"""
media-server Phase 1B - SQLite schema + DB helpers only.

Drop this file into your repo (for example: media_server/db.py).
It is intentionally small and safe:
- Idempotent migrations (safe to call on every startup)
- Basic helpers for queries + pagination that always returns total_count
"""

from __future__ import annotations

import sqlite3
import base64
import hashlib
import hmac
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


def utc_now_iso() -> str:
    """UTC timestamp in ISO-8601 (SQLite TEXT-friendly)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# -----------------------------
# Internal helpers for migrations and password hashing
# -----------------------------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r[1] == column for r in rows)


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    """Return a portable PBKDF2 hash string.

    Format: pbkdf2_sha256$<iterations>$<salt_b64>$<dk_b64>
    """
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")

    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    dk_b64 = base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt_b64}${dk_b64}"


def verify_password(password: str, stored: str) -> bool:
    """Verify password against hash string produced by hash_password()."""
    try:
        algo, iters_s, salt_b64, dk_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)

        def _pad(s: str) -> str:
            return s + "=" * ((4 - (len(s) % 4)) % 4)

        salt = base64.urlsafe_b64decode(_pad(salt_b64).encode("ascii"))
        expected = base64.urlsafe_b64decode(_pad(dk_b64).encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _ensure_core_media_tables(conn: sqlite3.Connection) -> None:
    """Create minimal core tables on a fresh DB.

    Phase 1B assumes `media_files` exists. If the scanner hasn't created it yet,
    we create a minimal version so migrations + users/playlists/progress work.
    """
    if not _table_exists(conn, "media_files"):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER,
                file_path TEXT NOT NULL UNIQUE,
                group_key TEXT,
                title TEXT,
                duration_seconds INTEGER,
                first_seen_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_media_files_library_id ON media_files(library_id);
            CREATE INDEX IF NOT EXISTS idx_media_files_group_key ON media_files(group_key);
            CREATE INDEX IF NOT EXISTS idx_media_files_first_seen ON media_files(first_seen_at);
            """
        )
        conn.execute(
            "UPDATE media_files SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP);"
        )

    # Ensure users table exists with admin/password fields on fresh DBs.
    if not _table_exists(conn, "users"):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """
        )


@dataclass(frozen=True)
class Page:
    limit: int = 50
    offset: int = 0


class Database:
    """
    Thin wrapper around sqlite3.

    Goals:
      - Keep SQL visible (no ORM).
      - Enforce foreign keys.
      - Provide helpers that always return total counts for pagination.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enforce FK constraints (off by default in SQLite)
        conn.execute("PRAGMA foreign_keys = ON;")
        # Reasonable defaults
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    @contextmanager
    def tx(self) -> Iterable[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# -----------------------------
# Migrations
# -----------------------------

MIGRATIONS: List[Tuple[str, str]] = [
    (
        "001_create_users_playback_playlists",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

        CREATE TABLE IF NOT EXISTS playback_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            media_file_id INTEGER NOT NULL,
            position_seconds INTEGER NOT NULL DEFAULT 0,
            duration_seconds INTEGER,
            completed INTEGER NOT NULL DEFAULT 0, -- 0/1 boolean
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, media_file_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            -- media_file_id FK added in 002, after we validate media_files exists
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
    ),
    (
        "002_add_first_seen_at_and_fk_media_files",
        """
        -- Add first_seen_at to existing media_files table.
        -- (media_files is ensured by apply_migrations() on fresh DBs.)

        -- Backfill existing rows so Recently Added works immediately.
        UPDATE media_files
           SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP);

        -- Add FK constraint for playback_progress.media_file_id by recreating the table.
        -- SQLite cannot add a FK constraint to an existing table directly.
        CREATE TABLE IF NOT EXISTS playback_progress_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            media_file_id INTEGER NOT NULL,
            position_seconds INTEGER NOT NULL DEFAULT 0,
            duration_seconds INTEGER,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, media_file_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
        );

        INSERT INTO playback_progress_new (
            id, user_id, media_file_id, position_seconds, duration_seconds, completed, created_at, updated_at
        )
        SELECT
            id, user_id, media_file_id, position_seconds, duration_seconds, completed, created_at, updated_at
        FROM playback_progress;

        DROP TABLE playback_progress;
        ALTER TABLE playback_progress_new RENAME TO playback_progress;
        """,
    ),
    (
        "003_create_playlist_items",
        """
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            media_file_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(playlist_id, position),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
            -- IMPORTANT: Deleting a playlist item NEVER deletes a media file; this cascade only removes playlist_items when a media_file is deleted.
            FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist_pos
            ON playlist_items(playlist_id, position);

        CREATE INDEX IF NOT EXISTS idx_playback_progress_user_updated
            ON playback_progress(user_id, completed, updated_at);

        CREATE INDEX IF NOT EXISTS idx_media_files_first_seen
            ON media_files(first_seen_at);
        """,
    ),
    (
        "004_create_library_roots",
        """
        CREATE TABLE IF NOT EXISTS library_roots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_id INTEGER NOT NULL,
            root_path TEXT NOT NULL,
            recursive INTEGER NOT NULL DEFAULT 1, -- 0/1 boolean
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(library_id, root_path),
            FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_library_roots_library_id
            ON library_roots(library_id);

        CREATE INDEX IF NOT EXISTS idx_library_roots_root_path
            ON library_roots(root_path);
        """,
    ),
    (
        "005_create_external_artwork",
        """
        -- Explicit mapping: internal_key -> provider metadata.
        -- internal_key is an app-defined stable identifier (e.g., "mf:4140" or "gk:tv:show:s01").
        -- This is intentionally NOT a foreign key: we do not want implicit deletes or magic coupling.

        CREATE TABLE IF NOT EXISTS external_artwork (
            internal_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            poster_url TEXT,
            backdrop_url TEXT,
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_external_artwork_provider
            ON external_artwork(provider, provider_id);

        CREATE INDEX IF NOT EXISTS idx_external_artwork_updated
            ON external_artwork(updated_at);
        """,
    ),
]


def _migration_applied(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations';"
    ).fetchone()
    if not row:
        return False
    r = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?;",
        (name,),
    ).fetchone()
    return r is not None


