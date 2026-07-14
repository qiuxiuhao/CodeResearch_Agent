from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from backend.app.image_generation.exceptions import ImageGenerationError


BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SafeImageDownloader:
    def __init__(self, allowed_domains: list[str], *, timeout_seconds: float, max_bytes: int) -> None:
        self.allowed_domains = {item.lower() for item in allowed_domains}
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def download(self, url: str) -> tuple[bytes, str]:
        current = url
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            for _ in range(5):
                self._validate_url(current)
                response = client.get(current)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageGenerationError("image_download_redirect_invalid", "Image URL redirect has no Location header.")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                data = b""
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > self.max_bytes:
                        raise ImageGenerationError("image_download_too_large", "Downloaded image exceeded byte limit.")
                return data, response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
        raise ImageGenerationError("image_download_redirect_limit", "Image URL redirected too many times.")

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            raise ImageGenerationError("image_download_scheme_blocked", "Only HTTPS image URLs are allowed.")
        host = (parsed.hostname or "").lower()
        if not host or not _domain_allowed(host, self.allowed_domains):
            raise ImageGenerationError("image_download_domain_blocked", "Image URL host is not in the allowlist.")
        for info in socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP):
            address = ipaddress.ip_address(info[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or any(address in net for net in BLOCKED_NETWORKS):
                raise ImageGenerationError("image_download_ssrf_blocked", "Image URL resolved to a blocked network.")


def _domain_allowed(host: str, allowed_domains: set[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)
