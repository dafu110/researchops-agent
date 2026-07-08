import io
import re
import zipfile

from app.core.config import settings
from app.core.network import URLFetchError, fetch_public_url


TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mdx",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def extract_github_repo_text(url: str, ref: str = "main") -> tuple[str, str]:
    owner, repo = parse_github_repo_url(url)
    archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"
    try:
        content = fetch_public_url(archive_url)
    except URLFetchError:
        if ref == "master":
            raise
        archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master"
        content = fetch_public_url(archive_url)

    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for info in archive.infolist():
            if info.is_dir() or _skip_path(info.filename) or not _is_text_path(info.filename):
                continue
            if info.file_size > settings.github_repo_file_max_bytes:
                continue
            with archive.open(info) as handle:
                raw = handle.read(settings.github_repo_file_max_bytes + 1)
            text = _decode_text(raw).strip()
            if not text:
                continue
            relative_path = "/".join(info.filename.split("/")[1:])
            parts.append(f"## {relative_path}\n{text[: settings.github_repo_file_max_bytes]}")
            if len("\n\n".join(parts)) > settings.github_repo_max_text_chars:
                break

    if not parts:
        raise ValueError("No supported text files found in GitHub repository.")
    return f"{owner}/{repo}", "\n\n".join(parts)[: settings.github_repo_max_text_chars]


def parse_github_repo_url(url: str) -> tuple[str, str]:
    match = re.match(r"^https://github\.com/([^/\s]+)/([^/\s#?]+)", url.strip())
    if not match:
        raise ValueError("Only https://github.com/{owner}/{repo} URLs are supported.")
    owner = match.group(1)
    repo = match.group(2).removesuffix(".git")
    return owner, repo


def _is_text_path(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(extension) for extension in TEXT_EXTENSIONS)


def _skip_path(path: str) -> bool:
    lowered = path.lower()
    skip_parts = (
        "/.git/",
        "/.pytest_cache/",
        "/.venv/",
        "/__pycache__/",
        "/build/",
        "/dist/",
        "/node_modules/",
    )
    return any(part in lowered for part in skip_parts)


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")