def apply_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply migrations in order, once.

    Safe to call on every startup.
    """
    # Fresh DB safety: ensure core tables exist even if scanner hasn't run yet.
    _ensure_core_media_tables(conn)

    # Older DB safety: add first_seen_at only if missing.
    if _table_exists(conn, "media_files") and not _column_exists(conn, "media_files", "first_seen_at"):
        conn.execute("ALTER TABLE media_files ADD COLUMN first_seen_at TEXT;")
        conn.execute(
            "UPDATE media_files SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP);"
        )

    # Older DB safety: ensure users admin/password columns exist.
    if _table_exists(conn, "users"):
        if not _column_exists(conn, "users", "password_hash"):
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT;")
        if not _column_exists(conn, "users", "is_admin"):
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;")

    for name, sql in MIGRATIONS:
        if _migration_applied(conn, name):
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations(name, applied_at) VALUES(?, ?);",
            (name, utc_now_iso()),
        )

    # Seed default admin user (admin/admin) if it doesn't exist yet.
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?;",
        ("admin",),
    ).fetchone()

    if row is None:
        admin_id = create_user(conn, "admin")
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?;", (admin_id,))
        set_user_password(conn, user_id=admin_id, new_password="admin")
    else:
        conn.execute("UPDATE users SET is_admin = 1 WHERE username = ?;", ("admin",))


# -----------------------------
# Minimal helper queries
# -----------------------------

def create_user(conn: sqlite3.Connection, username: str) -> int:
    now = utc_now_iso()
    cur = conn.execute(
        "INSERT INTO users(username, created_at, updated_at) VALUES(?, ?, ?);",
        (username, now, now),
    )
    return int(cur.lastrowid)



def get_user_id(conn: sqlite3.Connection, username: str) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?;",
        (username,),
    ).fetchone()
    return int(row["id"]) if row else None


def set_user_password(conn: sqlite3.Connection, *, user_id: int, new_password: str) -> None:
    """Set/replace a user's password hash."""
    now = utc_now_iso()
    ph = hash_password(new_password)
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?;",
        (ph, now, user_id),
    )




