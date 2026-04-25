import ipaddress
import re
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.local",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
}


def is_safe_http_url(url: str) -> bool:
    """Block obviously-internal targets before any outbound HTTP / Playwright call.

    Rejects:
      - non-http(s) schemes (file://, gopher://, javascript:, data: as a URL)
      - private / loopback / link-local / multicast / reserved IP literals
      - localhost / metadata-service hostnames
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    if host in _BLOCKED_HOSTNAMES:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


_EXT_OK = re.compile(r"^[a-z0-9]{1,8}$")


def safe_extension(ext: str | None, default: str = "bin") -> str:
    """Normalize a file extension to alphanumeric, max 8 chars.
    Strips dots, slashes, anything path-traversal-y.
    """
    if not ext:
        return default
    cleaned = re.sub(r"[^a-z0-9]", "", str(ext).lower())[:8]
    if not cleaned or not _EXT_OK.match(cleaned):
        return default
    return cleaned
