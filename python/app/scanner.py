

from __future__ import annotations

"""Scanner helpers (Phase 1B).

This file adds *library root mounting* support.

Concepts:
- A *library* is a user-defined bucket (Movies, TV Shows, Flix, etc.).
- A *library root* is a directory on disk that belongs to a library.

We do NOT move/rename/delete any media files.
We do NOT dedupe by title.

This module intentionally focuses on mapping file paths -> library_id.
Your existing scanner/indexer can call these helpers when inserting/updating rows in `media_files`.

Table(s) used:
- library_roots(library_id, root_path, recursive)
- media_files(file_path, library_id)
"""

import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple
_TV_PATTERNS = [
    # Common: "Show Name S01E02" / "Show.Name.S01E02" / "Show_Name_S01E02"
    re.compile(r"^(?P<show>.+?)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,2})\b", re.IGNORECASE),
    # Common alt: "Show Name 1x02"
    re.compile(r"^(?P<show>.+?)\b(?P<season>\d{1,2})x(?P<episode>\d{1,2})\b", re.IGNORECASE),
]

_SEASON_DIR_RX = re.compile(r"^season[\s._-]*(?P<season>\d{1,2})$", re.IGNORECASE)

_EPISODE_DIR_RX = re.compile(r"^(?:episode|ep)[\s._-]*(?P<ep>\d{1,3})\b", re.IGNORECASE)


def _slugify_show(name: str) -> str:
    """Create a stable, URL-ish slug for show names.

    Keeps only letters/numbers, converts separators to '-', collapses repeats.
    """
    s = (name or "").strip().lower()
    # Normalize common separators to spaces
    s = s.replace(".", " ").replace("_", " ").replace("-", " ")
    # Drop bracketed year like "(1996)" if it exists in show segment
    s = re.sub(r"\(\s*\d{4}\s*\)", " ", s)
    # Keep only alnum + spaces
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    slug = s.replace(" ", "-")
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def infer_group_key_from_path(file_path: str) -> Optional[str]:
    """Infer a TV group_key from the file path.

    IMPORTANT: Prefer filename patterns; fall back only to explicit 'Season N' folder segments.
    """
    base = os.path.basename(file_path or "")
    name, _ext = os.path.splitext(base)
    if not name:
        return None

    # Work on a lightly normalized string for regex matching.
    norm = name.replace(".", " ").replace("_", " ")

    for rx in _TV_PATTERNS:
        m = rx.match(norm)
        if not m:
            continue
        show_raw = (m.group("show") or "").strip()
        season = int(m.group("season"))
        if season < 0 or season > 99:
            return None
        slug = _slugify_show(show_raw)
        if not slug:
            return None
        return f"tv:{slug}:s{season:02d}"

    # Strict folder fallback:
    # If filename doesn't contain SxxEyy / 1x02, but the path has explicit `Season N`,
    # infer show from the directory immediately above the Season directory.
    try:
        parts = [p for p in (file_path or "").split(os.sep) if p]
    except Exception:
        parts = []

    if len(parts) >= 3:
        for i in range(len(parts) - 1):
            seg = parts[i]
            m2 = _SEASON_DIR_RX.match(seg)
            if not m2:
                continue

            season = int(m2.group("season"))
            if season < 0 or season > 99:
                return None

            if i - 1 < 0:
                return None

            show_raw = parts[i - 1]
            slug = _slugify_show(show_raw)
            if not slug:
                return None

            return f"tv:{slug}:s{season:02d}"

    return None


