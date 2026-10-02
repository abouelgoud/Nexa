import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select

from nexa.api.schemas import DocumentOut, DocumentTextIn, KnowledgeBaseIn, KnowledgeBaseOut, SearchIn
from nexa.core.config import get_settings
from nexa.core.deps import TenantContext, get_tenant_context, require
from nexa.core.errors import NotFound, ValidationFailed
from nexa.knowledge.service import retrieve
from nexa.models import Document, KnowledgeBase
from nexa.providers.registry import get_embeddings
from nexa.services.audit import audit
from nexa.services.jobs import enqueue

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
EXTENSIONS = {"pdf": "pdf", "docx": "docx", "txt": "txt", "md": "txt"}


async def _kb(ctx: TenantContext, kb_id: UUID) -> KnowledgeBase:
    kb = await ctx.db.get(KnowledgeBase, kb_id)
    if kb is None or kb.tenant_id != ctx.tenant_id or kb.deleted_at is not None:
        raise NotFound("Knowledge base not found.")
    return kb


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_kbs(ctx: TenantContext = Depends(get_tenant_context)):
    return list(await ctx.db.scalars(select(KnowledgeBase).where(KnowledgeBase.tenant_id == ctx.tenant_id,
                                                                 KnowledgeBase.deleted_at.is_(None))
                                     .order_by(KnowledgeBase.created_at)))


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
async def create_kb(body: KnowledgeBaseIn, ctx: TenantContext = Depends(require("write"))):
    kb = KnowledgeBase(tenant_id=ctx.tenant_id, name=body.name, description=body.description,
                       embedding_model=get_embeddings().model, created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(kb)
    await ctx.db.flush()
    audit(ctx, "knowledge.create", "knowledge_base", kb.id)
    await ctx.db.commit()
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: UUID, ctx: TenantContext = Depends(require("write"))):
    kb = await _kb(ctx, kb_id)
    kb.deleted_at = datetime.now(UTC)
    audit(ctx, "knowledge.delete", "knowledge_base", kb.id)
    await ctx.db.commit()


@router.get("/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(kb_id: UUID, ctx: TenantContext = Depends(get_tenant_context)):
    await _kb(ctx, kb_id)
    return list(await ctx.db.scalars(select(Document).where(Document.knowledge_base_id == kb_id,
                                                            Document.tenant_id == ctx.tenant_id,
                                                            Document.deleted_at.is_(None))
                                     .order_by(Document.created_at.desc())))


async def _add(ctx: TenantContext, kb: KnowledgeBase, title: str, source_type: str, raw: bytes | None,
               uri: str | None) -> Document:
    doc = Document(tenant_id=ctx.tenant_id, knowledge_base_id=kb.id, title=title, source_type=source_type,
                   source_uri=uri, raw_content=raw, size_bytes=len(raw or b""),
                   content_hash=hashlib.sha256(raw).hexdigest() if raw else None,
                   created_by=ctx.user.id, updated_by=ctx.user.id)
    ctx.db.add(doc)
    await ctx.db.flush()
    audit(ctx, "knowledge.add_document", "document", doc.id, {"title": title, "type": source_type})
    await enqueue(ctx.db, "ingest_document", {"document_id": str(doc.id)})
    await ctx.db.commit()
    await ctx.db.refresh(doc)
    return doc


@router.post("/{kb_id}/documents/upload", response_model=DocumentOut, status_code=201)
async def upload(kb_id: UUID, file: UploadFile = File(...), title: str | None = Form(None),
                 ctx: TenantContext = Depends(require("write"))):
    kb = await _kb(ctx, kb_id)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in EXTENSIONS:
        raise ValidationFailed("Upload a PDF, Word (.docx) or text file.")
    raw = await file.read(get_settings().max_upload_bytes + 1)
    if len(raw) > get_settings().max_upload_bytes:
        raise ValidationFailed("The file is too large.")
    return await _add(ctx, kb, title or file.filename or "Document", EXTENSIONS[ext], raw, file.filename)


@router.post("/{kb_id}/documents", response_model=DocumentOut, status_code=201)
async def add_text(kb_id: UUID, body: DocumentTextIn, ctx: TenantContext = Depends(require("write"))):
    kb = await _kb(ctx, kb_id)
    if body.source_type == "text":
        if not (body.content or "").strip():
            raise ValidationFailed("Enter some text.")
        return await _add(ctx, kb, body.title, "text", body.content.encode(), None)
    if body.source_type == "faq":
        if not body.faq:
            raise ValidationFailed("Add at least one question and answer.")
        return await _add(ctx, kb, body.title, "faq", json.dumps(body.faq, ensure_ascii=False).encode(), None)
    if not body.url:
        raise ValidationFailed("Enter the website address.")
    return await _add(ctx, kb, body.title, "url", None, body.url)


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(kb_id: UUID, doc_id: UUID, ctx: TenantContext = Depends(require("write"))):
    doc = await ctx.db.get(Document, doc_id)
    if doc is None or doc.tenant_id != ctx.tenant_id or doc.knowledge_base_id != kb_id:
        raise NotFound("Document not found.")
    doc.deleted_at = datetime.now(UTC)
    audit(ctx, "knowledge.delete_document", "document", doc.id)
    await ctx.db.commit()


@router.post("/{kb_id}/search")
async def search(kb_id: UUID, body: SearchIn, ctx: TenantContext = Depends(get_tenant_context)):
    await _kb(ctx, kb_id)
    return {"results": await retrieve(ctx.db, ctx.tenant_id, [kb_id], body.query, body.top_k)}
