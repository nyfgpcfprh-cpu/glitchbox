from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

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
    get_user_id,
    move_playlist_item,
    remove_item_from_playlist,
    rename_playlist,
)


@dataclass(frozen=True)
class ServiceResult:
    """Standard response shape for both CLI and HTTP endpoints."""

    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class MediaServerService:
    """Phase 1B service layer (transport-agnostic)."""

    def __init__(self, db_path: str) -> None:
        self.db = Database(db_path)

    def _init_db(self) -> None:
        # Safe to call repeatedly.
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
# HTTP JSON API (minimal)
# -----------------


def _int_qs(qs: Dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(qs.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        return default


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
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
    svc: MediaServerService

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write((fmt % args) + "\n")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/health":
                _json_response(self, 200, {"ok": True})
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
            # POST /users {"username": "nora"}
            if path == "/users":
                body = _read_json(self)
                username = str(body.get("username", "")).strip()
                if not username:
                    raise ValueError("username is required")
                user_id = self.svc.ensure_user(username)
                _json_response(self, 201, {"user_id": user_id, "username": username})
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

    args = parser.parse_args(argv)

    svc = MediaServerService(args.db)

    if args.cmd == "serve":
        run_server(args.db, args.host, args.port)
        return 0

    if args.cmd == "user":
        user_id = svc.ensure_user(args.username)
        print(json.dumps({"user_id": user_id, "username": args.username}))
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
"""GlitchBox python package.

This file is intentionally minimal.
Application entrypoints live in `python/main.py`.
"""