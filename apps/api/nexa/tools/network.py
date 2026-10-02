"""SSRF protection for customer-configured integrations."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from nexa.core.config import get_settings


class BlockedDestination(ValueError):
    pass


async def ensure_public_host(host: str) -> None:
    if get_settings().allow_private_network_integrations:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedDestination(f"The address {host} could not be found.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BlockedDestination(f"Connections to internal network addresses ({host}) are not allowed.")


async def ensure_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedDestination("Only http(s) URLs are allowed.")
    await ensure_public_host(parsed.hostname)
