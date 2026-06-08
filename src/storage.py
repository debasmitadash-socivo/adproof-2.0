"""Tier 2: handle Supabase-Storage URLs inside the simulate pipeline.

The wizard now uploads creatives directly to Supabase Storage (bucket
``ad-creatives``) and sends the resulting signed URL to the backend as
``image_path`` / ``video_path``. The vision providers and PIL all expect
local file paths, so this module bridges the gap: it detects URLs,
downloads them to per-request temp files, and returns those temp paths.

Crucially, the download happens INSIDE the request handler — once the
request finishes, the temp file is cleaned up. Nothing persistent ever
lives on the Railway disk, so a redeploy can never wipe an upload again.

Design choices:
- Streaming download (`requests.iter_content`) so a 25MB video doesn't
  read into a single in-memory string before hitting disk.
- 25MB cap (mirrors the bucket limit) to refuse runaway responses if
  Supabase ever served the wrong file.
- Cleanup via `RemoteFile.__enter__/__exit__` — context-manager pattern
  so the caller can't forget to delete the temp file.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests

__all__ = [
    "is_remote_url",
    "download_to_temp",
    "RemoteFile",
]


# Hard cap mirrors the Supabase bucket's file_size_limit so a misconfigured
# bucket can't make us hold 200MB in memory or disk by accident.
_MAX_BYTES = 25 * 1024 * 1024
_CHUNK = 256 * 1024


def is_remote_url(path) -> bool:
    """True when ``path`` looks like an http(s) URL we need to download.

    Local-disk paths starting with '/' or relative paths fall through to
    the existing behaviour unchanged. Signed Supabase URLs always begin
    with 'https://'.
    """
    if not path:
        return False
    s = str(path)
    return s.startswith("http://") or s.startswith("https://")


def _safe_suffix(url: str, content_type: str | None) -> str:
    """Pick a file extension for the temp file so PIL / Gemini can sniff
    the type from the path. URL-path extension wins; otherwise we map
    from the Content-Type header; otherwise we degrade to '.bin'.
    """
    parsed = urlparse(url)
    name = Path(parsed.path).name              # strips query string
    suffix = Path(name).suffix.lower()
    if suffix:
        return suffix
    mime = (content_type or "").split(";")[0].strip().lower()
    return {
        "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/webp": ".webp", "image/gif": ".gif",
        "video/mp4": ".mp4", "video/quicktime": ".mov",
        "video/webm": ".webm", "video/x-matroska": ".mkv",
        "video/3gpp": ".3gp", "video/x-msvideo": ".avi",
        "video/mpeg": ".mpeg",
    }.get(mime, ".bin")


def download_to_temp(url: str, *, timeout: float = 30.0) -> Path:
    """Stream ``url`` to a temp file and return the path.

    Raises FileNotFoundError when the URL 404s (so the existing
    'uploads vanished' branch in check_image_specs surfaces the same
    honest 'file no longer on the server' message — the signed URL
    expired or the user deleted the asset).
    """
    try:
        r = requests.get(url, stream=True, timeout=timeout)
    except requests.RequestException as exc:
        raise FileNotFoundError(
            f"Could not fetch uploaded creative ({exc})") from exc
    # Signed URLs 400 for expired sigs, 404 for missing objects — both mean
    # 'file is gone' from the user's POV, so we collapse them into
    # FileNotFoundError to reuse the existing honest error path.
    if r.status_code in (400, 401, 403, 404, 410):
        raise FileNotFoundError(
            f"Uploaded creative is no longer reachable (HTTP {r.status_code}).")
    r.raise_for_status()

    suffix = _safe_suffix(url, r.headers.get("Content-Type"))
    fd, tmp_path = tempfile.mkstemp(prefix="adproof_dl_", suffix=suffix)
    written = 0
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                written += len(chunk)
                if written > _MAX_BYTES:
                    raise ValueError(
                        f"Downloaded creative exceeds {_MAX_BYTES // 1_048_576}MB "
                        f"limit — refusing to load it.")
                f.write(chunk)
    except Exception:
        # Best-effort cleanup if download fails midway.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return Path(tmp_path)


class RemoteFile:
    """Context manager — download a URL on enter, delete the temp file on exit.

    Usage:
        with RemoteFile(image_path_or_url) as local_path:
            run_vision(local_path)

    If the input is already a local path, ``local_path`` is just that path
    and exit is a no-op — so callers can wrap unconditionally.
    """

    def __init__(self, path_or_url):
        self._original = path_or_url
        self._tmp: Path | None = None

    def __enter__(self) -> Path | None:
        if not self._original:
            return None
        if is_remote_url(self._original):
            self._tmp = download_to_temp(str(self._original))
            return self._tmp
        return Path(self._original)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmp is not None:
            try:
                os.unlink(self._tmp)
            except OSError:
                pass
