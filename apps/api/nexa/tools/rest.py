"""No-code REST API connector."""

from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import quote

import httpx

from nexa.core.config import get_settings
from nexa.schemas.tool_definition import RestToolConfig
from nexa.tools.network import ensure_public_url
from nexa.tools.templating import drop_empty, expand_dotted, extract_mapped, render

MAX_RESPONSE_BYTES = 512_000
_transport: httpx.AsyncBaseTransport | None = None  # test hook


class RestToolError(Exception):
    def __init__(self, message: str, code: str = "api_error", status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def auth_headers(config: dict[str, Any], secrets: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (headers, query) for the integration's authentication. Secrets never leave the backend."""
    auth = config.get("auth", {"type": "none"})
    kind = auth.get("type", "none")
    if kind == "bearer" and secrets.get("token"):
        return {"Authorization": f"Bearer {secrets['token']}"}, {}
    if kind == "api_key" and secrets.get("api_key"):
        if auth.get("location", "header") == "query":
            return {}, {auth.get("name", "api_key"): secrets["api_key"]}
        return {auth.get("name", "X-API-Key"): secrets["api_key"]}, {}
    if kind == "basic" and secrets.get("username") is not None:
        token = base64.b64encode(f"{secrets['username']}:{secrets.get('password', '')}".encode()).decode()
        return {"Authorization": f"Basic {token}"}, {}
    return {}, {}


def build_request(cfg: RestToolConfig, args: dict[str, Any], integration_config: dict[str, Any],
                  secrets: dict[str, Any]) -> dict[str, Any]:
    base = integration_config.get("base_url", "").rstrip("/")
    if not base:
        raise RestToolError("The API connection has no base URL.", "misconfigured")

    def path_param(m: re.Match) -> str:
        v = args.get(m.group(1))
        if v in (None, ""):
            raise RestToolError(f'Missing information: "{m.group(1)}".', "missing_argument")
        return quote(str(v), safe="")

    path = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path_param, cfg.path)
    url = base + (path if path.startswith("/") else "/" + path)
    headers = {**integration_config.get("default_headers", {}), **cfg.headers}
    headers = {k: str(render(v, args)) for k, v in headers.items()}
    a_headers, a_query = auth_headers(integration_config, secrets)
    headers.update(a_headers)
    query = drop_empty(render(cfg.query, args))
    query.update(a_query)
    body = None
    if cfg.body is not None and cfg.method in ("POST", "PUT", "PATCH", "DELETE"):
        body = expand_dotted(drop_empty(render(cfg.body, args)))
    return {"method": cfg.method, "url": url, "headers": headers, "params": query, "json": body}


async def execute_rest_tool(cfg: RestToolConfig, args: dict[str, Any], *, integration_config: dict[str, Any],
                            secrets: dict[str, Any]) -> dict[str, Any]:
    req = build_request(cfg, args, integration_config, secrets)
    await ensure_public_url(req["url"])
    timeout = min(cfg.timeout_seconds, get_settings().integration_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, transport=_transport, follow_redirects=False) as client:
        try:
            resp = await client.request(req["method"], req["url"], headers=req["headers"], params=req["params"],
                                        json=req["json"])
        except httpx.TimeoutException as exc:
            raise RestToolError("The external system did not respond in time.", "timeout") from exc
        except httpx.HTTPError as exc:
            raise RestToolError("Could not reach the external system.", "connection_error") from exc
    if len(resp.content) > MAX_RESPONSE_BYTES:
        raise RestToolError("The external system returned too much data.", "response_too_large")
    try:
        data: Any = resp.json()
    except ValueError:
        data = resp.text[:2000]
    if resp.status_code >= 400:
        raise RestToolError(f"The external system returned an error ({resp.status_code}).",
                            "not_found" if resp.status_code == 404 else "api_error", resp.status_code)
    mapped = {k: extract_mapped(data, p) for k, p in cfg.response_mapping.items()} if cfg.response_mapping else data
    return {"status_code": resp.status_code, "data": mapped}