def infer_tv_episode_title_from_path(file_path: str) -> Optional[str]:
    """Infer a display title for a TV episode from its path.

    Returns:
      - "S01E01 — Episode Name" when episode name is available
      - "S01E01" when only season+episode are available

    IMPORTANT:
      - Deterministic parsing only (no network lookups).
      - Returns None when season/episode cannot be inferred.
    """

    base = os.path.basename(file_path or "")
    name, _ext = os.path.splitext(base)
    if not name:
        return None

    # Normalize for matching.
    norm = name.replace(".", " ").replace("_", " ").strip()

    season: Optional[int] = None
    episode: Optional[int] = None
    episode_name: str = ""

    # First: SxxEyy / 1x02 patterns.
    for rx in _TV_PATTERNS:
        m = rx.match(norm)
        if not m:
            continue
        try:
            season = int(m.group("season"))
            episode = int(m.group("episode"))
        except Exception:
            return None

        # Anything after the match may be an episode title.
        rest = (norm[m.end() :] or "").strip()
        # Trim common separators.
        rest = rest.lstrip(" -–—._")
        episode_name = rest
        break

    # Second: strict folder-derived season + filename "Episode N".
    if season is None or episode is None:
        # Get season from explicit Season dir.
        try:
            parts = [p for p in (file_path or "").split(os.sep) if p]
        except Exception:
            parts = []

        for i in range(len(parts) - 1):
            m2 = _SEASON_DIR_RX.match(parts[i])
            if not m2:
                continue
            try:
                season = int(m2.group("season"))
            except Exception:
                return None
            break

        # Get episode from filename.
        m3 = _EPISODE_DIR_RX.match(norm)
        if m3:
            try:
                episode = int(m3.group("ep"))
            except Exception:
                return None
            # Try to parse a friendly episode name after the episode number.
            rest = (norm[m3.end() :] or "").strip()
            rest = rest.lstrip(" -–—._")
            episode_name = rest

    if season is None or episode is None:
        return None

    if season < 0 or season > 99:
        return None
    if episode < 0 or episode > 999:
        return None

    tag = f"S{season:02d}E{episode:02d}"
    if episode_name:
        # Avoid overly long junk; keep it readable.
        ep = re.sub(r"\s+", " ", episode_name).strip()
        if ep:
            return f"{tag} — {ep}"

    return tag


@dataclass(frozen=True)
class LibraryRoot:
    """A mounted directory that belongs to a library."""

    id: int
    library_id: int
    root_path: str
    recursive: bool


def normalize_path(p: str) -> str:
    """Normalize a path for reliable prefix comparisons.

    - Expands `~`
    - Converts to absolute path
    - Normalizes separators and removes trailing slashes

    IMPORTANT:
    - We do not resolve symlinks here (no realpath) because users may mount
      volumes/symlinks intentionally.
    """
    p = (p or "").strip()
    # On POSIX systems, users often paste shell-escaped paths like "TV\ Shows".
    # The database should store real filesystem paths, so we normalize this here.
    # (Windows paths legitimately use backslashes, so only do this on POSIX.)
    if os.sep == "/":
        p = p.replace("\\ ", " ")
    if not p:
        return ""
    p = os.path.expanduser(p)
    p = os.path.abspath(p)
    p = os.path.normpath(p)
    return p


def load_library_roots(conn: sqlite3.Connection) -> List[LibraryRoot]:
    """Load all library roots, normalized, sorted longest-root-first.

    Longest-root-first ensures that if you have overlapping roots, the most
    specific root wins.

    Example:
      /Volumes/plex1/movies
      /Volumes/plex1/movies/movies
    The second one should match files under it first.
    """
    rows = conn.execute(
        """
        SELECT id, library_id, root_path, recursive
        FROM library_roots
        ORDER BY LENGTH(root_path) DESC, root_path COLLATE NOCASE ASC, id ASC;
        """
    ).fetchall()

    roots: List[LibraryRoot] = []
    for r in rows:
        roots.append(
            LibraryRoot(
                id=int(r[0]),
                library_id=int(r[1]),
                root_path=normalize_path(str(r[2])),
                recursive=bool(int(r[3])),
            )
        )
    return roots


def match_library_id_for_file(roots: Iterable[LibraryRoot], file_path: str) -> Optional[int]:
    """Return the best matching library_id for a file path.

    Matching rules:
    - root_path must be a prefix of the file path (directory boundary aware)
    - If recursive=True: any depth under root matches
    - If recursive=False: file must be directly under root (no nested dirs)

    Returns:
    - library_id if matched
    - None if no roots match
    """
    fp = normalize_path(file_path)
    if not fp:
        return None

    # Ensure directory-boundary matching (avoid '/Movies2' matching '/Movies').
    for root in roots:
        rp = root.root_path
        if not rp:
            continue

        if fp == rp:
            # A file path equal to a directory root is unusual, but treat as match.
            return root.library_id

        prefix = rp + os.sep
        if not fp.startswith(prefix):
            continue

        if root.recursive:
            return root.library_id

        # Non-recursive: the file must be directly under the root directory.
        parent = os.path.dirname(fp)
        if normalize_path(parent) == rp:
            return root.library_id

    return None


