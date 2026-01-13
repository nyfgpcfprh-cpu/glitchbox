from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

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
    get_user_id,
    list_settings,
    move_playlist_item,
    remove_item_from_playlist,
    rename_playlist,
    set_setting,
    list_library_media_files,
    list_library_groups,
    attach_artwork,
    detach_artwork,
    get_artwork_for_internal_key,
    list_external_artwork,
)


@dataclass(frozen=True)
class ServiceResult:
    """Standard response shape for both CLI and HTTP endpoints."""

    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


# -----------------
# Artwork Model
# -----------------

@dataclass(frozen=True)
class ArtworkRecord:
    """Explicit artwork mapping (decorator only).

    internal_key:
      - media_file:<id>
      - group_key:<group_key>

    provider:
      - e.g. 'tmdb'
    """

    internal_key: str
    provider: str
    provider_id: str
    poster_url: str | None
    confidence: str
    created_at: str


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
        """Paged full-library listing.

        Optional group_key allows filtering episodes by season.
        """
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
    # Library Groups (TV Shows / Seasons)
    # -----------------

    def library_groups(
        self,
        *,
        library_id: int,
        prefix: str,
        limit: int,
        offset: int,
    ) -> ServiceResult:
        """List distinct group_keys for a library.

        Used for TV hierarchy:
          - prefix='tv:' → shows
          - prefix='tv:<show>:' → seasons
        """
        self._init_db()
        page = Page(limit=limit, offset=offset)
        with self.db.tx() as conn:
            items, total = list_library_groups(
                conn,
                library_id=library_id,
                prefix=prefix,
                page=page,
            )
        return ServiceResult(items=items, total=total, limit=limit, offset=offset)

    # -----------------
    # Artwork (explicit, optional)
    # -----------------

    def get_artwork(self, internal_key: str) -> ArtworkRecord | None:
        """Return artwork explicitly attached to an internal key.

        internal_key examples:
          - media_file:123
          - group_key:tv:3rd-rock-from-the-sun:s01
        """
        self._init_db()
        with self.db.tx() as conn:
            row = get_artwork_for_internal_key(conn, internal_key=internal_key)
        if not row:
            return None
        return ArtworkRecord(**row)

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
        """Attach artwork explicitly (no auto-matching).

        This never modifies media metadata.
        """
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
        """Remove artwork mapping.

        Safe: deleting artwork never affects media files.
        """
        self._init_db()
        with self.db.tx() as conn:
            detach_artwork(conn, internal_key=internal_key)