# -----------------------------
# Libraries + Library Roots (directory mounts)
# -----------------------------


def create_library(conn: sqlite3.Connection, *, name: str) -> int:
    """Create a user-named library (e.g., Movies, TV, Flix)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("library name is required")

    now = utc_now_iso()
    cur = conn.execute(
        "INSERT INTO libraries (name, created_at, updated_at) VALUES (?, ?, ?);",
        (name, now, now),
    )
    return int(cur.lastrowid)


def rename_library(conn: sqlite3.Connection, *, library_id: int, name: str) -> None:
    """Rename a library."""
    name = (name or "").strip()
    if not name:
        raise ValueError("library name is required")

    now = utc_now_iso()
    cur = conn.execute(
        "UPDATE libraries SET name = ?, updated_at = ? WHERE id = ?;",
        (name, now, library_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"library_id not found: {library_id}")


def list_libraries(conn: sqlite3.Connection, *, page: Page) -> Tuple[List[Dict[str, Any]], int]:
    """List libraries with pagination + total count."""
    total = int(conn.execute("SELECT COUNT(1) FROM libraries;").fetchone()[0])

    rows = conn.execute(
        """
        SELECT id, name, created_at, updated_at
        FROM libraries
        ORDER BY name COLLATE NOCASE ASC, id ASC
        LIMIT ? OFFSET ?;
        """,
        (page.limit, page.offset),
    ).fetchall()

    items = [
        {
            "id": int(r[0]),
            "name": str(r[1]),
            "created_at": str(r[2]),
            "updated_at": str(r[3]),
        }
        for r in rows
    ]
    return items, total


def add_library_root(
    conn: sqlite3.Connection,
    *,
    library_id: int,
    root_path: str,
    recursive: bool = True,
) -> int:
    """Mount a filesystem directory to a library.

    `root_path` should be an absolute or normalized path (normalization is handled in service/CLI).
    `recursive=True` means include subdirectories.
    """
    rp = (root_path or "").strip()
    if not rp:
        raise ValueError("root_path is required")

    now = utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO library_roots (library_id, root_path, recursive, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?);
        """,
        (library_id, rp, 1 if recursive else 0, now, now),
    )
    return int(cur.lastrowid)