def backfill_media_files_library_ids(conn: sqlite3.Connection) -> Tuple[int, int]:
    """Populate media_files.library_id for existing rows.

    This is useful when:
    - You added libraries + roots after an initial scan
    - You want to associate already-indexed files with libraries

    It updates only rows where library_id is NULL.

    Returns:
    - (updated_count, total_examined)
    """
    roots = load_library_roots(conn)

    rows = conn.execute(
        "SELECT id, file_path FROM media_files WHERE library_id IS NULL;"
    ).fetchall()

    updated = 0
    examined = 0

    for r in rows:
        examined += 1
        media_file_id = int(r[0])
        file_path = str(r[1])
        lib_id = match_library_id_for_file(roots, file_path)
        if lib_id is None:
            continue

        conn.execute(
            "UPDATE media_files SET library_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (lib_id, media_file_id),
        )
        updated += 1

    return updated, examined


# -----------------------------
# Phase 1B: Minimal scanner (Option A) + engine hook (Option B)
# -----------------------------

import fnmatch
from datetime import datetime, timezone
from typing import Dict, Set


def _utc_now_iso() -> str:
    """UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    """Return the set of column names for a table."""
    cols = set()
    for row in conn.execute(f"PRAGMA table_info({table});").fetchall():
        # row: (cid, name, type, notnull, dflt_value, pk)
        cols.add(str(row[1]))
    return cols


def _is_video_file(path: str, allowed_exts: Set[str] | None) -> bool:
    if allowed_exts is None:
        # Safe default set; user can override via CLI later.
        allowed_exts = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".webm"}
    _, ext = os.path.splitext(path)
    return ext.lower() in allowed_exts


def _iter_files_under_root(root_path: str, recursive: bool) -> Iterable[str]:
    """Yield file paths under a root directory."""
    rp = normalize_path(root_path)
    if not rp or not os.path.isdir(rp):
        return

    if recursive:
        for dirpath, _dirnames, filenames in os.walk(rp):
            for fn in filenames:
                yield os.path.join(dirpath, fn)
    else:
        for fn in os.listdir(rp):
            p = os.path.join(rp, fn)
            if os.path.isfile(p):
                yield p


def scan_library_roots(
    conn: sqlite3.Connection,
    *,
    allowed_exts: Set[str] | None = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Scan all mounted library roots and upsert rows into `media_files`.

    This is the concrete implementation for Option A.

    Notes / constraints:
    - Index is by file path (NOT by title)
    - Does not move/rename/delete media
    - No artificial limits
    - Assigns `library_id` using the *best* matching root (longest prefix)

    Returns a stats dict.
    """
    roots = load_library_roots(conn)

    # Discover files from all roots, de-duping by normalized file path.
    discovered: Set[str] = set()
    for r in roots:
        for p in _iter_files_under_root(r.root_path, r.recursive):
            p2 = normalize_path(p)
            if p2:
                discovered.add(p2)

    cols = _table_columns(conn, "media_files")
    now = _utc_now_iso()

    scanned = 0
    inserted = 0
    updated = 0
    skipped_unmatched = 0

    # We will try an UPSERT if possible, otherwise fall back to SELECT+INSERT/UPDATE.
    # Assume `file_path` is unique (it should be for file-indexing).

    for file_path in sorted(discovered):
        if not _is_video_file(file_path, allowed_exts):
            continue

        scanned += 1
        lib_id = match_library_id_for_file(roots, file_path)
        if lib_id is None:
            skipped_unmatched += 1
            continue

        if dry_run:
            continue

        # Build INSERT columns dynamically so we don't depend on a particular schema beyond `file_path`.
        insert_cols = ["file_path"]
        insert_vals: list[object] = [file_path]
        inferred_group_key: Optional[str] = None
        inferred_title: Optional[str] = None

        if "group_key" in cols:
            inferred_group_key = infer_group_key_from_path(file_path)
            insert_cols.append("group_key")
            insert_vals.append(inferred_group_key)

        if "title" in cols and inferred_group_key and inferred_group_key.startswith("tv:"):
            inferred_title = infer_tv_episode_title_from_path(file_path)
            insert_cols.append("title")
            insert_vals.append(inferred_title)

        if "library_id" in cols:
            insert_cols.append("library_id")
            insert_vals.append(lib_id)

        if "first_seen_at" in cols:
            insert_cols.append("first_seen_at")
            insert_vals.append(now)

        if "created_at" in cols:
            insert_cols.append("created_at")
            insert_vals.append(now)

        if "updated_at" in cols:
            insert_cols.append("updated_at")
            insert_vals.append(now)

        # Try insert; if conflict, update library_id/updated_at.
        placeholders = ",".join(["?"] * len(insert_cols))
        col_list = ",".join(insert_cols)

        # Build update set dynamically.
        update_sets: list[str] = []
        update_vals: list[object] = []
        if "library_id" in cols:
            update_sets.append("library_id = ?")
            update_vals.append(lib_id)
        if "updated_at" in cols:
            update_sets.append("updated_at = ?")
            update_vals.append(now)
        if "group_key" in cols:
            # Only set group_key if it was previously NULL; never overwrite user/admin corrections.
            update_sets.append("group_key = COALESCE(group_key, excluded.group_key)")

        if "title" in cols:
            # Only backfill title when NULL; never overwrite.
            update_sets.append("title = COALESCE(title, excluded.title)")

        if update_sets:
            upsert_sql = (
                f"INSERT INTO media_files ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT(file_path) DO UPDATE SET {', '.join(update_sets)};"
            )
            try:
                # Determine whether this is an insert vs update BEFORE the upsert.
                existed_before = conn.execute(
                    "SELECT 1 FROM media_files WHERE file_path = ? LIMIT 1;",
                    (file_path,),
                ).fetchone()

                _ = conn.execute(upsert_sql, (*insert_vals, *update_vals))

                if existed_before:
                    updated += 1
                else:
                    inserted += 1
                continue
            except sqlite3.OperationalError:
                # If ON CONFLICT(file_path) isn't supported (no unique constraint), fall back.
                pass

        # Fallback: SELECT then INSERT/UPDATE
        row = conn.execute(
            "SELECT id FROM media_files WHERE file_path = ? LIMIT 1;",
            (file_path,),
        ).fetchone()

        if row is None:
            conn.execute(
                f"INSERT INTO media_files ({col_list}) VALUES ({placeholders});",
                tuple(insert_vals),
            )
            inserted += 1
        else:
            # Update existing row
            sets = []
            vals: list[object] = []
            if "library_id" in cols:
                sets.append("library_id = ?")
                vals.append(lib_id)
            if "updated_at" in cols:
                sets.append("updated_at = ?")
                vals.append(now)
            if sets:
                vals.append(int(row[0]))
                conn.execute(
                    f"UPDATE media_files SET {', '.join(sets)} WHERE id = ?;",
                    tuple(vals),
                )

            # Preserve existing group_key; only backfill when NULL.
            if "group_key" in cols and inferred_group_key:
                conn.execute(
                    "UPDATE media_files SET group_key = ? WHERE id = ? AND group_key IS NULL;",
                    (inferred_group_key, int(row[0])),
                )
            # Preserve existing title; only backfill when NULL.
            if "title" in cols and inferred_title:
                conn.execute(
                    "UPDATE media_files SET title = ? WHERE id = ? AND title IS NULL;",
                    (inferred_title, int(row[0])),
                )
            updated += 1

    return {
        "roots": len(roots),
        "discovered_files": len(discovered),
        "scanned_video_files": scanned,
        "inserted": inserted,
        "updated": updated,
        "skipped_unmatched": skipped_unmatched,
        "dry_run": 1 if dry_run else 0,
    }


