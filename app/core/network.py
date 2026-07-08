import ipaddress
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.config import settings


class URLFetchError(ValueError):
    pass


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def fetch_public_url(url: str) -> bytes:
    current_url = url
    for _ in range(settings.url_fetch_max_redirects + 1):
        validate_public_url(current_url)
        request = Request(current_url, headers={"User-Agent": "ResearchOpsAgent/0.1"})
        try:
            with build_opener(NoRedirectHandler).open(request, timeout=settings.url_fetch_timeout_seconds) as response:
                return response.read(settings.max_upload_bytes + 1)
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise URLFetchError("Redirect response is missing a Location header.") from exc
                current_url = urljoin(current_url, location)
                continue
            raise URLFetchError(f"HTTP fetch failed with status {exc.code}.") from exc
        except (OSError, URLError) as exc:
            raise URLFetchError(f"Failed to fetch URL: {exc}") from exc
    raise URLFetchError("URL redirect limit exceeded.")


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise URLFetchError("Only http and https URLs are allowed.")
    if not parsed.hostname:
        raise URLFetchError("URL must include a hostname.")
    if parsed.username or parsed.password:
        raise URLFetchError("URLs with embedded credentials are not allowed.")

    allowed_domains = _allowed_domains()
    hostname = parsed.hostname.lower().rstrip(".")
    if allowed_domains and not _domain_allowed(hostname, allowed_domains):
        raise URLFetchError("URL hostname is not in the configured allowlist.")

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise URLFetchError(f"Could not resolve hostname: {hostname}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not _is_public_ip(ip):
            raise URLFetchError("URL resolves to a private or reserved network address.")


def _allowed_domains() -> list[str]:
    try:
        payload = json.loads(settings.url_fetch_allowlist_json)
    except json.JSONDecodeError:
        return []
    return [str(item).lower().rstrip(".") for item in payload if str(item).strip()]


def _domain_allowed(hostname: str, allowed_domains: list[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