def list_library_roots(
    conn: sqlite3.Connection,
    *,
    library_id: int,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """List mounted directories for a library with pagination + total count."""
    total = int(
        conn.execute(
            "SELECT COUNT(1) FROM library_roots WHERE library_id = ?;",
            (library_id,),
        ).fetchone()[0]
    )

    rows = conn.execute(
        """
        SELECT id, library_id, root_path, recursive, created_at, updated_at
        FROM library_roots
        WHERE library_id = ?
        ORDER BY root_path COLLATE NOCASE ASC, id ASC
        LIMIT ? OFFSET ?;
        """,
        (library_id, page.limit, page.offset),
    ).fetchall()

    items = [
        {
            "id": int(r[0]),
            "library_id": int(r[1]),
            "root_path": str(r[2]),
            "recursive": bool(int(r[3])),
            "created_at": str(r[4]),
            "updated_at": str(r[5]),
        }
        for r in rows
    ]
    return items, total


def remove_library_root(conn: sqlite3.Connection, *, root_id: int) -> None:
    """Remove a mounted directory from a library.

    IMPORTANT: This does not delete media files on disk and does not delete `media_files` rows.
    It only removes the mount mapping.
    """
    conn.execute("DELETE FROM library_roots WHERE id = ?;", (root_id,))


def upsert_playback_progress(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    media_file_id: int,
    position_seconds: int,
    duration_seconds: Optional[int],
    completed: Optional[bool] = None,
) -> None:
    """
    Insert or update playback progress for a specific user + media file.
    Completion rule here is minimal: completed if position >= duration (when duration known).
    """
    now = utc_now_iso()

    # If client explicitly provides completion state, trust it.
    # Otherwise, compute completion when duration is known.
    if completed is None:
        completed_i = 0
        if duration_seconds is not None and duration_seconds > 0 and position_seconds >= duration_seconds:
            completed_i = 1
    else:
        completed_i = 1 if completed else 0

    conn.execute(
        """
        INSERT INTO playback_progress (
            user_id, media_file_id, position_seconds, duration_seconds, completed, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, media_file_id) DO UPDATE SET
            position_seconds=excluded.position_seconds,
            duration_seconds=excluded.duration_seconds,
            completed=excluded.completed,
            updated_at=excluded.updated_at;
        """,
        (user_id, media_file_id, position_seconds, duration_seconds, completed_i, now, now),
    )


def paged_query(
    conn: sqlite3.Connection,
    *,
    items_sql: str,
    items_params: Tuple[Any, ...],
    count_sql: str,
    count_params: Tuple[Any, ...],
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Executes a paginated query and a total-count query.

    Returns: (items_as_dicts, total_count)
    """
    total_row = conn.execute(count_sql, count_params).fetchone()
    total = int(total_row[0]) if total_row else 0

    rows = conn.execute(
        items_sql + " LIMIT ? OFFSET ?;",
        items_params + (page.limit, page.offset),
    ).fetchall()

    return [dict(r) for r in rows], total


# -----------------------------
# Media file helpers
# -----------------------------

def get_media_file_by_id(conn: sqlite3.Connection, *, media_file_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single media_files row by id.

    Returns a dict (sqlite3.Row -> dict) or None if not found.
    """
    row = conn.execute(
        """
        SELECT mf.*
        FROM media_files mf
        WHERE mf.id = ?
        """,
        (int(media_file_id),),
    ).fetchone()

    return dict(row) if row else None


# -----------------------------
# Phase 1B Query helpers (read-only)
# -----------------------------

def get_recently_added(
    conn: sqlite3.Connection,
    *,
    library_id: int,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Recently Added (per library), based on *database* first_seen_at.

    Why this exists:
      - Filesystem mtimes are unreliable (copies, migrations, touches).
      - first_seen_at is set the first time the scanner notices the file.

    Pagination contract:
      - Always returns (items, total_count)
      - total_count is the count *without* LIMIT/OFFSET.

    Notes:
      - We deliberately `SELECT mf.*` so we don't couple this layer to a
        specific media_files column list during early phases.
      - Ordering is deterministic: first_seen_at DESC, then id DESC.
    """

    items_sql = (
        "SELECT mf.* "
        "FROM media_files mf "
        "WHERE mf.library_id = ? "
        "ORDER BY COALESCE(mf.first_seen_at, '') DESC, mf.id DESC"
    )

    count_sql = "SELECT COUNT(1) FROM media_files mf WHERE mf.library_id = ?"

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(library_id,),
        count_sql=count_sql,
        count_params=(library_id,),
        page=page,
    )


# -----------------------------
# Full library browse (paged, optional search, sorting)
# -----------------------------

def list_library_media_files(
    conn: sqlite3.Connection,
    *,
    library_id: int,
    page: Page,
    order: str = "title_asc",
    q: Optional[str] = None,
    group_key: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Full library listing (paged), optionally filtered by a search term and/or group_key.

    This is intentionally different from `get_recently_added`:
      - `get_recently_added` is a curated/time-based view.
      - `list_library_media_files` is the complete library browse view.

    No folder heuristics. No schema changes.
    Title may be NULL; callers can derive a fallback from file_path.

    order:
      - title_asc (default)
      - title_desc
      - added_desc (created_at DESC)
      - added_asc (created_at ASC)

    q:
      - optional substring match against title OR file_path
    group_key:
      - optional filter for a specific group_key value
    """

    order_by = "ORDER BY COALESCE(mf.title, mf.file_path) COLLATE NOCASE ASC, mf.id ASC"
    if order == "title_desc":
        order_by = "ORDER BY COALESCE(mf.title, mf.file_path) COLLATE NOCASE DESC, mf.id DESC"
    elif order == "added_desc":
        order_by = "ORDER BY mf.created_at DESC, mf.id DESC"
    elif order == "added_asc":
        order_by = "ORDER BY mf.created_at ASC, mf.id ASC"

    q_norm = (q or "").strip()
    gk_norm = (group_key or "").strip()

    # Build WHERE clause incrementally to support optional filters.
    where = "WHERE mf.library_id = ?"
    items_params_list: List[Any] = [library_id]
    count_params_list: List[Any] = [library_id]

    if gk_norm:
        where += " AND mf.group_key = ?"
        items_params_list.append(gk_norm)
        count_params_list.append(gk_norm)

    if q_norm:
        where += " AND (mf.title LIKE ? OR mf.file_path LIKE ?)"
        like = f"%{q_norm}%"
        items_params_list.extend([like, like])
        count_params_list.extend([like, like])

    items_sql = (
        "SELECT mf.* "
        "FROM media_files mf "
        f"{where} "
        f"{order_by}"
    )

    count_sql = f"SELECT COUNT(1) FROM media_files mf {where}"

    items_params = tuple(items_params_list)
    count_params = tuple(count_params_list)

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=items_params,
        count_sql=count_sql,
        count_params=count_params,
        page=page,
    )


# -----------------------------
# Grouping helpers for group_key (for TV/season hierarchy)
# -----------------------------

def list_library_groups(
    conn: sqlite3.Connection,
    *,
    library_id: int,
    prefix: str,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """List distinct group_keys (paged) for a library, with counts.

    This is the minimal primitive needed for TV hierarchy without schema changes.

    Examples:
      - prefix='tv:' -> list all TV show/season groups we have
      - prefix='tv:3rd-rock-from-the-sun:' -> list seasons for that show

    Returns rows shaped like:
      { 'group_key': 'tv:show:s01', 'media_count': 10 }

    Notes:
      - Only returns non-NULL group_key rows.
      - Uses LIKE prefix% matching.
    """

    px = (prefix or "").strip()
    like = f"{px}%"

    items_sql = (
        "SELECT mf.group_key AS group_key, COUNT(1) AS media_count "
        "FROM media_files mf "
        "WHERE mf.library_id = ? "
        "  AND mf.group_key IS NOT NULL "
        "  AND mf.group_key LIKE ? "
        "GROUP BY mf.group_key "
        "ORDER BY mf.group_key COLLATE NOCASE ASC"
    )

    count_sql = (
        "SELECT COUNT(DISTINCT mf.group_key) "
        "FROM media_files mf "
        "WHERE mf.library_id = ? "
        "  AND mf.group_key IS NOT NULL "
        "  AND mf.group_key LIKE ?"
    )

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(library_id, like),
        count_sql=count_sql,
        count_params=(library_id, like),
        page=page,
    )


def get_continue_watching(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Continue Watching — file-level (per user).

    Definition:
      - One row per (user, media_file)
      - Excludes completed items
      - Ordered by most recently updated playback activity

    Why this shape:
      - Streaming/UI layers can render directly from file rows
      - No title-based grouping or deduplication (file identity only)

    Pagination contract:
      - Always returns (items, total_count)
      - total_count ignores LIMIT/OFFSET

    Notes:
      - We join playback_progress -> media_files to expose file metadata
      - We keep SELECT explicit to avoid accidental column ambiguity
    """

    items_sql = (
        "SELECT "
        "  mf.*, "
        "  pp.position_seconds, "
        "  pp.duration_seconds, "
        "  pp.completed, "
        "  pp.updated_at AS progress_updated_at "
        "FROM playback_progress pp "
        "JOIN media_files mf ON mf.id = pp.media_file_id "
        "WHERE pp.user_id = ? "
        "  AND pp.completed = 0 "
        "ORDER BY pp.updated_at DESC, pp.id DESC"
    )

    count_sql = (
        "SELECT COUNT(1) "
        "FROM playback_progress pp "
        "WHERE pp.user_id = ? "
        "  AND pp.completed = 0"
    )

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(user_id,),
        count_sql=count_sql,
        count_params=(user_id,),
        page=page,
    )


def get_continue_watching_groups(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Continue Watching — group/card-level (per user, via group_key).

    Definition:
      - One row per logical group (group_key)
      - A group represents multiple media files (e.g. versions, episodes)
      - Excludes groups where *all* items are completed

    How grouping works:
      - media_files.group_key is the card identity
      - The "most recent" progress inside the group determines ordering

    Returned row semantics:
      - group_key
      - representative_media_file_id (most recently updated file in group)
      - position_seconds / duration_seconds from that representative file
      - last_activity_at = MAX(playback_progress.updated_at) for the group

    Pagination contract:
      - Always returns (items, total_count)
      - total_count is the number of distinct group_keys

    Notes:
      - This intentionally does NOT collapse or modify file-level progress
      - File-level data remains the source of truth
    """

    items_sql = (
        "SELECT "
        "  mf.group_key AS group_key, "
        "  pp.media_file_id AS representative_media_file_id, "
        "  pp.position_seconds, "
        "  pp.duration_seconds, "
        "  MAX(pp.updated_at) AS last_activity_at "
        "FROM playback_progress pp "
        "JOIN media_files mf ON mf.id = pp.media_file_id "
        "WHERE pp.user_id = ? "
        "  AND pp.completed = 0 "
        "  AND mf.group_key IS NOT NULL "
        "GROUP BY mf.group_key "
        "ORDER BY last_activity_at DESC"
    )

    count_sql = (
        "SELECT COUNT(DISTINCT mf.group_key) "
        "FROM playback_progress pp "
        "JOIN media_files mf ON mf.id = pp.media_file_id "
        "WHERE pp.user_id = ? "
        "  AND pp.completed = 0 "
        "  AND mf.group_key IS NOT NULL"
    )

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(user_id,),
        count_sql=count_sql,
        count_params=(user_id,),
        page=page,
    )


# -----------------------------
# Playlists (read-only helpers)
# -----------------------------

def get_playlists_for_user(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List playlists for a user (owner-only).

    Returned row semantics:
      - playlists.* (id, user_id, name, created_at, updated_at)

    Pagination contract:
      - Always returns (items, total_count)

    Ordering:
      - updated_at DESC, then id DESC for deterministic results.
    """

    items_sql = (
        "SELECT p.* "
        "FROM playlists p "
        "WHERE p.user_id = ? "
        "ORDER BY p.updated_at DESC, p.id DESC"
    )

    count_sql = "SELECT COUNT(1) FROM playlists p WHERE p.user_id = ?"

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(user_id,),
        count_sql=count_sql,
        count_params=(user_id,),
        page=page,
    )


def get_playlist_items(
    conn: sqlite3.Connection,
    *,
    playlist_id: int,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List items in a playlist, ordered.

    Returned row semantics:
      - playlist_items fields: id, playlist_id, media_file_id, position, created_at
      - plus media_files.* for the media_file_id

    Pagination contract:
      - Always returns (items, total_count)

    Ordering:
      - position ASC (playlist order)
      - then id ASC for deterministic stability if positions collide (shouldn't).
    """

    items_sql = (
        "SELECT "
        "  pi.id AS playlist_item_id, "
        "  pi.playlist_id, "
        "  pi.media_file_id, "
        "  pi.position, "
        "  pi.created_at AS playlist_item_created_at, "
        "  mf.* "
        "FROM playlist_items pi "
        "JOIN media_files mf ON mf.id = pi.media_file_id "
        "WHERE pi.playlist_id = ? "
        "ORDER BY pi.position ASC, pi.id ASC"
    )

    count_sql = "SELECT COUNT(1) FROM playlist_items pi WHERE pi.playlist_id = ?"

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(playlist_id,),
        count_sql=count_sql,
        count_params=(playlist_id,),
        page=page,
    )


# -----------------------------
# Playlists (write helpers)
# -----------------------------


def create_playlist(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    name: str,
) -> int:
    """Create a new playlist for a user. Returns playlist_id."""
    now = utc_now_iso()
    cur = conn.execute(
        "INSERT INTO playlists(user_id, name, created_at, updated_at) VALUES(?, ?, ?, ?);",
        (user_id, name, now, now),
    )
    return int(cur.lastrowid)


def rename_playlist(
    conn: sqlite3.Connection,
    *,
    playlist_id: int,
    name: str,
) -> None:
    """Rename an existing playlist and bump updated_at."""
    now = utc_now_iso()
    conn.execute(
        "UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?;",
        (name, now, playlist_id),
    )


def delete_playlist(
    conn: sqlite3.Connection,
    *,
    playlist_id: int,
) -> None:
    """
    Delete a playlist.

    Note: playlist_items are removed automatically via ON DELETE CASCADE.
    Media files are NOT affected; only playlist rows/items are removed.
    """
    conn.execute("DELETE FROM playlists WHERE id = ?;", (playlist_id,))


def _next_playlist_position(conn: sqlite3.Connection, playlist_id: int) -> int:
    """Return the next position (1-based) for appending to a playlist."""
    row = conn.execute(
        "SELECT COALESCE(MAX(position), 0) AS max_pos FROM playlist_items WHERE playlist_id = ?;",
        (playlist_id,),
    ).fetchone()
    max_pos = int(row["max_pos"]) if row else 0
    return max_pos + 1


def add_item_to_playlist(
    conn: sqlite3.Connection,
    *,
    playlist_id: int,
    media_file_id: int,
) -> int:
    """
    Append a media file to a playlist.

    Behavior:
      - Inserts at the end (highest position + 1)
      - Returns playlist_item_id

    Why we don't dedupe:
      - Playlists are ordered lists; duplicates are allowed (e.g. same song twice).
    """
    now = utc_now_iso()
    pos = _next_playlist_position(conn, playlist_id)
    cur = conn.execute(
        "INSERT INTO playlist_items(playlist_id, media_file_id, position, created_at) VALUES(?, ?, ?, ?);",
        (playlist_id, media_file_id, pos, now),
    )
    # Bump playlist updated_at to reflect modification.
    conn.execute(
        "UPDATE playlists SET updated_at = ? WHERE id = ?;",
        (utc_now_iso(), playlist_id),
    )
    return int(cur.lastrowid)


def _repack_playlist_positions(conn: sqlite3.Connection, playlist_id: int) -> None:
    """
    Re-number playlist item positions to be contiguous (1..N).

    This keeps ordering stable and prevents gaps after removals.

    Implementation detail:
      - Because of UNIQUE(playlist_id, position), we do a two-pass update
        to avoid transient collisions:
          1) shift existing positions by +1_000_000
          2) write desired 1..N positions
    """
    rows = conn.execute(
        "SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY position ASC, id ASC;",
        (playlist_id,),
    ).fetchall()

    ids = [int(r["id"]) for r in rows]
    if not ids:
        return

    # Pass 1: shift away from the normal range.
    conn.executemany(
        "UPDATE playlist_items SET position = position + 1000000 WHERE id = ?;",
        [(i,) for i in ids],
    )

    # Pass 2: rewrite contiguous positions.
    conn.executemany(
        "UPDATE playlist_items SET position = ? WHERE id = ?;",
        [(idx + 1, item_id) for idx, item_id in enumerate(ids)],
    )


def remove_item_from_playlist(
    conn: sqlite3.Connection,
    *,
    playlist_id: int,
    playlist_item_id: int,
) -> None:
    """
    Remove a specific playlist item.

    This deletes only the playlist_items row (i.e., removes the title from the playlist).
    Media files are NOT deleted; your library content stays on disk and in media_files.
    """
    conn.execute(
        "DELETE FROM playlist_items WHERE id = ? AND playlist_id = ?;",
        (playlist_item_id, playlist_id),
    )
    _repack_playlist_positions(conn, playlist_id)
    conn.execute(
        "UPDATE playlists SET updated_at = ? WHERE id = ?;",
        (utc_now_iso(), playlist_id),
    )



def move_playlist_item(
    conn: sqlite3.Connection,
    *,
    playlist_id: int,
    playlist_item_id: int,
    new_position: int,
) -> None:
    """
    Move an item to a new 1-based position within a playlist.

    Rules:
      - new_position is clamped into [1, N]
      - Ordering is updated and positions are repacked

    This is the primitive you need for drag-and-drop reordering later.
    """
    if new_position < 1:
        new_position = 1

    rows = conn.execute(
        "SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY position ASC, id ASC;",
        (playlist_id,),
    ).fetchall()

    ids = [int(r["id"]) for r in rows]
    if not ids:
        return

    if playlist_item_id not in ids:
        # Item isn't in this playlist; no-op.
        return

    # Clamp new_position to list bounds.
    if new_position > len(ids):
        new_position = len(ids)

    # Reorder in-memory.
    ids.remove(playlist_item_id)
    ids.insert(new_position - 1, playlist_item_id)

    # Two-pass update to avoid UNIQUE(playlist_id, position) collisions.
    conn.executemany(
        "UPDATE playlist_items SET position = position + 1000000 WHERE id = ?;",
        [(i,) for i in ids],
    )

    conn.executemany(
        "UPDATE playlist_items SET position = ? WHERE id = ?;",
        [(idx + 1, item_id) for idx, item_id in enumerate(ids)],
    )

    conn.execute(
        "UPDATE playlists SET updated_at = ? WHERE id = ?;",
        (utc_now_iso(), playlist_id),
    )


# -----------------------------
# External artwork (explicit mapping; no guessing)
# -----------------------------

def attach_artwork(
    conn: sqlite3.Connection,
    *,
    internal_key: str,
    provider: str,
    provider_id: str,
    poster_url: Optional[str] = None,
    backdrop_url: Optional[str] = None,
    confidence: float = 1.0,
) -> None:
    """Attach artwork metadata to an internal_key.

    This is an explicit mapping only. The caller decides what internal_key means.
    Examples:
      - "mf:4140" (single media file)
      - "gk:tv:3rd-rock-from-the-sun:s01" (group/card)

    Upserts the record and updates updated_at.
    """
    ik = (internal_key or "").strip()
    pv = (provider or "").strip()
    pid = (provider_id or "").strip()
    if not ik:
        raise ValueError("internal_key is required")
    if not pv:
        raise ValueError("provider is required")
    if not pid:
        raise ValueError("provider_id is required")

    if confidence is None:
        confidence = 1.0
    try:
        confidence_f = float(confidence)
    except Exception:
        confidence_f = 1.0

    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO external_artwork (
            internal_key, provider, provider_id, poster_url, backdrop_url, confidence, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(internal_key) DO UPDATE SET
            provider=excluded.provider,
            provider_id=excluded.provider_id,
            poster_url=excluded.poster_url,
            backdrop_url=excluded.backdrop_url,
            confidence=excluded.confidence,
            updated_at=excluded.updated_at;
        """,
        (ik, pv, pid, poster_url, backdrop_url, confidence_f, now, now),
    )


def detach_artwork(conn: sqlite3.Connection, *, internal_key: str) -> None:
    """Remove artwork mapping for internal_key (no-op if missing)."""
    ik = (internal_key or "").strip()
    if not ik:
        raise ValueError("internal_key is required")
    conn.execute("DELETE FROM external_artwork WHERE internal_key = ?;", (ik,))


def get_artwork_for_internal_key(
    conn: sqlite3.Connection,
    *,
    internal_key: str,
) -> Optional[Dict[str, Any]]:
    """Return the artwork mapping dict for internal_key, or None."""
    ik = (internal_key or "").strip()
    if not ik:
        raise ValueError("internal_key is required")

    row = conn.execute(
        """
        SELECT internal_key, provider, provider_id, poster_url, backdrop_url, confidence, created_at, updated_at
        FROM external_artwork
        WHERE internal_key = ?;
        """,
        (ik,),
    ).fetchone()

    return dict(row) if row else None


def list_external_artwork(
    conn: sqlite3.Connection,
    *,
    page: Page,
) -> Tuple[List[Dict[str, Any]], int]:
    """List all explicit artwork mappings (paged), newest updated first."""

    items_sql = (
        "SELECT internal_key, provider, provider_id, poster_url, backdrop_url, confidence, created_at, updated_at "
        "FROM external_artwork "
        "ORDER BY updated_at DESC, internal_key ASC"
    )

    count_sql = "SELECT COUNT(1) FROM external_artwork"

    return paged_query(
        conn,
        items_sql=items_sql,
        items_params=(),
        count_sql=count_sql,
        count_params=(),
        page=page,
    )