class ScannerEngine:
    """Engine abstraction (Option B hook).

    Today both engines can share the same Python implementation.
    Later, a Go-based scanner can be exposed behind this interface.
    """

    name: str = "base"

    def scan(self, conn: sqlite3.Connection, *, allowed_exts: Set[str] | None = None, dry_run: bool = False) -> Dict[str, int]:
        raise NotImplementedError


class SimpleScannerEngine(ScannerEngine):
    """Option A: direct Python scan."""

    name = "simple"

    def scan(self, conn: sqlite3.Connection, *, allowed_exts: Set[str] | None = None, dry_run: bool = False) -> Dict[str, int]:
        return scan_library_roots(conn, allowed_exts=allowed_exts, dry_run=dry_run)


class PluginScannerEngine(ScannerEngine):
    """Option B: placeholder for alternate scanner implementations.

    For Phase 1, this delegates to the simple engine.
    In Phase 2, this can dispatch to a Go scanner binary/process.
    """

    name = "plugin"

    def scan(self, conn: sqlite3.Connection, *, allowed_exts: Set[str] | None = None, dry_run: bool = False) -> Dict[str, int]:
        # Placeholder: for now, reuse the Python implementation.
        return scan_library_roots(conn, allowed_exts=allowed_exts, dry_run=dry_run)


def get_scanner_engine(name: str) -> ScannerEngine:
    n = (name or "").strip().lower()
    if n in ("simple", "a", "option-a"):
        return SimpleScannerEngine()
    if n in ("plugin", "b", "option-b"):
        return PluginScannerEngine()
    raise ValueError(f"unknown scanner engine: {name}")