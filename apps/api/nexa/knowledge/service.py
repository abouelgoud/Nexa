"""Knowledge ingestion and retrieval (pgvector), with internal citations."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.knowledge.parsing import ParseError, chunk_sections, parse_document
from nexa.models import Document, DocumentChunk, KnowledgeBase
from nexa.nlp.arabic import matching_key, normalize_text, similarity
from nexa.providers.registry import get_embeddings
from nexa.services.usage import record_usage
from nexa.tools.network import BlockedDestination, ensure_public_url

MIN_SCORE = 0.2


async def fetch_url(url: str) -> bytes:
    await ensure_public_url(url)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        r = await client.get(url, headers={"User-Agent": "NexaKnowledgeBot/1.0"})
    if r.status_code >= 400:
        raise ParseError(f"The website returned an error ({r.status_code}).")
    return r.content[:5_000_000]


async def ingest_document(db: AsyncSession, document_id: UUID) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise ValueError("document not found")
    doc.status, doc.error = "processing", None
    await db.flush()
    try:
        raw = doc.raw_content
        if doc.source_type == "url":
            raw = await fetch_url(doc.source_uri or "")
        if not raw:
            raise ParseError("The document is empty.")
        sections = parse_document(doc.source_type, raw)
        chunks = chunk_sections(sections)
        if not chunks:
            raise ParseError("No text was found in the document.")
        embedder = get_embeddings()
        vectors = await embedder.embed([c["content"] for c in chunks])
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        for i, (c, v) in enumerate(zip(chunks, vectors, strict=True)):
            db.add(DocumentChunk(tenant_id=doc.tenant_id, document_id=doc.id, knowledge_base_id=doc.knowledge_base_id,
                                 chunk_index=i, content=c["content"], normalized_content=matching_key(c["content"]),
                                 embedding=v, meta={**c["meta"], "embedding_model": embedder.model}))
        doc.chunk_count = len(chunks)
        doc.content_hash = hashlib.sha256(raw).hexdigest()
        doc.size_bytes = len(raw)
        doc.status = "ready"
        kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
        if kb and kb.embedding_model != embedder.model:
            kb.embedding_model = embedder.model
        record_usage(db, doc.tenant_id, "storage_bytes", len(raw), meta={"document_id": str(doc.id)})
    except (ParseError, BlockedDestination) as exc:
        doc.status, doc.error = "failed", str(exc)
    except httpx.HTTPError:
        doc.status, doc.error = "failed", "The website could not be reached."
    await db.flush()
    return doc


async def retrieve(db: AsyncSession, tenant_id: UUID, kb_ids: list[UUID], query: str, top_k: int = 4) -> list[dict[str, Any]]:
    if not kb_ids or not query.strip():
        return []
    embedder = get_embeddings()
    [qv] = await embedder.embed([normalize_text(query)])
    rows = (await db.execute(
        text(
            "SELECT c.id, c.document_id, c.content, c.metadata, d.title, 1 - (c.embedding <=> CAST(:q AS vector)) AS score "
            "FROM document_chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE c.tenant_id = :tenant AND c.knowledge_base_id = ANY(:kbs) AND d.deleted_at IS NULL "
            "AND d.status = 'ready' AND c.metadata->>'embedding_model' = :model "
            "ORDER BY c.embedding <=> CAST(:q AS vector) LIMIT :k"
        ),
        {"q": str(qv), "tenant": tenant_id, "kbs": list(kb_ids), "model": embedder.model, "k": top_k * 3},
    )).all()
    results = []
    for r in rows:
        lexical = similarity(query, r.content)
        score = 0.75 * float(r.score) + 0.25 * lexical
        if score < MIN_SCORE:
            continue
        results.append({"chunk_id": str(r.id), "document_id": str(r.document_id), "document_title": r.title,
                        "content": r.content, "score": round(score, 3), "metadata": r.metadata})
    results.sort(key=lambda x: -x["score"])
    return results[:top_k]



async def kb_ids_for_tenant(db: AsyncSession, tenant_id: UUID, ids: list[UUID]) -> list[UUID]:
    rows = await db.scalars(select(KnowledgeBase.id).where(KnowledgeBase.tenant_id == tenant_id,
                                                           KnowledgeBase.id.in_(ids),
                                                           KnowledgeBase.deleted_at.is_(None)))
    return list(rows)
