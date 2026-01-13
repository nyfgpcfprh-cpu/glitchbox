from __future__ import annotations

import argparse
import json
import sys
import mimetypes
import hashlib
import os
import urllib.request
import ssl
from pathlib import Path
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse, urlencode
import subprocess
import time

from python.db import (
    Database,
    Page,
    add_item_to_playlist,
    apply_migrations,
    create_playlist,
    create_user,
    delete_playlist,
    get_continue_watching,
    get_continue_watching_groups,
    get_playlist_items,
    get_playlists_for_user,
    get_recently_added,
    get_setting,
    list_library_media_files,
    list_library_groups,
    get_user_id,
    get_media_file_by_id,
    upsert_playback_progress,
    move_playlist_item,
    remove_item_from_playlist,
    rename_playlist,
    set_setting,
    set_user_password,
    list_libraries,
    create_library,
    rename_library,
    add_library_root,
    list_library_roots,
    remove_library_root,
    attach_artwork,
    detach_artwork,
    get_artwork_for_internal_key,
    list_external_artwork,
    list_settings,
)

# --- WebUI/scan support
from python.app.scanner import get_scanner_engine


@dataclass(frozen=True)
class ServiceResult:
    """Standard response shape for both CLI and HTTP endpoints."""

    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class MediaServerService:
    """
    Phase 1B service layer (transport-agnostic).

    This keeps:
      - raw SQL in python/db.py
      - endpoint + CLI wiring in python/main.py
      - validation + “run migrations” here
    """

    def __init__(self, db_path: str) -> None:
        self.db = Database(db_path)

    def _init_db(self) -> None:
        with self.db.tx() as conn:
            apply_migrations(conn)

    # -----------------
    # Users
    # -----------------

    def ensure_user(self, username: str) -> int:
        self._init_db()
        with self.db.tx() as conn:
            uid = get_user_id(conn, username)
            if uid is not None:
                return uid
            return create_user(conn, username)

    def set_password(self, user_id: int, new_password: str) -> None:
        """Set/replace a user's password hash (does not enforce auth yet)."""
        self._init_db()
        with self.db.tx() as conn:
            set_user_password(conn, user_id=user_id, new_password=new_password)

    # -----------------
    # Libraries
    # -----------------

    def libraries(self, *, limit: int = 50, offset: int = 0) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_libraries(conn, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    def library_create(self, name: str) -> int:
        self._init_db()
        with self.db.tx() as conn:
            return create_library(conn, name=name)

    def library_rename(self, library_id: int, name: str) -> None:
        self._init_db()
        with self.db.tx() as conn:
            rename_library(conn, library_id=library_id, name=name)

    def library_roots(self, *, library_id: int, limit: int = 50, offset: int = 0) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_library_roots(conn, library_id=library_id, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    def library_root_add(self, library_id: int, root_path: str, recursive: bool = True) -> int:
        self._init_db()
        with self.db.tx() as conn:
            return add_library_root(conn, library_id=library_id, root_path=root_path, recursive=recursive)

    def library_root_remove(self, root_id: int) -> None:
        self._init_db()
        with self.db.tx() as conn:
            remove_library_root(conn, root_id=root_id)

    def libraries_with_counts(self, *, limit: int = 50, offset: int = 0) -> ServiceResult:
        """List libraries along with the number of indexed media files in each.

        This is what the WebUI will typically show (e.g., Movies (546)).
        Counts are file-level counts from `media_files`.
        """
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_libraries(conn, page=page)
            counts = {
                int(r[0]): int(r[1])
                for r in conn.execute(
                    "SELECT library_id, COUNT(1) FROM media_files GROUP BY library_id;"
                ).fetchall()
            }

        # Enrich items with media_count without changing DB-layer contracts.
        enriched: List[Dict[str, Any]] = []
        for it in items:
            lib_id = int(it.get("id"))
            it2 = dict(it)
            it2["media_count"] = counts.get(lib_id, 0)
            enriched.append(it2)

        return ServiceResult(items=enriched, total=total, limit=limit, offset=offset)

    def scan(self, *, engine: str = "simple", dry_run: bool = False, extensions: str | None = None) -> Dict[str, Any]:
        """Trigger a scan of all mounted library roots.

        - engine: "simple" (Option A) or "plugin" (Option B hook)
        - dry_run: if true, do not write to DB
        - extensions: optional comma-separated list like ".mkv,.mp4"

        Returns scan stats.
        """
        self._init_db()

        allowed_exts = None
        if extensions:
            allowed_exts = {e.strip().lower() for e in extensions.split(",") if e.strip()}

        eng = get_scanner_engine(engine)
        with self.db.tx() as conn:
            stats = eng.scan(conn, allowed_exts=allowed_exts, dry_run=dry_run)
        return stats

    # -----------------
    # Recently Added
    # -----------------


    def recently_added(self, library_id: int, limit: int, offset: int) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = get_recently_added(conn, library_id=library_id, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    # -----------------
    # Full Library Browse
    # -----------------

    def library_media_files(
        self,
        *,
        library_id: int,
        limit: int,
        offset: int,
        order: str = "title_asc",
        q: str | None = None,
        group_key: str | None = None,
    ) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_library_media_files(
                conn,
                library_id=library_id,
                page=page,
                order=order,
                q=q,
                group_key=group_key,
            )
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    # -----------------
    # Library Groups (TV hierarchy)
    # -----------------

    def library_groups(
        self,
        *,
        library_id: int,
        prefix: str,
        limit: int,
        offset: int,
    ) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_library_groups(conn, library_id=library_id, prefix=prefix, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    # -----------------
    # Continue Watching
    # -----------------

    def continue_watching(self, user_id: int, limit: int, offset: int) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = get_continue_watching(conn, user_id=user_id, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    def continue_watching_groups(self, user_id: int, limit: int, offset: int) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = get_continue_watching_groups(conn, user_id=user_id, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    # -----------------
    # App Settings (simple key/value)
    # -----------------

    def get_setting(self, key: str) -> str | None:
        self._init_db()
        with self.db.tx() as conn:
            return get_setting(conn, key=key)

    def list_settings(self, keys: List[str] | None = None) -> List[Dict[str, Any]]:
        self._init_db()
        with self.db.tx() as conn:
            return list_settings(conn, keys=keys)

    def set_settings(self, settings: Dict[str, Any]) -> None:
        self._init_db()
        with self.db.tx() as conn:
            for k, v in (settings or {}).items():
                set_setting(conn, key=str(k), value=None if v is None else str(v))

    # -----------------
    # Artwork (explicit, optional)
    # -----------------

    def get_artwork(self, internal_key: str) -> Dict[str, Any] | None:
        self._init_db()
        with self.db.tx() as conn:
            return get_artwork_for_internal_key(conn, internal_key=internal_key)

    def list_artwork(self, limit: int, offset: int) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_external_artwork(conn, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    def attach_artwork(
        self,
        *,
        internal_key: str,
        provider: str,
        provider_id: str,
        poster_url: str | None,
        confidence: str = "manual",
    ) -> None:
        self._init_db()
        with self.db.tx() as conn:
            attach_artwork(
                conn,
                internal_key=internal_key,
                provider=provider,
                provider_id=provider_id,
                poster_url=poster_url,
                confidence=confidence,
            )

    def detach_artwork(self, internal_key: str) -> None:
        self._init_db()
        with self.db.tx() as conn:
            detach_artwork(conn, internal_key=internal_key)

    def set_playback_progress(
        self,
        *,
        user_id: int,
        media_file_id: int,
        position_seconds: int,
        duration_seconds: int,
        completed: bool | None = None,
    ) -> None:
        """Create/update playback progress for a user + media file.

        If `completed` is provided, trust the client.
        Otherwise, completion is computed in the DB layer when duration is known.
        """
        self._init_db()
        with self.db.tx() as conn:
            upsert_playback_progress(
                conn,
                user_id=user_id,
                media_file_id=media_file_id,
                position_seconds=position_seconds,
                duration_seconds=duration_seconds,
                completed=completed,
            )

    # -----------------
    # Playlists
    # -----------------

    def playlists(self, user_id: int, limit: int, offset: int) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = get_playlists_for_user(conn, user_id=user_id, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    def playlist_items(self, playlist_id: int, limit: int, offset: int) -> ServiceResult:
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = get_playlist_items(conn, playlist_id=playlist_id, page=page)
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    def playlist_create(self, user_id: int, name: str) -> int:
        self._init_db()
        with self.db.tx() as conn:
            return create_playlist(conn, user_id=user_id, name=name)

    def playlist_rename(self, playlist_id: int, name: str) -> None:
        self._init_db()
        with self.db.tx() as conn:
            rename_playlist(conn, playlist_id=playlist_id, name=name)

    def playlist_delete(self, playlist_id: int) -> None:
        self._init_db()
        with self.db.tx() as conn:
            delete_playlist(conn, playlist_id=playlist_id)

    def playlist_add_item(self, playlist_id: int, media_file_id: int) -> int:
        """Adds a title to the playlist. Does NOT touch disk files."""
        self._init_db()
        with self.db.tx() as conn:
            return add_item_to_playlist(conn, playlist_id=playlist_id, media_file_id=media_file_id)

    def playlist_remove_item(self, playlist_id: int, playlist_item_id: int) -> None:
        """Removes the title from the playlist. Does NOT delete media files."""
        self._init_db()
        with self.db.tx() as conn:
            remove_item_from_playlist(conn, playlist_id=playlist_id, playlist_item_id=playlist_item_id)

    def playlist_move_item(self, playlist_id: int, playlist_item_id: int, new_position: int) -> None:
        self._init_db()
        with self.db.tx() as conn:
            move_playlist_item(
                conn,
                playlist_id=playlist_id,
                playlist_item_id=playlist_item_id,
                new_position=new_position,
            )


# -----------------
# WebUI static file serving (same-origin)
# -----------------

# Repo layout (current): GlitchBox/python/main.py
# WebUI layout:        GlitchBox/webui/public/*  and GlitchBox/webui/src/*
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent
_WEBUI_PUBLIC_DIR = (_REPO_ROOT / "webui" / "public").resolve()
_WEBUI_SRC_DIR = (_REPO_ROOT / "webui" / "src").resolve()

_ARTWORK_DIR = (_REPO_ROOT / "data" / "artwork").resolve()

# HLS cache directory
_HLS_DIR = (_REPO_ROOT / "data" / "hls").resolve()

# In-memory HLS ffmpeg job registry
_HLS_JOBS: Dict[int, subprocess.Popen[bytes]] = {}

# TMDB configuration
_TMDB_API_BASE = "https://api.themoviedb.org/3"
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context for outbound HTTPS calls.

    Default: verify certificates.
    Dev escape hatch: set GLITCHBOX_INSECURE_SSL=1 to disable verification.
    """
    insecure = (os.environ.get("GLITCHBOX_INSECURE_SSL") or "").strip() == "1"
    if insecure:
        # Explicitly unsafe: only for local dev troubleshooting.
        return ssl._create_unverified_context()  # noqa: SLF001

    ctx = ssl.create_default_context()
    # If certifi is available, use it (helps some macOS Python installs).
    try:
        import certifi  # type: ignore

        ctx.load_verify_locations(certifi.where())
    except Exception:
        # Fall back to system trust store.
        pass

    return ctx


def _tmdb_api_key_env() -> str:
    # Explicit: require env var, no guessing
    return (os.environ.get("TMDB_API_KEY") or "").strip()


def _tmdb_get_json(path: str, params: Dict[str, Any], *, api_key: str | None = None) -> Dict[str, Any]:
    key = (api_key or "").strip() or _tmdb_api_key_env()
    if not key:
        raise ValueError("TMDB_API_KEY is not set")

    q = dict(params or {})
    q["api_key"] = key

    url = f"{_TMDB_API_BASE}{path}?{urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _cache_tmdb_image(*, kind: str, tmdb_type: str, tmdb_id: str, file_path: str, size: str = "original") -> str:
    """Download and cache a TMDB image locally, returning a server URL path.

    Example return: /artwork/tmdb/movie/603/poster_<hash>.jpg
    """
    if not file_path or not file_path.startswith("/"):
        raise ValueError("file_path must start with '/'")

    tmdb_type = (tmdb_type or "").strip().lower()
    if tmdb_type not in ("movie", "tv"):
        raise ValueError("tmdb_type must be movie or tv")

    kind = (kind or "").strip().lower()
    if kind not in ("poster", "backdrop"):
        raise ValueError("kind must be poster or backdrop")

    tmdb_id = str(tmdb_id).strip()
    if not tmdb_id:
        raise ValueError("tmdb_id is required")

    ext = Path(file_path).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"

    h = _sha1(f"tmdb:{tmdb_type}:{tmdb_id}:{kind}:{file_path}")
    fname = f"{kind}_{h}{ext}"

    rel = Path("tmdb") / tmdb_type / tmdb_id / fname
    dst = (_ARTWORK_DIR / rel).resolve()

    if _safe_resolve(_ARTWORK_DIR, str(rel)) != dst:
        raise ValueError("invalid artwork path")

    if not dst.exists():
        _ensure_dir(dst.parent)
        img_url = f"{_TMDB_IMAGE_BASE}/{size}{file_path}"
        req = urllib.request.Request(img_url, headers={"User-Agent": "GlitchBox/0.1"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            dst.write_bytes(resp.read())

    return f"/artwork/{rel.as_posix()}"


def _guess_content_type(p: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(p))
    # Ensure JS is correct even if the platform mime map is odd.
    if p.suffix == ".js":
        return "text/javascript; charset=utf-8"
    if p.suffix == ".css":
        return "text/css; charset=utf-8"
    if p.suffix in (".html", ".htm"):
        return "text/html; charset=utf-8"
    return ctype or "application/octet-stream"


def _safe_resolve(base: Path, rel_url_path: str) -> Path | None:
    """Resolve a URL path to a filesystem path under `base`.

    Prevents path traversal. Returns None if the resolved path escapes base.
    """
    rel = rel_url_path.lstrip("/")
    candidate = (base / rel).resolve()
    try:
        base_resolved = base.resolve()
    except Exception:
        base_resolved = base

    try:
        candidate.relative_to(base_resolved)
        return candidate
    except ValueError:
        return None



def _serve_file(handler: BaseHTTPRequestHandler, fs_path: Path) -> bool:
    """Serve a file from disk. Returns True if served."""
    if not fs_path.exists() or not fs_path.is_file():
        return False

    data = fs_path.read_bytes()
    handler.send_response(200)
    _add_cors_headers(handler)
    handler.send_header("Content-Type", _guess_content_type(fs_path))
    handler.send_header("Content-Length", str(len(data)))
    # Simple caching behavior for local dev; safe to keep minimal.
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(data)
    return True


# Serve only headers for a file (HEAD)
def _serve_file_head(handler: BaseHTTPRequestHandler, fs_path: Path) -> bool:
    """Serve only headers for a file from disk (HEAD). Returns True if served."""
    if not fs_path.exists() or not fs_path.is_file():
        return False

    handler.send_response(200)
    _add_cors_headers(handler)
    handler.send_header("Content-Type", _guess_content_type(fs_path))
    handler.send_header("Content-Length", str(fs_path.stat().st_size))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    return True


# -----------------
# HTTP JSON API (minimal)
# -----------------


def _int_qs(qs: Dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(qs.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        return default


def _cors_allow_origin(handler: BaseHTTPRequestHandler) -> str:
    """Return an allowed Origin value for CORS.

    We keep this explicit (no "*") so credentials can be enabled later if needed.
    """
    origin = (handler.headers.get("Origin") or "").strip()

    # Allow local dev UI servers.
    allowed = {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    }

    if origin in allowed:
        return origin

    # If no Origin header is present (curl, server-to-server), do not emit CORS.
    return ""


def _add_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    """Add CORS headers for local development UI calls."""
    allow_origin = _cors_allow_origin(handler)
    if not allow_origin:
        return

    handler.send_header("Access-Control-Allow-Origin", allow_origin)
    handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    # NOTE: We are not enabling credentials yet. If you later need cookies/auth,
    # add: handler.send_header("Access-Control-Allow-Credentials", "true")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    _add_cors_headers(handler)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


class ApiHandler(BaseHTTPRequestHandler):
    # Set by run_server()
    svc: "MediaServerService"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write((fmt % args) + "\n")

    def do_OPTIONS(self) -> None:
        """CORS preflight support for the WebUI running on a different port."""
        self.send_response(204)
        _add_cors_headers(self)
        self.end_headers()

    def _guess_stream_content_type(self, file_path: str) -> str:
        ctype, _ = mimetypes.guess_type(file_path)
        return ctype or "application/octet-stream"

    def _serve_fs_file_stream(self, fs_path: Path, *, content_type: str) -> None:
        """Stream a filesystem file without loading it all into memory."""
        if not fs_path.exists() or not fs_path.is_file():
            _json_response(self, 404, {"error": "not_found"})
            return

        size = fs_path.stat().st_size
        self.send_response(200)
        _add_cors_headers(self)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        with fs_path.open("rb") as f:
            chunk = 1024 * 256
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                self.wfile.write(buf)

    def _ensure_hls(self, *, media_id: int) -> Dict[str, str]:
        """Ensure an HLS playlist exists for this media file.

        Returns paths (as URL paths) for master + media playlist.
        This is explicit, inspectable, and cached on disk under data/hls/<id>/.
        """
        _ensure_dir(_HLS_DIR)

        self.svc._init_db()
        with self.svc.db.tx() as conn:
            mf = get_media_file_by_id(conn, media_file_id=media_id)

        if not mf:
            raise ValueError("media not found")

        file_path = str(mf.get("file_path") or "").strip()
        if not file_path or not os.path.exists(file_path):
            raise ValueError("file missing")

        # Per-media cache directory
        out_dir = (_HLS_DIR / str(media_id)).resolve()
        _ensure_dir(out_dir)

        master_fs = (out_dir / "master.m3u8").resolve()
        index_fs = (out_dir / "index.m3u8").resolve()

        # If already generated (or partially generated), use it.
        if master_fs.exists() and index_fs.exists():
            return {
                "master": f"/hls/{media_id}/master.m3u8",
                "index": f"/hls/{media_id}/index.m3u8",
            }

        # Write a very small master that references a single variant.
        # Keep it explicit and stable.
        master_body = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=3000000\n"
            "index.m3u8\n"
        )
        master_fs.write_text(master_body, encoding="utf-8")

        # Start ffmpeg only once per media_id.
        proc = _HLS_JOBS.get(media_id)
        if proc is None or (proc.poll() is not None):
            # Segment duration sets seek granularity. 2s gives better +/-10s behavior.
            # We output TS segments for broad Roku compatibility.
            seg_pat = str((out_dir / "seg_%05d.ts").resolve())
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                file_path,

                # Force consistent keyframes for clean 2s HLS segments
                "-g",
                "48",
                "-keyint_min",
                "48",
                "-sc_threshold",
                "0",
                "-force_key_frames",
                "expr:gte(t,n_forced*2)",

                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",

                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ac",
                "2",

                "-f",
                "hls",
                "-hls_time",
                "2",
                "-hls_list_size",
                "0",
                "-hls_playlist_type",
                "event",
                "-hls_segment_filename",
                seg_pat,
                str(index_fs),
            ]

            _HLS_JOBS[media_id] = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Wait briefly for the index playlist to appear so first playback starts quickly.
        t0 = time.time()
        while not index_fs.exists() and (time.time() - t0) < 2.0:
            time.sleep(0.05)

        return {
            "master": f"/hls/{media_id}/master.m3u8",
            "index": f"/hls/{media_id}/index.m3u8",
        }

    def _send_file_range(
        self,
        *,
        file_path: str,
        content_type: str,
        range_header: str | None,
        head_only: bool,
    ) -> None:
        file_size = os.path.getsize(file_path)

        start = 0
        end = file_size - 1
        status = 200

        if range_header and range_header.startswith("bytes="):
            spec = range_header[len("bytes="):].strip()

            # Multiple ranges are not supported.
            if "," in spec:
                _json_response(self, 416, {"error": "range_not_supported"})
                return

            if spec.startswith("-"):
                # Suffix: last N bytes
                try:
                    suffix = int(spec[1:])
                    if suffix <= 0:
                        raise ValueError()
                    start = max(0, file_size - suffix)
                except Exception:
                    _json_response(self, 416, {"error": "invalid_range"})
                    return
            else:
                parts = spec.split("-", 1)
                try:
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if len(parts) > 1 and parts[1] else end
                except Exception:
                    _json_response(self, 416, {"error": "invalid_range"})
                    return

            if start < 0 or start >= file_size or end < start:
                _json_response(self, 416, {"error": "invalid_range"})
                return

            end = min(end, file_size - 1)
            status = 206

        length = (end - start) + 1

        self.send_response(status)
        _add_cors_headers(self)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        if head_only:
            return

        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk = 1024 * 256
            while remaining > 0:
                n = chunk if remaining > chunk else remaining
                buf = f.read(n)
                if not buf:
                    break
                self.wfile.write(buf)
                remaining -= len(buf)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # Mirror static/artwork handling from do_GET, but headers only.
        if path == "/" or path == "/index.html":
            index_path = (_WEBUI_PUBLIC_DIR / "index.html").resolve()
            if _serve_file_head(self, index_path):
                return
            self.send_error(404)
            return

        if path == "/app.css":
            css_path = (_WEBUI_PUBLIC_DIR / "app.css").resolve()
            if _serve_file_head(self, css_path):
                return
            self.send_error(404)
            return

        if path.startswith("/assets/"):
            rel = path[len("/"):]  # "assets/..."
            fs = _safe_resolve(_WEBUI_PUBLIC_DIR, rel)
            if fs and _serve_file_head(self, fs):
                return
            self.send_error(404)
            return

        if path.startswith("/src/"):
            rel = path[len("/src/"):]  # relative under src
            fs = _safe_resolve(_WEBUI_SRC_DIR, rel)
            if fs and _serve_file_head(self, fs):
                return
            self.send_error(404)
            return

        if path.startswith("/artwork/"):
            rel = path[len("/artwork/"):]
            fs = _safe_resolve(_ARTWORK_DIR, rel)
            if fs and _serve_file_head(self, fs):
                return
            self.send_error(404)
            return

        # Streaming (headers-only)
        if path.startswith("/stream/"):
            media_id_str = path.split("/", 2)[2]
            try:
                media_id = int(media_id_str)
            except Exception:
                _json_response(self, 400, {"error": "bad_request", "detail": "invalid media_file_id"})
                return

            try:
                self.svc._init_db()
                with self.svc.db.tx() as conn:
                    mf = get_media_file_by_id(conn, media_file_id=media_id)
            except Exception as e:
                _json_response(self, 500, {"error": "server_error", "detail": str(e)})
                return

            if not mf:
                _json_response(self, 404, {"error": "not_found"})
                return

            file_path = str(mf.get("file_path") or "").strip()
            if not file_path or not os.path.exists(file_path):
                _json_response(self, 404, {"error": "file_missing"})
                return

            ctype = self._guess_stream_content_type(file_path)
            self._send_file_range(
                file_path=file_path,
                content_type=ctype,
                range_header=self.headers.get("Range"),
                head_only=True,
            )
            return

        # HLS (headers-only)
        if path.startswith("/hls/"):
            parts = path.strip("/").split("/")
            if len(parts) < 3:
                _json_response(self, 400, {"error": "bad_request", "detail": "invalid hls path"})
                return

            try:
                media_id = int(parts[1])
            except Exception:
                _json_response(self, 400, {"error": "bad_request", "detail": "invalid media_file_id"})
                return

            name = parts[2]
            if name in ("master.m3u8", "index.m3u8"):
                try:
                    self._ensure_hls(media_id=media_id)
                except Exception:
                    # Keep HEAD minimal
                    self.send_error(404)
                    return

            fs = _safe_resolve(_HLS_DIR, "/".join(parts[1:]))
            if not fs or not fs.exists() or not fs.is_file():
                self.send_error(404)
                return

            self.send_response(200)
            _add_cors_headers(self)
            if name.endswith(".m3u8"):
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            elif name.endswith(".ts"):
                self.send_header("Content-Type", "video/MP2T")
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(fs.stat().st_size))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return

        # For API routes, keep it explicit.
        _json_response(self, 405, {"error": "method_not_allowed"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # --- WebUI static files (served from same origin as API)
        # This avoids CORS problems when the browser calls the API.
        # Hash-routing means most navigation stays on "/", but we also serve
        # assets + module JS under /src/.
        if path == "/" or path == "/index.html":
            index_path = (_WEBUI_PUBLIC_DIR / "index.html").resolve()
            if _serve_file(self, index_path):
                return

        if path == "/app.css":
            css_path = (_WEBUI_PUBLIC_DIR / "app.css").resolve()
            if _serve_file(self, css_path):
                return

        if path.startswith("/assets/"):
            rel = path[len("/"):]  # "assets/..."
            fs = _safe_resolve(_WEBUI_PUBLIC_DIR, rel)
            if fs and _serve_file(self, fs):
                return

        if path.startswith("/src/"):
            # Serve from webui/src directly (do not rely on symlink in public/)
            rel = path[len("/src/"):]  # relative under src
            fs = _safe_resolve(_WEBUI_SRC_DIR, rel)
            if fs and _serve_file(self, fs):
                return

        # Local artwork cache (Option C)
        if path.startswith("/artwork/"):
            rel = path[len("/artwork/"):]  # e.g. "tmdb/movie/603/poster_<hash>.jpg"
            fs = _safe_resolve(_ARTWORK_DIR, rel)
            if fs and _serve_file(self, fs):
                return
            _json_response(self, 404, {"error": "not_found"})
            return

        # Streaming endpoint (Roku/WebUI player)
        # GET /stream/<media_file_id>  (supports HTTP Range)
        if path.startswith("/stream/"):
            media_id_str = path.split("/", 2)[2]
            try:
                media_id = int(media_id_str)
            except Exception:
                _json_response(self, 400, {"error": "bad_request", "detail": "invalid media_file_id"})
                return

            try:
                self.svc._init_db()
                with self.svc.db.tx() as conn:
                    mf = get_media_file_by_id(conn, media_file_id=media_id)
            except Exception as e:
                _json_response(self, 500, {"error": "server_error", "detail": str(e)})
                return

            if not mf:
                _json_response(self, 404, {"error": "not_found"})
                return

            file_path = str(mf.get("file_path") or "").strip()
            if not file_path or not os.path.exists(file_path):
                _json_response(self, 404, {"error": "file_missing"})
                return

            ctype = self._guess_stream_content_type(file_path)
            self._send_file_range(
                file_path=file_path,
                content_type=ctype,
                range_header=self.headers.get("Range"),
                head_only=False,
            )
            return

        # HLS endpoint (Option A universal playback)
        # GET /hls/<media_file_id>/master.m3u8
        # GET /hls/<media_file_id>/index.m3u8
        # GET /hls/<media_file_id>/seg_00001.ts
        if path.startswith("/hls/"):
            parts = path.strip("/").split("/")
            if len(parts) < 3:
                _json_response(self, 400, {"error": "bad_request", "detail": "invalid hls path"})
                return

            try:
                media_id = int(parts[1])
            except Exception:
                _json_response(self, 400, {"error": "bad_request", "detail": "invalid media_file_id"})
                return

            # Ensure generation when requesting master/index.
            name = parts[2]
            if name in ("master.m3u8", "index.m3u8"):
                try:
                    self._ensure_hls(media_id=media_id)
                except ValueError as e:
                    msg = str(e)
                    if "not found" in msg:
                        _json_response(self, 404, {"error": "not_found"})
                        return
                    if "missing" in msg:
                        _json_response(self, 404, {"error": "file_missing"})
                        return
                    _json_response(self, 400, {"error": "bad_request", "detail": msg})
                    return
                except Exception as e:
                    _json_response(self, 500, {"error": "server_error", "detail": str(e)})
                    return

            fs = _safe_resolve(_HLS_DIR, "/".join(parts[1:]))
            if not fs:
                _json_response(self, 404, {"error": "not_found"})
                return

            # Content types
            if name.endswith(".m3u8"):
                return self._serve_fs_file_stream(fs, content_type="application/vnd.apple.mpegurl")
            if name.endswith(".ts"):
                return self._serve_fs_file_stream(fs, content_type="video/MP2T")

            _json_response(self, 404, {"error": "not_found"})
            return

        # Optional: if the browser asks for an unknown path (e.g., future switch
        # to History routing), serve index.html for HTML navigations.
        accept = (self.headers.get("Accept") or "")
        if "text/html" in accept and not path.startswith("/users/") and not path.startswith("/libraries") and not path.startswith("/playlists") and path not in ("/health", "/scan"):
            index_path = (_WEBUI_PUBLIC_DIR / "index.html").resolve()
            if _serve_file(self, index_path):
                return

        try:
            if path == "/health":
                _json_response(self, 200, {"ok": True})
                return

            # GET /settings
            if path == "/settings":
                keys = ["tmdb_api_key", "opensubtitles_api_key"]
                items = self.svc.list_settings(keys=keys)
                settings = {k: "" for k in keys}
                for it in items:
                    k = it.get("key")
                    if k in settings:
                        settings[k] = it.get("value") or ""
                _json_response(self, 200, {"settings": settings})
                return

            # GET /artwork?internal_key=... or /artwork?limit=50&offset=0
            if path == "/artwork":
                internal_key = qs.get("internal_key", [None])[0]
                if internal_key:
                    rec = self.svc.get_artwork(str(internal_key))
                    _json_response(self, 200, {"item": rec if rec else None})
                else:
                    limit = _int_qs(qs, "limit", 50)
                    offset = _int_qs(qs, "offset", 0)
                    res = self.svc.list_artwork(limit=limit, offset=offset)
                    _json_response(self, 200, res.__dict__)
                return

            # --- TMDB provider (explicit, admin-driven)
            # GET /providers/tmdb/search?type=movie|tv&q=...
            if path == "/providers/tmdb/search":
                tmdb_type = str(qs.get("type", [""])[0] or "").strip().lower()
                q = str(qs.get("q", [""])[0] or "").strip()

                if tmdb_type not in ("movie", "tv"):
                    raise ValueError("type must be movie or tv")
                if not q:
                    raise ValueError("q is required")

                api_path = "/search/movie" if tmdb_type == "movie" else "/search/tv"
                tmdb_key = (self.svc.get_setting("tmdb_api_key") or "").strip()
                data = _tmdb_get_json(api_path, {"query": q, "include_adult": "false"}, api_key=tmdb_key)

                items: List[Dict[str, Any]] = []
                for r in data.get("results", []) or []:
                    items.append(
                        {
                            "id": r.get("id"),
                            "type": tmdb_type,
                            "title": (r.get("title") if tmdb_type == "movie" else r.get("name")) or "",
                            "original_title": (r.get("original_title") if tmdb_type == "movie" else r.get("original_name")) or "",
                            "year": (
                                str(r.get("release_date") or "")[:4]
                                if tmdb_type == "movie"
                                else str(r.get("first_air_date") or "")[:4]
                            ),
                            "overview": r.get("overview") or "",
                            "poster_path": r.get("poster_path"),
                            "backdrop_path": r.get("backdrop_path"),
                        }
                    )

                _json_response(self, 200, {"items": items})
                return

            # GET /providers/tmdb/images?type=movie|tv&id=<tmdb_id>
            if path == "/providers/tmdb/images":
                tmdb_type = str(qs.get("type", [""])[0] or "").strip().lower()
                tmdb_id = str(qs.get("id", [""])[0] or "").strip()

                if tmdb_type not in ("movie", "tv"):
                    raise ValueError("type must be movie or tv")
                if not tmdb_id:
                    raise ValueError("id is required")

                api_path = f"/movie/{tmdb_id}/images" if tmdb_type == "movie" else f"/tv/{tmdb_id}/images"
                tmdb_key = (self.svc.get_setting("tmdb_api_key") or "").strip()
                data = _tmdb_get_json(api_path, {"include_image_language": "en,null"}, api_key=tmdb_key)

                posters: List[Dict[str, Any]] = []
                for p in data.get("posters", []) or []:
                    posters.append(
                        {
                            "file_path": p.get("file_path"),
                            "width": p.get("width"),
                            "height": p.get("height"),
                            "aspect_ratio": p.get("aspect_ratio"),
                            "vote_average": p.get("vote_average"),
                            "vote_count": p.get("vote_count"),
                        }
                    )

                backdrops: List[Dict[str, Any]] = []
                for b in data.get("backdrops", []) or []:
                    backdrops.append(
                        {
                            "file_path": b.get("file_path"),
                            "width": b.get("width"),
                            "height": b.get("height"),
                            "aspect_ratio": b.get("aspect_ratio"),
                            "vote_average": b.get("vote_average"),
                            "vote_count": b.get("vote_count"),
                        }
                    )

                _json_response(self, 200, {"type": tmdb_type, "id": tmdb_id, "posters": posters, "backdrops": backdrops})
                return

            # GET /libraries?limit=50&offset=0
            if path == "/libraries":
                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.libraries_with_counts(limit=limit, offset=offset)
                _json_response(self, 200, res.__dict__)
                return

            # GET /libraries/<id>/roots?limit=50&offset=0
            if path.startswith("/libraries/") and path.endswith("/roots"):
                parts = path.strip("/").split("/")
                library_id = int(parts[1])
                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.library_roots(library_id=library_id, limit=limit, offset=offset)
                _json_response(self, 200, res.__dict__)
                return


            # GET /libraries/<id>/recently-added?limit=50&offset=0
            if path.startswith("/libraries/") and path.endswith("/recently-added"):
                parts = path.strip("/").split("/")
                library_id = int(parts[1])
                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.recently_added(library_id, limit, offset)
                _json_response(self, 200, res.__dict__)
                return

            # GET /libraries/<id>/media-files?limit=100&offset=0&order=title_asc&q=&group_key=
            if path.startswith("/libraries/") and path.endswith("/media-files"):
                parts = path.strip("/").split("/")
                library_id = int(parts[1])

                limit = _int_qs(qs, "limit", 100)
                offset = _int_qs(qs, "offset", 0)
                order = str(qs.get("order", ["title_asc"])[0] or "title_asc")
                q = qs.get("q", [None])[0]
                group_key = qs.get("group_key", [None])[0]

                res = self.svc.library_media_files(
                    library_id=library_id,
                    limit=limit,
                    offset=offset,
                    order=order,
                    q=q,
                    group_key=group_key,
                )
                _json_response(self, 200, res.__dict__)
                return

            # GET /libraries/<id>/groups?prefix=tv:&limit=50&offset=0
            if path.startswith("/libraries/") and path.endswith("/groups"):
                parts = path.strip("/").split("/")
                library_id = int(parts[1])

                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                prefix = str(qs.get("prefix", [""])[0] or "").strip()
                if not prefix:
                    raise ValueError("prefix is required")

                res = self.svc.library_groups(
                    library_id=library_id,
                    prefix=prefix,
                    limit=limit,
                    offset=offset,
                )
                _json_response(self, 200, res.__dict__)
                return

            # GET /users/<id>/continue-watching
            if path.startswith("/users/") and path.endswith("/continue-watching"):
                parts = path.strip("/").split("/")
                user_id = int(parts[1])
                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.continue_watching(user_id, limit, offset)
                _json_response(self, 200, res.__dict__)
                return

            # GET /users/<id>/continue-watching-groups
            if path.startswith("/users/") and path.endswith("/continue-watching-groups"):
                parts = path.strip("/").split("/")
                user_id = int(parts[1])
                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.continue_watching_groups(user_id, limit, offset)
                _json_response(self, 200, res.__dict__)
                return

            # GET /users/<id>/playlists
            if path.startswith("/users/") and path.endswith("/playlists"):
                parts = path.strip("/").split("/")
                user_id = int(parts[1])
                limit = _int_qs(qs, "limit", 50)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.playlists(user_id, limit, offset)
                _json_response(self, 200, res.__dict__)
                return

            # GET /playlists/<id>/items
            if path.startswith("/playlists/") and path.endswith("/items"):
                parts = path.strip("/").split("/")
                playlist_id = int(parts[1])
                limit = _int_qs(qs, "limit", 100)
                offset = _int_qs(qs, "offset", 0)
                res = self.svc.playlist_items(playlist_id, limit, offset)
                _json_response(self, 200, res.__dict__)
                return

            _json_response(self, 404, {"error": "not_found"})

        except ValueError as e:
            _json_response(self, 400, {"error": "bad_request", "detail": str(e)})
        except Exception as e:
            _json_response(self, 500, {"error": "server_error", "detail": str(e)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            # POST /scan {"engine": "simple"|"plugin", "dry_run": true|false, "extensions": ".mkv,.mp4"}
            if path == "/scan":
                body = _read_json(self) or {}
                engine = str(body.get("engine", "simple") or "simple").strip()
                dry_run = bool(body.get("dry_run", False))
                extensions = body.get("extensions")

                # Optional hint from WebUI; current scan scans all roots.
                # Parse but intentionally ignore for now (no per-library scan behavior yet).
                library_id = body.get("library_id", None)
                try:
                    _ = int(library_id) if library_id is not None else None
                except Exception:
                    pass

                stats = self.svc.scan(engine=engine, dry_run=dry_run, extensions=extensions)
                _json_response(self, 200, stats)
                return

            # POST /settings {"tmdb_api_key": "...", "opensubtitles_api_key": "..."}
            if path == "/settings":
                body = _read_json(self) or {}
                allowed = {}
                if "tmdb_api_key" in body:
                    allowed["tmdb_api_key"] = body.get("tmdb_api_key")
                if "opensubtitles_api_key" in body:
                    allowed["opensubtitles_api_key"] = body.get("opensubtitles_api_key")
                if allowed:
                    self.svc.set_settings(allowed)
                _json_response(self, 200, {"ok": True})
                return

            # POST /artwork {"internal_key": "...", "provider": "...", "provider_id": "...", "poster_url": "..."}
            if path == "/artwork":
                body = _read_json(self) or {}
                internal_key = str(body.get("internal_key", "") or "").strip()
                provider = str(body.get("provider", "") or "").strip() or "manual"
                provider_id = str(body.get("provider_id", "") or "").strip() or "manual"
                poster_url = str(body.get("poster_url", "") or "").strip()
                if not internal_key:
                    raise ValueError("internal_key is required")
                if not poster_url:
                    raise ValueError("poster_url is required")
                self.svc.attach_artwork(
                    internal_key=internal_key,
                    provider=provider,
                    provider_id=provider_id,
                    poster_url=poster_url,
                    confidence="manual",
                )
                _json_response(self, 201, {"ok": True})
                return
            # POST /artwork/cache-tmdb
            # Body: {"kind": "poster"|"backdrop", "tmdb_type": "movie"|"tv", "tmdb_id": "603", "file_path": "/abc.jpg", "size": "w342"|"original"}
            # Returns: {"ok": true, "url": "/artwork/..."}
            if path == "/artwork/cache-tmdb":
                body = _read_json(self)

                kind = str(body.get("kind", "poster") or "poster").strip().lower()
                tmdb_type = str(body.get("tmdb_type", "") or "").strip().lower()
                tmdb_id = str(body.get("tmdb_id", "") or "").strip()
                file_path = str(body.get("file_path", "") or "").strip()
                size = str(body.get("size", "original") or "original").strip()

                if tmdb_type not in ("movie", "tv"):
                    raise ValueError("tmdb_type must be movie or tv")
                if kind not in ("poster", "backdrop"):
                    raise ValueError("kind must be poster or backdrop")
                if not tmdb_id:
                    raise ValueError("tmdb_id is required")
                if not file_path:
                    raise ValueError("file_path is required")

                url = _cache_tmdb_image(
                    kind=kind,
                    tmdb_type=tmdb_type,
                    tmdb_id=tmdb_id,
                    file_path=file_path,
                    size=size,
                )

                _json_response(self, 201, {"ok": True, "url": url})
                return
            # POST /users {"username": "nora"}
            if path == "/users":
                body = _read_json(self)
                username = str(body.get("username", "")).strip()
                if not username:
                    raise ValueError("username is required")
                user_id = self.svc.ensure_user(username)
                _json_response(self, 201, {"user_id": user_id, "username": username})
                return

            # POST /users/<id>/progress
            # Body: {"media_file_id": int, "position_seconds": int, "duration_seconds": int, "completed": bool}
            if path.startswith("/users/") and path.endswith("/progress"):
                parts = path.strip("/").split("/")
                user_id = int(parts[1])

                body = _read_json(self)

                # Required fields
                try:
                    media_file_id = int(body.get("media_file_id"))
                    position_seconds = int(body.get("position_seconds"))
                    duration_seconds = int(body.get("duration_seconds"))
                except (TypeError, ValueError):
                    raise ValueError("media_file_id, position_seconds, and duration_seconds are required integers")

                # Optional: trust client if provided
                completed = body.get("completed", None)
                if completed is not None and not isinstance(completed, bool):
                    raise ValueError("completed must be a boolean when provided")

                self.svc.set_playback_progress(
                    user_id=user_id,
                    media_file_id=media_file_id,
                    position_seconds=position_seconds,
                    duration_seconds=duration_seconds,
                    completed=completed,
                )

                _json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "user_id": user_id,
                        "media_file_id": media_file_id,
                        "position_seconds": position_seconds,
                        "duration_seconds": duration_seconds,
                        "completed": completed,
                    },
                )
                return

            # POST /libraries/<id>/roots {"root_path": "/path", "recursive": true}
            if path.startswith("/libraries/") and path.endswith("/roots"):
                parts = path.strip("/").split("/")
                library_id = int(parts[1])
                body = _read_json(self)
                root_path = str(body.get("root_path", "")).strip()
                if not root_path:
                    raise ValueError("root_path is required")
                recursive = bool(body.get("recursive", True))
                root_id = self.svc.library_root_add(library_id, root_path, recursive=recursive)
                _json_response(
                    self,
                    201,
                    {"root_id": root_id, "library_id": library_id, "root_path": root_path, "recursive": recursive},
                )
                return

            # POST /users/<id>/playlists {"name": "My Playlist"}
            if path.startswith("/users/") and path.endswith("/playlists"):
                parts = path.strip("/").split("/")
                user_id = int(parts[1])
                body = _read_json(self)
                name = str(body.get("name", "")).strip()
                if not name:
                    raise ValueError("name is required")
                playlist_id = self.svc.playlist_create(user_id, name)
                _json_response(self, 201, {"playlist_id": playlist_id})
                return

            # POST /playlists/<id>/items {"media_file_id": 123}
            if path.startswith("/playlists/") and path.endswith("/items"):
                parts = path.strip("/").split("/")
                playlist_id = int(parts[1])
                body = _read_json(self)
                media_file_id = int(body.get("media_file_id"))
                playlist_item_id = self.svc.playlist_add_item(playlist_id, media_file_id)
                _json_response(self, 201, {"playlist_item_id": playlist_item_id})
                return

            # POST /playlists/<pid>/items/<item_id>/move {"new_position": 1}
            if path.startswith("/playlists/") and "/items/" in path and path.endswith("/move"):
                parts = path.strip("/").split("/")
                playlist_id = int(parts[1])
                playlist_item_id = int(parts[3])
                body = _read_json(self)
                new_position = int(body.get("new_position"))
                self.svc.playlist_move_item(playlist_id, playlist_item_id, new_position)
                _json_response(self, 200, {"ok": True})
                return

            _json_response(self, 404, {"error": "not_found"})

        except ValueError as e:
            _json_response(self, 400, {"error": "bad_request", "detail": str(e)})
        except Exception as e:
            _json_response(self, 500, {"error": "server_error", "detail": str(e)})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            # PATCH /playlists/<id> {"name": "New Name"}
            if path.startswith("/playlists/") and "/items/" not in path:
                parts = path.strip("/").split("/")
                playlist_id = int(parts[1])
                body = _read_json(self)
                name = str(body.get("name", "")).strip()
                if not name:
                    raise ValueError("name is required")
                self.svc.playlist_rename(playlist_id, name)
                _json_response(self, 200, {"ok": True})
                return

            _json_response(self, 404, {"error": "not_found"})

        except ValueError as e:
            _json_response(self, 400, {"error": "bad_request", "detail": str(e)})
        except Exception as e:
            _json_response(self, 500, {"error": "server_error", "detail": str(e)})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            # DELETE /library-roots/<root_id>
            if path.startswith("/library-roots/"):
                parts = path.strip("/").split("/")
                root_id = int(parts[1])
                self.svc.library_root_remove(root_id)
                _json_response(self, 200, {"ok": True})
                return

            # DELETE /playlists/<id>
            if path.startswith("/playlists/") and "/items/" not in path:
                parts = path.strip("/").split("/")
                playlist_id = int(parts[1])
                self.svc.playlist_delete(playlist_id)
                _json_response(self, 200, {"ok": True})
                return

            # DELETE /playlists/<pid>/items/<item_id>
            if path.startswith("/playlists/") and "/items/" in path:
                parts = path.strip("/").split("/")
                playlist_id = int(parts[1])
                playlist_item_id = int(parts[3])
                self.svc.playlist_remove_item(playlist_id, playlist_item_id)
                _json_response(self, 200, {"ok": True})
                return

            # DELETE /artwork?internal_key=...
            if path == "/artwork":
                qs = parse_qs(parsed.query or "")
                internal_key = qs.get("internal_key", [None])[0]
                if not internal_key:
                    raise ValueError("internal_key is required")
                self.svc.detach_artwork(str(internal_key))
                _json_response(self, 200, {"ok": True})
                return

            _json_response(self, 404, {"error": "not_found"})

        except ValueError as e:
            _json_response(self, 400, {"error": "bad_request", "detail": str(e)})
        except Exception as e:
            _json_response(self, 500, {"error": "server_error", "detail": str(e)})


def run_server(db_path: str, host: str, port: int) -> None:
    ApiHandler.svc = MediaServerService(db_path)
    server = HTTPServer((host, port), ApiHandler)
    print(f"Serving HTTP on http://{host}:{port} using db={db_path}")
    server.serve_forever()


# -----------------
# CLI
# -----------------


def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="media-server")
    parser.add_argument("--db", default="data/media.db", help="Path to SQLite database")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Run HTTP JSON API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    p_user = sub.add_parser("user", help="Create/ensure a user")
    p_user.add_argument("username")

    p_user_pw = sub.add_parser("user-set-password", help="Set a user's password")
    p_user_pw.add_argument("user_id", type=int)
    p_user_pw.add_argument("new_password")

    p_recent = sub.add_parser("recently-added", help="Recently added (per library)")
    p_recent.add_argument("library_id", type=int)
    p_recent.add_argument("--limit", type=int, default=50)
    p_recent.add_argument("--offset", type=int, default=0)

    p_cw = sub.add_parser("continue-watching", help="Continue watching (file-level)")
    p_cw.add_argument("user_id", type=int)
    p_cw.add_argument("--limit", type=int, default=50)
    p_cw.add_argument("--offset", type=int, default=0)

    p_cwg = sub.add_parser("continue-watching-groups", help="Continue watching (group-level)")
    p_cwg.add_argument("user_id", type=int)
    p_cwg.add_argument("--limit", type=int, default=50)
    p_cwg.add_argument("--offset", type=int, default=0)

    p_pl_list = sub.add_parser("playlists", help="List playlists for a user")
    p_pl_list.add_argument("user_id", type=int)
    p_pl_list.add_argument("--limit", type=int, default=50)
    p_pl_list.add_argument("--offset", type=int, default=0)

    p_pl_create = sub.add_parser("playlist-create", help="Create a playlist")
    p_pl_create.add_argument("user_id", type=int)
    p_pl_create.add_argument("name")

    p_pl_items = sub.add_parser("playlist-items", help="List items in a playlist")
    p_pl_items.add_argument("playlist_id", type=int)
    p_pl_items.add_argument("--limit", type=int, default=100)
    p_pl_items.add_argument("--offset", type=int, default=0)

    p_pl_add = sub.add_parser("playlist-add", help="Add a media_file_id to a playlist")
    p_pl_add.add_argument("playlist_id", type=int)
    p_pl_add.add_argument("media_file_id", type=int)

    p_pl_rm = sub.add_parser("playlist-remove", help="Remove a playlist item (does NOT delete media files)")
    p_pl_rm.add_argument("playlist_id", type=int)
    p_pl_rm.add_argument("playlist_item_id", type=int)

    p_pl_move = sub.add_parser("playlist-move", help="Move a playlist item to a new position")
    p_pl_move.add_argument("playlist_id", type=int)
    p_pl_move.add_argument("playlist_item_id", type=int)
    p_pl_move.add_argument("new_position", type=int)

    p_libs = sub.add_parser("libraries", help="List libraries")
    p_libs.add_argument("--limit", type=int, default=50)
    p_libs.add_argument("--offset", type=int, default=0)

    p_lib_create = sub.add_parser("library-create", help="Create a library")
    p_lib_create.add_argument("name")

    p_lib_rename = sub.add_parser("library-rename", help="Rename a library")
    p_lib_rename.add_argument("library_id", type=int)
    p_lib_rename.add_argument("name")

    p_root_add = sub.add_parser("library-root-add", help="Mount a directory to a library")
    p_root_add.add_argument("library_id", type=int)
    p_root_add.add_argument("root_path")
    p_root_add.add_argument("--no-recursive", action="store_true", help="Do not include subdirectories")

    p_roots = sub.add_parser("library-roots", help="List mounted directories for a library")
    p_roots.add_argument("library_id", type=int)
    p_roots.add_argument("--limit", type=int, default=50)
    p_roots.add_argument("--offset", type=int, default=0)

    p_root_rm = sub.add_parser("library-root-remove", help="Remove a mounted directory")
    p_root_rm.add_argument("root_id", type=int)

    args = parser.parse_args(argv)

    svc = MediaServerService(args.db)

    if args.cmd == "serve":
        run_server(args.db, args.host, args.port)
        return 0

    if args.cmd == "user":
        user_id = svc.ensure_user(args.username)
        print(json.dumps({"user_id": user_id, "username": args.username}))
        return 0

    if args.cmd == "user-set-password":
        svc.set_password(args.user_id, args.new_password)
        print(json.dumps({"ok": True}))
        return 0

    if args.cmd == "libraries":
        res = svc.libraries(limit=args.limit, offset=args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "library-create":
        library_id = svc.library_create(args.name)
        print(json.dumps({"library_id": library_id, "name": args.name}, ensure_ascii=False))
        return 0

    if args.cmd == "library-rename":
        svc.library_rename(args.library_id, args.name)
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0

    if args.cmd == "library-root-add":
        root_id = svc.library_root_add(
            args.library_id,
            args.root_path,
            recursive=(not args.no_recursive),
        )
        print(
            json.dumps(
                {
                    "root_id": root_id,
                    "library_id": args.library_id,
                    "root_path": args.root_path,
                    "recursive": (not args.no_recursive),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "library-roots":
        res = svc.library_roots(library_id=args.library_id, limit=args.limit, offset=args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "library-root-remove":
        svc.library_root_remove(args.root_id)
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0

    if args.cmd == "recently-added":
        res = svc.recently_added(args.library_id, args.limit, args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "continue-watching":
        res = svc.continue_watching(args.user_id, args.limit, args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "continue-watching-groups":
        res = svc.continue_watching_groups(args.user_id, args.limit, args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "playlists":
        res = svc.playlists(args.user_id, args.limit, args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "playlist-create":
        playlist_id = svc.playlist_create(args.user_id, args.name)
        print(json.dumps({"playlist_id": playlist_id}))
        return 0

    if args.cmd == "playlist-items":
        res = svc.playlist_items(args.playlist_id, args.limit, args.offset)
        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0

    if args.cmd == "playlist-add":
        playlist_item_id = svc.playlist_add_item(args.playlist_id, args.media_file_id)
        print(json.dumps({"playlist_item_id": playlist_item_id}))
        return 0

    if args.cmd == "playlist-remove":
        svc.playlist_remove_item(args.playlist_id, args.playlist_item_id)
        print(json.dumps({"ok": True}))
        return 0

    if args.cmd == "playlist-move":
        svc.playlist_move_item(args.playlist_id, args.playlist_item_id, args.new_position)
        print(json.dumps({"ok": True}))
        return 0

    return 1


def main() -> None:
    raise SystemExit(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
