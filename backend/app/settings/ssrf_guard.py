from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


OFFICIAL_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_vl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm_v": "https://open.bigmodel.cn/api/paas/v4",
    "qwen_image": "https://dashscope.aliyuncs.com",
    "seedream": "https://ark.cn-beijing.volces.com/api/v3",
}

METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


def validate_base_url(
    provider_id: str,
    base_url: str,
    *,
    allow_custom_base_url: bool = False,
    allow_local_endpoint: bool = False,
    resolve_dns: bool = False,
) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("Base URL must use https.")
    if parsed.scheme != "https" and not allow_local_endpoint:
        raise ValueError("Base URL must use https unless a local endpoint is explicitly allowed.")
    if not parsed.hostname:
        raise ValueError("Base URL host is required.")
    official = OFFICIAL_BASE_URLS.get(provider_id)
    if official and not _same_origin_or_path(base_url, official) and not allow_custom_base_url:
        raise ValueError("Custom Base URL requires explicit advanced authorization.")
    _validate_host(parsed.hostname, allow_local_endpoint=allow_local_endpoint)
    if resolve_dns:
        _validate_dns(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), allow_local_endpoint)


def is_custom_base_url(provider_id: str, base_url: str) -> bool:
    official = OFFICIAL_BASE_URLS.get(provider_id)
    return bool(official and not _same_origin_or_path(base_url, official))


def _same_origin_or_path(value: str, official: str) -> bool:
    parsed_value = urlparse(value.rstrip("/"))
    parsed_official = urlparse(official.rstrip("/"))
    return (
        parsed_value.scheme == parsed_official.scheme
        and parsed_value.hostname == parsed_official.hostname
        and (parsed_value.path or "/").startswith(parsed_official.path or "/")
    )


def _validate_host(hostname: str, *, allow_local_endpoint: bool) -> None:
    lowered = hostname.strip().lower()
    if lowered in {"localhost"} and not allow_local_endpoint:
        raise ValueError("Localhost Base URL is blocked by default.")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return
    _validate_ip(ip, allow_local_endpoint=allow_local_endpoint)


def _validate_dns(hostname: str, port: int, allow_local_endpoint: bool) -> None:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Base URL host could not be resolved.") from exc
    for info in infos:
        address = info[4][0]
        _validate_ip(ipaddress.ip_address(address), allow_local_endpoint=allow_local_endpoint)


def _validate_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_local_endpoint: bool) -> None:
    if ip in METADATA_IPS:
        raise ValueError("Cloud metadata addresses are blocked.")
    if allow_local_endpoint and (ip.is_loopback or ip.is_private):
        return
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ValueError("Private, loopback, link-local, and reserved addresses are blocked.")
