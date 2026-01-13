import { createRouter } from "./router.js";
import { createApiClient } from "./api/client.js";

// Explicit UI configuration (no guessing)
if (!window.__GLITCHBOX_LIBRARY_SCAN_PATH) {
  // Default to the known backend endpoint.
  // If you want a per-library scan route, you can override this explicitly.
  window.__GLITCHBOX_LIBRARY_SCAN_PATH = "/scan";
}
const appEl = document.getElementById("app");
if (!appEl) throw new Error("#app not found");


const api = createApiClient();

// When running the Web UI on its own port (e.g., 5173), API/artwork live on the backend port (e.g., 8765).
// Allow overriding via window.__GLITCHBOX_API_BASE if needed.
const API_BASE = (() => {
  try {
    const v = window.__GLITCHBOX_API_BASE;
    if (typeof v === "string" && v.trim()) return v.trim().replace(/\/$/, "");
  } catch {
    // ignore
  }
  try {
    const { protocol, host, hostname } = window.location;
    if (hostname && hostname !== "127.0.0.1" && hostname !== "localhost") {
      return `${protocol}//${host}`;
    }
  } catch {
    // ignore
  }
  return "http://127.0.0.1:8765";
})();

// Optional server-side scan endpoint template.
// We DO NOT guess routes. If you want a Scan button, provide a template like:
//   window.__GLITCHBOX_LIBRARY_SCAN_PATH = "/libraries/{id}/scan"
// This button will POST to API_BASE + that path with {id} replaced.
const LIBRARY_SCAN_PATH_TEMPLATE = (() => {
  try {
    const v = window.__GLITCHBOX_LIBRARY_SCAN_PATH;
    if (typeof v === "string" && v.trim()) return v.trim();
  } catch {
    // ignore
  }
  return null;
})();

function normalizeStoredUrl(v) {
  if (v == null) return null;
  const s = String(v).trim();
  if (!s) return null;
  if (s === "null" || s === "undefined") return null;
  return s;
}

function absolutizeArtworkUrl(url) {
  const s = normalizeStoredUrl(url);
  if (!s) return null;
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith("/")) return API_BASE + s;
  return s;
}

// -----------------
// Artwork (server-persisted poster mapping)
// -----------------
// Posters are stored in the server DB (external_artwork) and cached client-side.

const ARTWORK_CACHE = new Map();
let ARTWORK_CACHE_READY = false;
let ARTWORK_CACHE_PROMISE = null;

function posterKeyForMediaFileId(id) {
  return `media_file:${id}`;
}

function posterKeyForTvShow(showSlug) {
  return `group_key:tv:${showSlug}`;
}

function posterKeyForTvSeason(showSlug, season2) {
  // season2 must be 2-digit string, e.g. "01"
  return `group_key:tv:${showSlug}:s${season2}`;
}

async function ensureArtworkCache() {
  if (ARTWORK_CACHE_READY) return;
  if (ARTWORK_CACHE_PROMISE) return ARTWORK_CACHE_PROMISE;
  ARTWORK_CACHE_PROMISE = (async () => {
    let offset = 0;
    const limit = 200;
    for (;;) {
      const res = await api.get(`/artwork?limit=${limit}&offset=${offset}`);
      const items = Array.isArray(res?.items) ? res.items : [];
      for (const it of items) {
        const key = it?.internal_key;
        if (!key) continue;
        const url = absolutizeArtworkUrl(it?.poster_url);
        if (url) ARTWORK_CACHE.set(key, url);
      }
      if (items.length < limit) break;
      offset += limit;
    }
    ARTWORK_CACHE_READY = true;
  })();
  return ARTWORK_CACHE_PROMISE;
}

function getPosterUrlForMediaFileId(id) {
  if (!id) return null;
  const key = posterKeyForMediaFileId(id);
  return ARTWORK_CACHE.get(key) || null;
}

function getPosterUrlForTvShow(showSlug) {
  if (!showSlug) return null;
  return ARTWORK_CACHE.get(posterKeyForTvShow(showSlug)) || null;
}

function getPosterUrlForTvSeason(showSlug, season2) {
  if (!showSlug || !season2) return null;
  return ARTWORK_CACHE.get(posterKeyForTvSeason(showSlug, season2)) || null;
}

async function setPosterForInternalKey({ internalKey, url, provider, providerId }) {
  const posterUrl = absolutizeArtworkUrl(url);
  if (!internalKey) return;

  if (!posterUrl) {
    await api.del(`/artwork?internal_key=${encodeURIComponent(internalKey)}`);
    ARTWORK_CACHE.delete(internalKey);
    return;
  }

  await api.post("/artwork", {
    internal_key: internalKey,
    provider: provider || "manual",
    provider_id: providerId || "manual",
    poster_url: posterUrl,
  });
  ARTWORK_CACHE.set(internalKey, posterUrl);
}

async function setPosterUrlForMediaFileId(id, url, provider = "manual", providerId = "manual") {
  if (!id) return;
  return setPosterForInternalKey({
    internalKey: posterKeyForMediaFileId(id),
    url,
    provider,
    providerId,
  });
}

async function setPosterUrlForTvShow(showSlug, url, provider = "manual", providerId = "manual") {
  if (!showSlug) return;
  return setPosterForInternalKey({
    internalKey: posterKeyForTvShow(showSlug),
    url,
    provider,
    providerId,
  });
}

async function setPosterUrlForTvSeason(showSlug, season2, url, provider = "manual", providerId = "manual") {
  if (!showSlug || !season2) return;
  return setPosterForInternalKey({
    internalKey: posterKeyForTvSeason(showSlug, season2),
    url,
    provider,
    providerId,
  });
}

function effectivePosterUrlForEpisode({ showSlug, season2, mediaFileId }) {
  // Explicit fallback chain. No guessing.
  // 1) season poster
  const seasonUrl = getPosterUrlForTvSeason(showSlug, season2);
  if (seasonUrl) return seasonUrl;
  // 2) show poster
  const showUrl = getPosterUrlForTvShow(showSlug);
  if (showUrl) return showUrl;
  // 3) legacy per-media mapping (optional): if one exists, use it, but TV UX will stop setting these.
  const mfUrl = getPosterUrlForMediaFileId(mediaFileId);
  if (mfUrl) return mfUrl;
  return null;
}

async function setPosterFlowForTvShow({ router, showSlug, showName }) {
  const defaultQ = showName || showSlug || "";
  const q = prompt("TMDB search (tv) — set SHOW poster:", defaultQ);
  if (!q) return;

  let items;
  try {
    items = await tmdbSearchTv(q);
  } catch (e) {
    alert(`TMDB search failed: ${e?.message || e}`);
    return;
  }

  if (!items.length) {
    alert("No results.");
    return;
  }

  const max = Math.min(10, items.length);
  const previewLines = items
    .slice(0, max)
    .map((it, idx) => {
      const yr = it.year ? ` (${it.year})` : "";
      const p = it.poster_path ? " [poster]" : "";
      return `${idx + 1}. ${it.title}${yr}${p}`;
    })
    .join("\n");

  const pickRaw = prompt(`Pick a result (1-${max}) for SHOW poster:\n\n${previewLines}`, "1");
  if (!pickRaw) return;

  const pick = Number(pickRaw);
  if (!Number.isFinite(pick) || pick < 1 || pick > max) {
    alert("Invalid selection.");
    return;
  }

  const chosen = items[pick - 1];
  if (!chosen?.poster_path) {
    alert("Chosen result has no poster.");
    return;
  }

  let url;
  try {
    url = await cacheTmdbPoster({ tmdbType: "tv", tmdbId: chosen.id, posterPath: chosen.poster_path, size: "w342" });
  } catch (e) {
    alert(`Poster cache failed: ${e?.message || e}`);
    return;
  }

  await setPosterUrlForTvShow(showSlug, url, "tmdb", String(chosen.id));
  router.navigate(window.location.hash.replace(/^#/, "") || "/");
}

async function setPosterFlowForTvSeason({ router, showSlug, showName, season2 }) {
  const s2 = String(season2 || "").padStart(2, "0");
  const defaultQ = showName ? `${showName} Season ${s2}` : (showSlug ? `${showSlug} Season ${s2}` : "");
  const q = prompt(`TMDB search (tv) — set SEASON ${s2} poster:`, defaultQ);
  if (!q) return;

  let items;
  try {
    items = await tmdbSearchTv(q);
  } catch (e) {
    alert(`TMDB search failed: ${e?.message || e}`);
    return;
  }

  if (!items.length) {
    alert("No results.");
    return;
  }

  const max = Math.min(10, items.length);
  const previewLines = items
    .slice(0, max)
    .map((it, idx) => {
      const yr = it.year ? ` (${it.year})` : "";
      const p = it.poster_path ? " [poster]" : "";
      return `${idx + 1}. ${it.title}${yr}${p}`;
    })
    .join("\n");

  const pickRaw = prompt(`Pick a result (1-${max}) for SEASON ${s2} poster:\n\n${previewLines}`, "1");
  if (!pickRaw) return;

  const pick = Number(pickRaw);
  if (!Number.isFinite(pick) || pick < 1 || pick > max) {
    alert("Invalid selection.");
    return;
  }

  const chosen = items[pick - 1];
  if (!chosen?.poster_path) {
    alert("Chosen result has no poster.");
    return;
  }

  let url;
  try {
    url = await cacheTmdbPoster({ tmdbType: "tv", tmdbId: chosen.id, posterPath: chosen.poster_path, size: "w342" });
  } catch (e) {
    alert(`Poster cache failed: ${e?.message || e}`);
    return;
  }

  await setPosterUrlForTvSeason(showSlug, s2, url, "tmdb", String(chosen.id));
  router.navigate(window.location.hash.replace(/^#/, "") || "/");
}

function makePosterImg(urlOrNull, { onClick, isSet, title } = {}) {
  const img = document.createElement("img");
  img.loading = "lazy";
  img.decoding = "async";
  img.alt = "poster";
  img.style.width = "46px";
  img.style.height = "69px";
  img.style.objectFit = "cover";

  // Visual truth: set vs not-set is obvious.
  // - isSet=true: solid border
  // - isSet=false: dashed border
  img.style.border = isSet ? "2px solid #4caf50" : "1px dashed #bbb";
  img.style.borderRadius = "3px";
  img.style.cursor = typeof onClick === "function" ? "pointer" : "default";
  if (typeof title === "string" && title.trim()) {
    img.title = title;
  } else {
    img.title = isSet ? "Poster set (click to change)" : "No poster set (click to set)";
  }

  // Tiny inline placeholder so we never show a blank poster cell.
  const placeholderSvg =
    "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(
      `<svg xmlns='http://www.w3.org/2000/svg' width='46' height='69'>
         <rect width='100%' height='100%' fill='#f2f2f2'/>
         <path d='M6 58 L18 40 L30 52 L40 36 L40 63 L6 63 Z' fill='#d0d0d0'/>
         <rect x='6' y='6' width='34' height='6' fill='#e0e0e0'/>
         <rect x='6' y='16' width='26' height='6' fill='#e0e0e0'/>
       </svg>`
    );

  const resolved = absolutizeArtworkUrl(urlOrNull);
  img.src = resolved || placeholderSvg;
  img.onerror = () => {
    // Never show a broken-image icon; fall back to the inline placeholder.
    img.onerror = null;
    img.src = placeholderSvg;
  };

  if (typeof onClick === "function") {
    img.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      onClick();
    });
  }

  return img;
}

async function tmdbSearchMovies(query) {
  const q = encodeURIComponent(query || "");
  const data = await api.get(`/providers/tmdb/search?type=movie&q=${q}`);
  return Array.isArray(data?.items) ? data.items : [];
}

async function tmdbSearchTv(query) {
  const q = encodeURIComponent(query || "");
  const data = await api.get(`/providers/tmdb/search?type=tv&q=${q}`);
  return Array.isArray(data?.items) ? data.items : [];
}

// -----------------
// TMDB auto-pick helpers (the ONLY allowed magic)
// -----------------
// This auto mode picks the FIRST result returned by TMDB that has a poster_path.
// It is still explicit: the user must confirm before running, and we provide an undo for the last run.

let _lastAutoPosterRun = null;
// shape:
// {
//   label: string,
//   changes: Array<{ kind: "movie"|"tv_show"|"tv_season", key: string, prev: string|null, next: string|null }>
// }

function beginAutoPosterRun(label) {
  _lastAutoPosterRun = { label, changes: [] };
  return _lastAutoPosterRun;
}

function recordAutoPosterChange(kind, key, prev, next) {
  if (!_lastAutoPosterRun) return;
  _lastAutoPosterRun.changes.push({ kind, key, prev: prev ?? null, next: next ?? null });
}

async function undoLastAutoPosterRun() {
  if (!_lastAutoPosterRun || !_lastAutoPosterRun.changes.length) {
    alert("No auto-poster run to undo.");
    return;
  }
  // Reverse apply
  for (let i = _lastAutoPosterRun.changes.length - 1; i >= 0; i--) {
    const ch = _lastAutoPosterRun.changes[i];
    try {
      if (ch.kind === "movie") {
        // key is mediaFileId
        await setPosterUrlForMediaFileId(ch.key, ch.prev);
      } else if (ch.kind === "tv_show") {
        // key is showSlug
        await setPosterUrlForTvShow(ch.key, ch.prev);
      } else if (ch.kind === "tv_season") {
        // key is showSlug|season2
        const parts = String(ch.key).split("|");
        const showSlug = parts[0];
        const season2 = parts[1];
        if (showSlug && season2) await setPosterUrlForTvSeason(showSlug, season2, ch.prev);
      }
    } catch {
      // ignore
    }
  }
  alert(`Undid last auto-poster run (${_lastAutoPosterRun.label}).`);
  _lastAutoPosterRun = null;
}

async function tmdbAutoPickPoster({ tmdbType, query, size }) {
  const t = tmdbType === "tv" ? "tv" : "movie";
  const q = String(query || "").trim();
  if (!q) return null;

  const items = t === "tv" ? await tmdbSearchTv(q) : await tmdbSearchMovies(q);
  if (!Array.isArray(items) || items.length === 0) return null;

  const chosen = items.find((it) => it && it.poster_path);
  if (!chosen || !chosen.poster_path) return null;

  const url = await cacheTmdbPoster({ tmdbType: t, tmdbId: chosen.id, posterPath: chosen.poster_path, size: size || "w342" });
  if (!url) return null;
  return { url, tmdbId: String(chosen.id), tmdbType: t };
}

// -----------------
// Library-level Auto Fetch Posters helpers
// -----------------
async function autoFetchMissingMoviePostersForLibrary({ libraryId, statusEl }) {
  const id = String(libraryId);
  await ensureArtworkCache();
  const limit = 200;
  let offset = 0;
  let total = null;
  let done = 0;
  let setCount = 0;

  for (;;) {
    const res = await api.get(`/libraries/${encodeURIComponent(id)}/media-files?limit=${limit}&offset=${offset}&order=title_asc`);
    const items = res?.items ?? [];
    total = Number(res?.total ?? (total ?? 0)) || (total ?? items.length);

    for (const it of items) {
      const mediaId = it?.id ?? it?.media_file_id;
      if (mediaId == null) continue;
      const mid = String(mediaId);
      const prev = getPosterUrlForMediaFileId(mid);
      if (prev) {
        done++;
        continue;
      }

      const rawTitle = it?.title ?? it?.display_title ?? it?.name ?? "";
      const path = it?.file_path ?? it?.path ?? "";
      const title = (rawTitle && String(rawTitle).trim()) ? String(rawTitle) : basenameNoExt(path);

      if (statusEl) statusEl.textContent = `Auto Fetch (movies) — ${done + 1} / ${total || "?"} … ${title}`;

      try {
        const picked = await tmdbAutoPickPoster({ tmdbType: "movie", query: title, size: "w342" });
        if (picked?.url) {
          await setPosterUrlForMediaFileId(mid, picked.url, "tmdb", picked.tmdbId);
          recordAutoPosterChange("movie", mid, null, picked.url);
          setCount++;
        }
      } catch {
        // continue
      }
      done++;
    }

    offset += items.length;
    if (!items.length || (total != null && offset >= total)) break;
  }
  if (statusEl) statusEl.textContent = `Auto Fetch (movies) — done. Set ${setCount} posters.`;
}

async function autoFetchMissingTvPostersForLibrary({ libraryId, statusEl }) {
  const id = String(libraryId);
  await ensureArtworkCache();

  // Build show->season list from groups
  const groups = await fetchAllGroups(api, id, "tv:");
  const showMap = new Map();

  for (const g of (groups || [])) {
    const gk = g?.group_key;
    const show = tvShowFromGroupKey(gk);
    const seasonNum = tvSeasonFromGroupKey(gk);
    if (!show || seasonNum == null) continue;
    if (!showMap.has(show)) showMap.set(show, new Set());
    showMap.get(show).add(seasonNum);
  }

  const shows = Array.from(showMap.keys()).sort((a, b) => tvDisplayShowName(a).localeCompare(tvDisplayShowName(b)));
  if (!shows.length) {
    if (statusEl) statusEl.textContent = "Auto Fetch (tv) — no TV groups found for this library (no group_key prefix tv:).";
    return;
  }

  let idx = 0;
  for (const show of shows) {
    idx++;
    const showName = tvDisplayShowName(show);

    // Show poster
    if (!getPosterUrlForTvShow(show)) {
      if (statusEl) statusEl.textContent = `Auto Fetch (tv) — show ${idx}/${shows.length} … ${showName}`;
      try {
        const prev = getPosterUrlForTvShow(show);
        const picked = await tmdbAutoPickPoster({ tmdbType: "tv", query: showName || show, size: "w342" });
        if (picked?.url) {
          await setPosterUrlForTvShow(show, picked.url, "tmdb", picked.tmdbId);
          recordAutoPosterChange("tv_show", show, prev, picked.url);
        }
      } catch {
        // continue
      }
    }

    // Season posters
    const seasonSet = showMap.get(show) || new Set();
    const seasons = Array.from(seasonSet).sort((a, b) => a - b);

    for (const n of seasons) {
      const s2 = String(n).padStart(2, "0");
      if (getPosterUrlForTvSeason(show, s2)) continue;

      const q = `${showName} Season ${s2}`;
      if (statusEl) statusEl.textContent = `Auto Fetch (tv) — ${showName} season ${s2} …`;

      try {
        const prev = getPosterUrlForTvSeason(show, s2);
        const picked = await tmdbAutoPickPoster({ tmdbType: "tv", query: q, size: "w342" });
        if (picked?.url) {
          await setPosterUrlForTvSeason(show, s2, picked.url, "tmdb", picked.tmdbId);
          recordAutoPosterChange("tv_season", `${show}|${s2}`, prev, picked.url);
        }
      } catch {
        // continue
      }
    }
  }
}

async function cacheTmdbPoster({ tmdbType, tmdbId, posterPath, size }) {
  // Backward-compatible for existing call sites in this file.
  // In the next chunk we will pass tmdbType explicitly from each flow.
  const t = tmdbType === "tv" ? "tv" : "movie";
  const payload = {
    kind: "poster",
    tmdb_type: t,
    tmdb_id: String(tmdbId),
    file_path: posterPath,
    size: size || "w342",
  };
  const data = await api.post(`/artwork/cache-tmdb`, payload);
  if (!data?.url) throw new Error("No artwork url returned");
  return data.url;
}

async function setPosterFlowForRow({ router, row, tmdbType }) {
  const defaultQ = row.title || "";

  // Backward-compatible default: existing call sites behave as movie.
  // Allowed explicit values: "movie" | "tv".
  const t = tmdbType === "tv" || tmdbType === "movie" ? tmdbType : "movie";

  // Scope enforcement: per-item poster setting is NOT allowed for TV.
  // TV posters must be set at show/season scope only.
  if (t === "tv") {
    alert(
      "TV posters are set at show/season scope only. Per-episode / per-item posters are not allowed. Use the TV Shows browse view to set show and season posters."
    );
    return;
  }

  const q = prompt(`TMDB search (${t}):`, defaultQ);
  if (!q) return;

  let items;
  try {
    items = t === "tv" ? await tmdbSearchTv(q) : await tmdbSearchMovies(q);
  } catch (e) {
    alert(`TMDB search failed: ${e?.message || e}`);
    return;
  }

  if (!items.length) {
    alert("No results.");
    return;
  }

  const max = Math.min(10, items.length);
  const previewLines = items
    .slice(0, max)
    .map((it, idx) => {
      const yr = it.year ? ` (${it.year})` : "";
      const p = it.poster_path ? " [poster]" : "";
      return `${idx + 1}. ${it.title}${yr}${p}`;
    })
    .join("\n");

  const pickRaw = prompt(`Pick a result (1-${max}):\n\n${previewLines}`, "1");
  if (!pickRaw) return;

  const pick = Number(pickRaw);
  if (!Number.isFinite(pick) || pick < 1 || pick > max) {
    alert("Invalid selection.");
    return;
  }

  const chosen = items[pick - 1];
  if (!chosen?.poster_path) {
    alert("Chosen result has no poster.");
    return;
  }

  let url;
  try {
    url = await cacheTmdbPoster({ tmdbType: t, tmdbId: chosen.id, posterPath: chosen.poster_path, size: "w342" });
  } catch (e) {
    alert(`Poster cache failed: ${e?.message || e}`);
    return;
  }

  await setPosterUrlForMediaFileId(row.id, url, "tmdb", String(chosen.id));

  // Re-render current route so the poster cell updates.
  router.navigate(window.location.hash.replace(/^#/, "") || "/");
}

// -----------------
// Minimal admin-first shell
// -----------------
// NOTE: For this step we keep everything self-contained in app.js so we don't
// depend on any other files/modules yet. Next steps will move these into
// src/pages/* and src/components/*.

function h(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, String(v));
  }
  for (const c of children) {
    if (c == null) continue;
    if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
  return el;
}

function renderTopNav(router) {
  const nav = h("div", {
    style: {
      display: "flex",
      gap: "12px",
      alignItems: "center",
      marginBottom: "16px",
    },
  });

  const brand = h("strong", {}, ["GlitchBox"]);
  nav.appendChild(brand);

  const links = [
    ["Dashboard", "/"],
    ["Libraries", "/libraries"],
    ["Continue Watching", "/continue"],
    ["Playlists", "/playlists"],
    ["Settings", "/settings"],
  ];

  for (const [label, path] of links) {
    const a = h("a", { href: "#" + path }, [label]);
    a.addEventListener("click", (e) => {
      e.preventDefault();
      router.navigate(path);
    });
    nav.appendChild(a);
  }

  return nav;
}

function renderPageTitle(title, subtitle = "") {
  const wrap = h("div");
  wrap.appendChild(h("h1", {}, [title]));
  if (subtitle) wrap.appendChild(h("p", {}, [subtitle]));
  return wrap;
}

// Helper: get basename without extension
function basenameNoExt(p) {
  if (!p) return "";
  const s = String(p);
  const parts = s.split("/");
  const base = parts[parts.length - 1] || "";
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(0, dot) : base;
}

// Helper: shorten long paths but keep filename
function shortenPath(p, maxLen = 80) {
  if (!p) return "";
  const s = String(p);
  if (s.length <= maxLen) return s;
  // Keep the end (filename) since it's the most useful.
  const tailLen = Math.max(30, Math.floor(maxLen * 0.6));
  return "…" + s.slice(s.length - tailLen);
}

function formatSeconds(sec) {
  const n = Number(sec);
  if (!Number.isFinite(n) || n < 0) return "";
  const s = Math.floor(n);
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  if (hh > 0) return `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

function navigateToPlay(router, mediaId, posSeconds = 0) {
  const id = String(mediaId);
  const pos = Math.max(0, Number(posSeconds) || 0);
  if (pos > 0) router.navigate(`/play/${id}?pos=${encodeURIComponent(String(pos))}`);
  else router.navigate(`/play/${id}`);
}

// TV group_key helpers
// group_key format: tv:<show-slug>:sNN
function isTvGroupKey(gk) {
  return typeof gk === "string" && gk.startsWith("tv:");
}

function tvShowFromGroupKey(gk) {
  // tv:3rd-rock-from-the-sun:s01 -> 3rd-rock-from-the-sun
  if (!isTvGroupKey(gk)) return null;
  const parts = String(gk).split(":");
  if (parts.length < 3) return null;
  return parts[1] || null;
}

function tvSeasonFromGroupKey(gk) {
  // tv:show:s01 -> 1
  if (!isTvGroupKey(gk)) return null;
  const parts = String(gk).split(":");
  const last = parts[parts.length - 1] || "";
  const m = /^s(\d{1,2})$/i.exec(last);
  if (!m) return null;
  return Number(m[1]);
}

function tvDisplayShowName(showSlug) {
  // Best-effort display: slug -> Title Case words, keep numbers.
  if (!showSlug) return "";
  return String(showSlug)
    .split("-")
    .filter(Boolean)
    .map((w) => w.length ? (w[0].toUpperCase() + w.slice(1)) : w)
    .join(" ");
}

// -----------------
// Library type detection (explicit; name-based)
// -----------------
// Rule: detection is based ONLY on the library name string.
// No auto-fallback or inference beyond these keywords.

const _libraryTypeCache = new Map(); // libraryId -> "movie" | "tv" | "unknown"

function classifyLibraryTypeFromName(name) {
  const s = String(name || "").toLowerCase();
  // Explicit keyword match only.
  // Examples that should match: "TV", "TV Shows", "Shows", "Television", "Series"
  // Non-matches remain "movie" by default.
  const tvKeywords = [
    "tv",
    "tv shows",
    "shows",
    "television",
    "series",
  ];

  for (const k of tvKeywords) {
    if (!k) continue;
    // word-boundary-ish match: allow spaces, hyphens, parentheses around keywords
    // keep it simple and transparent
    if (s.includes(k)) return "tv";
  }

  // Default to movie if not explicitly TV.
  return "movie";
}

function setLibraryTypeForId(libraryId, type) {
  const id = String(libraryId);
  const t = type === "tv" || type === "movie" ? type : "unknown";
  _libraryTypeCache.set(id, t);
  return t;
}

function getLibraryTypeForId(libraryId) {
  const id = String(libraryId);
  return _libraryTypeCache.get(id) || "unknown";
}

function rememberLibraryTypeFromLibraryObject(lib) {
  const id = lib?.id;
  if (id == null) return "unknown";
  const t = classifyLibraryTypeFromName(lib?.name);
  return setLibraryTypeForId(id, t);
}

async function fetchAllGroups(api, libraryId, prefix) {
  const items = [];
  let limit = 200;
  let offset = 0;
  for (;;) {
    const res = await api.get(`/libraries/${libraryId}/groups?prefix=${encodeURIComponent(prefix)}&limit=${limit}&offset=${offset}`);
    const batch = res?.items ?? [];
    for (const it of batch) items.push(it);
    const total = res?.total ?? items.length;
    offset += batch.length;
    if (offset >= total || batch.length === 0) break;
  }
  return items;
}

// Continue Watching cache (user 1 for now; no auth yet)
let _cwCache = {
  loaded: false,
  loading: null,
  map: new Map(), // mediaId -> { position_seconds, duration_seconds, completed }
};

async function fetchAllContinueWatching(api, userId) {
  const items = [];
  let limit = 200;
  let offset = 0;
  for (;;) {
    const res = await api.get(`/users/${userId}/continue-watching?limit=${limit}&offset=${offset}`);
    const batch = res?.items ?? [];
    for (const it of batch) items.push(it);
    const total = res?.total ?? items.length;
    offset += batch.length;
    if (offset >= total || batch.length === 0) break;
  }
  return items;
}

async function ensureContinueWatchingMap(api, userId = 1) {
  if (_cwCache.loaded) return _cwCache.map;
  if (_cwCache.loading) return _cwCache.loading;

  _cwCache.loading = (async () => {
    const items = await fetchAllContinueWatching(api, userId);
    const map = new Map();
    for (const it of (items || [])) {
      const mediaId = it.media_file_id ?? it.id;
      if (mediaId == null) continue;
      map.set(String(mediaId), {
        position_seconds: Number(it.position_seconds ?? 0) || 0,
        duration_seconds: Number(it.duration_seconds ?? 0) || 0,
        completed: Boolean(it.completed ?? false),
      });
    }
    _cwCache.map = map;
    _cwCache.loaded = true;
    return map;
  })();

  return _cwCache.loading;
}

// -----------------
// Pages
// -----------------

function DashboardPage() {
  const wrap = h("div");

  wrap.appendChild(
    renderPageTitle(
      "Dashboard",
      "Admin console scaffold is live. Health is now wired to the server. Next: Libraries list."
    )
  );

  const box = h("div", {
    style: {
      padding: "12px",
      border: "1px solid #ddd",
      borderRadius: "6px",
      maxWidth: "720px",
    },
  });

  const label = h("div", { style: { fontWeight: "600", marginBottom: "6px" } }, ["Server Health"]);
  const status = h("div", {}, ["Checking /health …"]);

  box.appendChild(label);
  box.appendChild(status);
  wrap.appendChild(box);

  (async () => {
    try {
      const data = await api.get("/health");
      status.textContent = `OK: ${JSON.stringify(data)}`;
    } catch (e) {
      status.textContent = `ERROR: ${e?.message || String(e)}`;
    }
  })();


  // Continue Watching (top 10)
  const cwBox = h("div", {
    style: {
      padding: "12px",
      border: "1px solid #ddd",
      borderRadius: "6px",
      maxWidth: "960px",
      marginTop: "16px",
    },
  });

  cwBox.appendChild(h("div", { style: { fontWeight: "600", marginBottom: "6px" } }, ["Continue Watching"]));
  const cwStatus = h("div", {}, ["Loading…"]);
  cwBox.appendChild(cwStatus);

  const cwTable = h("table", { border: "1", cellpadding: "6", style: "border-collapse: collapse; width: 100%; marginTop: 8 + 'px'" });
  const cwThead = h("thead");
  const cwHeadRow = h("tr");
  for (const col of ["Poster", "Title", "Progress", "Actions"]) {
    cwHeadRow.appendChild(h("th", {}, [col]));
  }
  cwThead.appendChild(cwHeadRow);
  cwTable.appendChild(cwThead);
  const cwTbody = h("tbody");
  cwTable.appendChild(cwTbody);
  cwBox.appendChild(cwTable);

  wrap.appendChild(cwBox);

  (async () => {
    try {
      await ensureArtworkCache();
      const res = await api.get(`/users/1/continue-watching?limit=10&offset=0`);
      const items = res?.items ?? [];
      cwStatus.textContent = `Loaded ${items.length} items.`;
      cwTbody.innerHTML = "";

      if (!Array.isArray(items) || items.length === 0) {
        cwTbody.appendChild(h("tr", {}, [h("td", { colspan: "4" }, ["(nothing in progress)"])]));
        return;
      }

      for (const it of items) {
        const mediaId = it.media_file_id ?? it.id ?? "";
        const path = it.file_path ?? "";
        const rawTitle = it.title ?? "";
        const title = (rawTitle && String(rawTitle).trim()) ? String(rawTitle) : basenameNoExt(path);

        const pos = Number(it.position_seconds ?? 0) || 0;
        const dur = Number(it.duration_seconds ?? 0) || 0;
        const prog = dur > 0 ? `${formatSeconds(pos)} / ${formatSeconds(dur)}` : formatSeconds(pos);

        const tr = h("tr");
        // Poster column
        const posterUrl = getPosterUrlForMediaFileId(mediaId);
        const posterTd = h("td");
        posterTd.appendChild(
          makePosterImg(posterUrl, {
            isSet: !!posterUrl,
            onClick: () => setPosterFlowForRow({ router, row: { id: mediaId, title } }),
          })
        );
        tr.appendChild(posterTd);
        // Title column
        tr.appendChild(h("td", {}, [title]));
        tr.appendChild(h("td", {}, [prog]));

        const actions = h("td");
        const resume = h("button", {}, ["Resume"]);
        resume.disabled = !mediaId;
        resume.addEventListener("click", () => navigateToPlay(router, mediaId, pos));

        const restart = h("button", { style: { marginLeft: "6px" } }, ["Play from start"]);
        restart.disabled = !mediaId;
        restart.addEventListener("click", () => navigateToPlay(router, mediaId, 0));

        actions.appendChild(resume);
        actions.appendChild(restart);
        tr.appendChild(actions);

        cwTbody.appendChild(tr);
      }
    } catch (e) {
      cwStatus.textContent = `ERROR: ${e?.message || String(e)}`;
      cwTbody.innerHTML = "";
    }
  })();

  return wrap;
}

function SettingsPage() {
  const wrap = h("div");
  wrap.appendChild(renderPageTitle("Settings", "API keys are stored on the server."));

  let lastSettings = { tmdb_api_key: "", opensubtitles_api_key: "" };
  let tmdbDirty = false;
  let osDirty = false;

  const box = h("div", {
    style: {
      padding: "12px",
      border: "1px solid #ddd",
      borderRadius: "6px",
      maxWidth: "640px",
    },
  });

  const status = h("div", { style: { marginBottom: "10px", color: "#666" } }, ["Loading…"]);
  box.appendChild(status);

  const tmdbRow = h("div", { style: { marginBottom: "10px" } });
  tmdbRow.appendChild(h("div", { style: { fontWeight: "600", marginBottom: "4px" } }, ["TMDB API Key"]));
  const tmdbInput = h("input", { type: "password", style: "width: 100%; padding: 6px;" });
  tmdbInput.addEventListener("input", () => {
    tmdbDirty = true;
  });
  tmdbRow.appendChild(tmdbInput);
  const tmdbClear = h("button", { style: { marginTop: "6px" } }, ["Clear TMDB Key"]);
  tmdbClear.addEventListener("click", () => {
    if (!confirm("Clear the TMDB API key? This will remove it from the server.")) return;
    tmdbInput.value = "";
    tmdbDirty = true;
  });
  tmdbRow.appendChild(tmdbClear);
  box.appendChild(tmdbRow);

  const osRow = h("div", { style: { marginBottom: "10px" } });
  osRow.appendChild(h("div", { style: { fontWeight: "600", marginBottom: "4px" } }, ["OpenSubtitles API Key"]));
  const osInput = h("input", { type: "password", style: "width: 100%; padding: 6px;" });
  osInput.addEventListener("input", () => {
    osDirty = true;
  });
  osRow.appendChild(osInput);
  const osClear = h("button", { style: { marginTop: "6px" } }, ["Clear OpenSubtitles Key"]);
  osClear.addEventListener("click", () => {
    if (!confirm("Clear the OpenSubtitles API key? This will remove it from the server.")) return;
    osInput.value = "";
    osDirty = true;
  });
  osRow.appendChild(osClear);
  box.appendChild(osRow);

  const showRow = h("div", { style: { marginBottom: "10px" } });
  const showToggle = h("input", { type: "checkbox", id: "show-keys" });
  const showLabel = h("label", { for: "show-keys", style: { marginLeft: "6px" } }, ["Show keys"]);
  showToggle.addEventListener("change", () => {
    const t = showToggle.checked ? "text" : "password";
    tmdbInput.type = t;
    osInput.type = t;
  });
  showRow.appendChild(showToggle);
  showRow.appendChild(showLabel);
  box.appendChild(showRow);

  const saveBtn = h("button", {}, ["Save Settings"]);
  saveBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    saveBtn.disabled = true;
    status.textContent = "Saving…";
    try {
      const tmdbVal = String(tmdbInput.value || "").trim();
      const osVal = String(osInput.value || "").trim();
      const payload = {};
      if (tmdbVal !== lastSettings.tmdb_api_key) payload.tmdb_api_key = tmdbVal;
      if (osVal !== lastSettings.opensubtitles_api_key) payload.opensubtitles_api_key = osVal;
      if (Object.keys(payload).length === 0) {
        status.textContent = "No changes.";
        return;
      }
      await api.post("/settings", payload);
      if ("tmdb_api_key" in payload) lastSettings.tmdb_api_key = tmdbVal;
      if ("opensubtitles_api_key" in payload) lastSettings.opensubtitles_api_key = osVal;
      status.textContent = "Saved.";
    } catch (err) {
      status.textContent = `ERROR: ${err?.message || String(err)}`;
    } finally {
      saveBtn.disabled = false;
    }
  });
  box.appendChild(saveBtn);

  wrap.appendChild(box);

  (async () => {
    try {
      const res = await api.get("/settings");
      const s = res?.settings || {};
      lastSettings = {
        tmdb_api_key: s.tmdb_api_key || "",
        opensubtitles_api_key: s.opensubtitles_api_key || "",
      };
      if (!tmdbDirty) tmdbInput.value = lastSettings.tmdb_api_key;
      if (!osDirty) osInput.value = lastSettings.opensubtitles_api_key;
      tmdbDirty = false;
      osDirty = false;
      status.textContent = "Loaded.";
    } catch (err) {
      status.textContent = `ERROR: ${err?.message || String(err)}`;
    }
  })();

  return wrap;
}

function PostersPage({ router, query }) {
  const wrap = h("div");

  const libraryId = query?.libraryId ? String(query.libraryId) : "";

  const headerRow = h("div", {
    style: { display: "flex", alignItems: "center", gap: "12px", marginBottom: "10px" },
  });

  const back = h("a", { href: "#/libraries" }, ["← Back to Libraries"]);
  back.addEventListener("click", (e) => {
    e.preventDefault();
    router.navigate("/libraries");
  });
  headerRow.appendChild(back);
  wrap.appendChild(headerRow);

  // If no library selected, show a picker/list (this is the "All or select" entry point).
  if (!libraryId) {
    wrap.appendChild(
      renderPageTitle(
        "Posters",
        "Pick a library to manage posters. This is explicit and manual: you choose each TMDB match; no automatic poster selection."
      )
    );

    const status = h("div", { style: { marginBottom: "10px" } }, ["Loading libraries…"]);
    wrap.appendChild(status);

    const table = h("table", { border: "1", cellpadding: "6", style: "border-collapse: collapse; width: 100%;" });
    const thead = h("thead");
    const hr = h("tr");
    for (const col of ["ID", "Name", "Type", "Actions"]) hr.appendChild(h("th", {}, [col]));
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = h("tbody");
    table.appendChild(tbody);
    wrap.appendChild(table);

    (async () => {
      try {
        const res = await api.get("/libraries?limit=200&offset=0");
        const libs = res?.items ?? [];
        status.textContent = `Loaded ${libs.length} libraries.`;
        tbody.innerHTML = "";

        for (const lib of libs) {
          const tr = h("tr");
          const detectedType = rememberLibraryTypeFromLibraryObject(lib);

          tr.appendChild(h("td", {}, [lib.id]));
          tr.appendChild(h("td", {}, [lib.name ?? ""]));
          tr.appendChild(h("td", {}, [detectedType]));

          const actions = h("td");
          const manage = h("button", {}, ["Manage Posters"]);
          manage.addEventListener("click", () => router.navigate(`/posters?libraryId=${encodeURIComponent(String(lib.id))}`));
          actions.appendChild(manage);
          tr.appendChild(actions);

          tbody.appendChild(tr);
        }
      } catch (e) {
        status.textContent = `ERROR: ${e?.message || String(e)}`;
        tbody.innerHTML = "";
      }
    })();

    return wrap;
  }

  const libType = getLibraryTypeForId(libraryId);

  // Posters: explicit auto-fetch for THIS library + undo (the only allowed magic)
  const libAutoRow = h("div", {
    style: {
      display: "flex",
      gap: "8px",
      alignItems: "center",
      margin: "10px 0",
      flexWrap: "wrap",
    },
  });

  const libAutoBtn = h("button", {}, ["Auto Fetch Posters (This Library)"]);
  const libUndoBtn = h("button", {}, ["Undo Last Auto Fetch"]);
  const libAutoStatus = h("div", { style: { color: "#666" } }, [""]);

  libUndoBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await undoLastAutoPosterRun();
    // re-render this Posters route so indicators update
    router.navigate(window.location.hash.replace(/^#/, "") || "/");
  });

  libAutoBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const t = libType === "tv" ? "tv" : "movie";

    const ok = prompt(
      `AUTO MODE (${t})\n\nThis will set posters by picking the FIRST TMDB result that has a poster.\nOnly missing posters are filled.\nNo fallback between movie/tv types.\n\nType YES to proceed:`,
      ""
    );
    const okNorm = String(ok || "").trim().toUpperCase();
    if (okNorm !== "YES") return;

    beginAutoPosterRun(`posters:auto:${t}:library:${libraryId}`);
    const beforeCount = _lastAutoPosterRun?.changes?.length || 0;

    libAutoBtn.disabled = true;
    libUndoBtn.disabled = true;
    libAutoStatus.textContent = `Auto Fetch started for library ${libraryId} (${t})…`;

    try {
      if (t === "tv") {
        await autoFetchMissingTvPostersForLibrary({ libraryId: String(libraryId), statusEl: libAutoStatus });
      } else {
        await autoFetchMissingMoviePostersForLibrary({ libraryId: String(libraryId), statusEl: libAutoStatus });
      }

      const afterCount = _lastAutoPosterRun?.changes?.length || 0;
      const changed = Math.max(0, afterCount - beforeCount);
      libAutoStatus.textContent = `Auto Fetch complete for library ${libraryId} (${t}). Set ${changed} posters. You can Undo Last Auto Fetch.`;
      alert(`Auto Fetch complete for library ${libraryId} (${t}). Set ${changed} posters.`);
      router.navigate(window.location.hash.replace(/^#/, "") || "/");
    } catch (err) {
      libAutoStatus.textContent = `Auto Fetch ERROR for library ${libraryId}: ${err?.message || String(err)}`;
      alert(`Auto Fetch failed for library ${libraryId}.`);
    } finally {
      libAutoBtn.disabled = false;
      libUndoBtn.disabled = false;
    }
  });

  libAutoRow.appendChild(libAutoBtn);
  libAutoRow.appendChild(libUndoBtn);
  libAutoRow.appendChild(libAutoStatus);
  wrap.appendChild(libAutoRow);

  // TV libraries are show/season scoped; do not offer per-item posters here.
  if (libType === "tv") {
    wrap.appendChild(
      renderPageTitle(
        `Posters — Library ${libraryId}`,
        "TV posters are managed at show/season scope. Use the TV Shows browse view to set show and season posters."
      )
    );

    const btnRow = h("div", { style: { display: "flex", gap: "8px", alignItems: "center", marginTop: "10px" } });
    const openBrowse = h("button", {}, ["Open TV Shows Browse"]);
    openBrowse.addEventListener("click", () => router.navigate(`/libraries/${encodeURIComponent(libraryId)}/browse`));
    btnRow.appendChild(openBrowse);
    wrap.appendChild(btnRow);
    return wrap;
  }

  // Movie library posters manager (per-item, explicit).
  wrap.appendChild(
    renderPageTitle(
      `Posters — Library ${libraryId}`,
      "Movies: set posters per item. This is explicit: you run a TMDB search and pick a result. No guessing, no bulk auto-selection."
    )
  );

  let limit = 100;
  let offset = 0;
  let order = "title_asc";
  let q = "";
  let onlyMissing = true;
  // Selection + Work Queue state (explicit; manual)
  let selectedMediaIds = new Set(); // mediaId strings
  let lastVisibleItems = []; // current table view snapshot
  let queueItems = []; // snapshot used by Work Queue (view or selected subset)
  let queueMode = false;
  let queueIndex = 0;

  const controls = h("div", { style: { display: "flex", gap: "8px", alignItems: "center", marginBottom: "10px", flexWrap: "wrap" } });
  const queueBox = h("div", {
    style: {
      padding: "10px",
      border: "1px solid #ddd",
      borderRadius: "6px",
      marginBottom: "10px",
      display: "none",
    },
  });

  const missingLabel = h("label", { style: { display: "flex", gap: "6px", alignItems: "center" } });
  const missingCb = h("input", { type: "checkbox" });
  missingCb.checked = !!onlyMissing;
  missingLabel.appendChild(missingCb);
  missingLabel.appendChild(h("span", {}, ["Only missing posters"]));

  const qInput = h("input", { type: "text", placeholder: "Search title or path…", value: q, style: { width: "260px" } });

  const orderSel = h("select");
  for (const [val, label] of [
    ["title_asc", "Title A→Z"],
    ["title_desc", "Title Z→A"],
    ["added_desc", "Added (newest)"],
    ["added_asc", "Added (oldest)"],
  ]) {
    orderSel.appendChild(h("option", { value: val }, [label]));
  }
  orderSel.value = order;

  const applyBtn = h("button", {}, ["Apply"]);
  const prevBtn = h("button", {}, ["Prev"]);
  const nextBtn = h("button", {}, ["Next"]);

  controls.appendChild(missingLabel);
  controls.appendChild(qInput);
  controls.appendChild(orderSel);
  controls.appendChild(applyBtn);
  controls.appendChild(prevBtn);
  controls.appendChild(nextBtn);

  // Work Queue buttons
  const startQueueBtn = h("button", {}, ["Start Work Queue"]);
  startQueueBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();

    // Work Queue is only meaningful when showing missing posters.
    if (!onlyMissing) {
      alert("Work Queue is for missing posters. Turn on 'Only missing posters' first.");
      return;
    }

    if (!Array.isArray(lastVisibleItems) || lastVisibleItems.length === 0) {
      alert("No missing-poster items in the current view.");
      return;
    }

    queueItems = Array.isArray(lastVisibleItems) ? lastVisibleItems.slice() : [];
    queueMode = true;
    queueIndex = 0;
    renderQueue();
  });

  const exitQueueBtn = h("button", {}, ["Exit Work Queue"]);
  exitQueueBtn.disabled = true;
  exitQueueBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    queueMode = false;
    queueBox.style.display = "none";
    exitQueueBtn.disabled = true;
    startQueueBtn.disabled = false;
  });

  controls.appendChild(startQueueBtn);
  controls.appendChild(exitQueueBtn);

  const selectAllBtn = h("button", {}, ["Select All (This Page)"]);
  selectAllBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    for (const it of (lastVisibleItems || [])) {
      if (it?.mediaId) selectedMediaIds.add(String(it.mediaId));
    }
    load();
  });

  const clearSelBtn = h("button", {}, ["Clear Selection"]);
  clearSelBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    selectedMediaIds = new Set();
    load();
  });

  const startSelectedQueueBtn = h("button", {}, ["Start Queue (Selected)"]);
  startSelectedQueueBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();

    if (!onlyMissing) {
      alert("Work Queue is for missing posters. Turn on 'Only missing posters' first.");
      return;
    }

    const subset = (lastVisibleItems || []).filter((it) => it?.mediaId && selectedMediaIds.has(String(it.mediaId)));
    if (subset.length === 0) {
      alert("No selected items in the current view.");
      return;
    }

    queueItems = subset;
    queueMode = true;
    queueIndex = 0;
    renderQueue();
  });

  controls.appendChild(selectAllBtn);
  controls.appendChild(clearSelBtn);
  controls.appendChild(startSelectedQueueBtn);

  const autoFetchPageBtn = h("button", {}, ["Auto Fetch Posters (This Page)"]);
  autoFetchPageBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const ok = prompt(
      "AUTO MODE (Movies)\n\nThis will set posters by picking the FIRST TMDB result that has a poster.\nThis is the only allowed magic.\n\nType YES to proceed:",
      ""
    );
    const okNorm = String(ok || "").trim().toUpperCase();
    if (okNorm !== "YES") return;

    beginAutoPosterRun(`movies:library:${libraryId}:page:${offset}`);
    const beforeCount = _lastAutoPosterRun?.changes?.length || 0;

    autoFetchPageBtn.disabled = true;
    const itemsToDo = (lastVisibleItems || []).filter((it) => it?.mediaId && !getPosterUrlForMediaFileId(it.mediaId));
    if (itemsToDo.length === 0) {
      alert("No missing-poster items in the current view.");
      autoFetchPageBtn.disabled = false;
      return;
    }

    for (const it of itemsToDo) {
      const mediaId = String(it.mediaId);
      const prev = getPosterUrlForMediaFileId(mediaId);
      try {
        const picked = await tmdbAutoPickPoster({ tmdbType: "movie", query: it.title, size: "w342" });
        if (picked?.url) {
          await setPosterUrlForMediaFileId(mediaId, picked.url, "tmdb", picked.tmdbId);
          recordAutoPosterChange("movie", mediaId, prev, picked.url);
        }
      } catch {
        // keep going
      }
    }

    autoFetchPageBtn.disabled = false;
    load();
    const afterCount = _lastAutoPosterRun?.changes?.length || 0;
    const changed = Math.max(0, afterCount - beforeCount);
    alert(`Auto Fetch complete for this page. Set ${changed} posters. You can Undo Last Auto Fetch.`);
  });

  const autoFetchSelectedBtn = h("button", {}, ["Auto Fetch Posters (Selected)"]);
  autoFetchSelectedBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const ok = prompt(
      "AUTO MODE (Movies)\n\nThis will set posters for SELECTED items by picking the FIRST TMDB result that has a poster.\n\nType YES to proceed:",
      ""
    );
    const okNorm = String(ok || "").trim().toUpperCase();
    if (okNorm !== "YES") return;

    const subset = (lastVisibleItems || []).filter((it) => it?.mediaId && selectedMediaIds.has(String(it.mediaId)));
    if (subset.length === 0) {
      alert("No selected items in the current view.");
      return;
    }

    beginAutoPosterRun(`movies:library:${libraryId}:selected:${subset.length}`);
    const beforeCount = _lastAutoPosterRun?.changes?.length || 0;

    autoFetchSelectedBtn.disabled = true;

    for (const it of subset) {
      const mediaId = String(it.mediaId);
      const prev = getPosterUrlForMediaFileId(mediaId);
      if (prev) continue; // only fill missing
      try {
        const picked = await tmdbAutoPickPoster({ tmdbType: "movie", query: it.title, size: "w342" });
        if (picked?.url) {
          await setPosterUrlForMediaFileId(mediaId, picked.url, "tmdb", picked.tmdbId);
          recordAutoPosterChange("movie", mediaId, prev, picked.url);
        }
      } catch {
        // keep going
      }
    }

    autoFetchSelectedBtn.disabled = false;
    load();
    const afterCount = _lastAutoPosterRun?.changes?.length || 0;
    const changed = Math.max(0, afterCount - beforeCount);
    alert(`Auto Fetch complete for selected items. Set ${changed} posters. You can Undo Last Auto Fetch.`);
  });

  const undoAutoBtn = h("button", {}, ["Undo Last Auto Fetch"]);
  undoAutoBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await undoLastAutoPosterRun();
    load();
  });

  controls.appendChild(autoFetchPageBtn);
  controls.appendChild(autoFetchSelectedBtn);
  controls.appendChild(undoAutoBtn);

  wrap.appendChild(controls);
  wrap.appendChild(queueBox);

  const status = h("div", { style: { marginBottom: "10px" } }, ["Loading…"]);
  wrap.appendChild(status);

  const table = h("table", { border: "1", cellpadding: "6", style: "border-collapse: collapse; width: 100%;" });
  const thead = h("thead");
  const hr = h("tr");
  for (const col of ["Sel", "ID", "Poster", "Title", "Duration", "Path", "Actions"]) hr.appendChild(h("th", {}, [col]));
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = h("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);

  function renderQueue() {
    // Toggle button state
    queueBox.style.display = queueMode ? "block" : "none";
    exitQueueBtn.disabled = !queueMode;
    startQueueBtn.disabled = queueMode;

    if (!queueMode) return;

    queueBox.innerHTML = "";

    const total = queueItems.length;
    if (total === 0) {
      queueBox.appendChild(h("div", {}, ["No items in the queue."]));
      return;
    }

    // Clamp index
    if (queueIndex < 0) queueIndex = 0;
    if (queueIndex >= total) queueIndex = total - 1;

    const cur = queueItems[queueIndex];

    const top = h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px" } });
    top.appendChild(h("div", { style: { fontWeight: "600" } }, [`Work Queue: ${queueIndex + 1} / ${total}`]));
    top.appendChild(h("div", { style: { color: "#666" } }, ["Manual: search TMDB and pick a match. No auto selection."]));
    queueBox.appendChild(top);

    const row = h("div", { style: { display: "flex", gap: "12px", alignItems: "flex-start", marginTop: "10px" } });

    const posterUrl = getPosterUrlForMediaFileId(cur.mediaId);
    const posterCell = h("div");
    posterCell.appendChild(
      makePosterImg(posterUrl, {
        isSet: !!posterUrl,
        onClick: () => setPosterFlowForRow({ router, row: { id: cur.mediaId, title: cur.title }, tmdbType: "movie" }),
      })
    );
    row.appendChild(posterCell);

    const meta = h("div", { style: { flex: "1" } });
    meta.appendChild(h("div", { style: { fontWeight: "600" } }, [cur.title]));
    meta.appendChild(h("div", { style: { color: "#666", marginTop: "4px" } }, [`ID: ${cur.mediaId}`]));
    meta.appendChild(h("div", { style: { color: "#666", marginTop: "4px" } }, [shortenPath(cur.path || "") ]));
    row.appendChild(meta);

    const actions = h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });

    const searchSet = h("button", {}, ["Search & Set Poster"]);
    searchSet.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await setPosterFlowForRow({ router, row: { id: cur.mediaId, title: cur.title }, tmdbType: "movie" });
      // Refresh the table and queue view after setting.
      load();
      renderQueue();
    });

    const clear = h("button", {}, ["Clear Poster"]);
    clear.disabled = !getPosterUrlForMediaFileId(cur.mediaId);
    clear.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await setPosterUrlForMediaFileId(cur.mediaId, null);
      // Re-render queue (keeps index)
      renderQueue();
      // Also refresh table view
      load();
    });

    const skip = h("button", {}, ["Skip"]);
    skip.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      queueIndex = Math.min(total - 1, queueIndex + 1);
      renderQueue();
    });

    const prev = h("button", {}, ["Prev in Queue"]);
    prev.disabled = queueIndex <= 0;
    prev.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      queueIndex = Math.max(0, queueIndex - 1);
      renderQueue();
    });

    const next = h("button", {}, ["Next in Queue"]);
    next.disabled = queueIndex >= total - 1;
    next.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      queueIndex = Math.min(total - 1, queueIndex + 1);
      renderQueue();
    });

    actions.appendChild(searchSet);
    actions.appendChild(clear);
    actions.appendChild(prev);
    actions.appendChild(next);
    actions.appendChild(skip);

    row.appendChild(actions);
    queueBox.appendChild(row);

    const hint = h("div", { style: { marginTop: "8px", color: "#666" } }, [
      "Tip: After setting a poster, click Next. The table below will update as well."
    ]);
    queueBox.appendChild(hint);

    // Keep controls in sync
    startQueueBtn.disabled = queueMode;
    exitQueueBtn.disabled = !queueMode;
  }

  async function load() {
    status.textContent = "Loading…";
    tbody.innerHTML = "";
    await ensureArtworkCache();

    const params = new URLSearchParams();
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    params.set("order", order);
    if (q && q.trim()) params.set("q", q.trim());

    try {
      const res = await api.get(`/libraries/${encodeURIComponent(libraryId)}/media-files?` + params.toString());
      const items = res?.items ?? [];
      const total = res?.total ?? items.length;

      // Filter client-side for missing posters (explicit and inspectable; no schema changes).
      const visible = onlyMissing
        ? items.filter((it) => {
            const mediaId = it.id ?? it.media_file_id ?? "";
            return mediaId && !getPosterUrlForMediaFileId(mediaId);
          })
        : items;

      // Snapshot the current visible list for Work Queue.
      lastVisibleItems = (visible || []).map((it) => {
        const mediaId = it.id ?? it.media_file_id ?? "";
        const rawTitle = it.title ?? it.display_title ?? it.name ?? "";
        const path = it.file_path ?? it.path ?? "";
        const title = (rawTitle && String(rawTitle).trim()) ? String(rawTitle) : basenameNoExt(path);
        return { mediaId, title, path };
      });
      // If queue isn't active, keep queueItems aligned with the current view.
      if (!queueMode) {
        queueItems = lastVisibleItems.slice();
      }

      // If queue mode is active, keep it rendered and clamp index.
      if (queueMode) {
        if (queueIndex >= lastVisibleItems.length) queueIndex = Math.max(0, lastVisibleItems.length - 1);
        renderQueue();
      }

      const start = Math.min(offset + 1, total);
      const end = Math.min(offset + items.length, total);
      status.textContent = `Showing ${start}-${end} of ${total}. Displaying ${visible.length} rows (filter: ${onlyMissing ? "missing only" : "all"}).`;

      prevBtn.disabled = offset <= 0;
      nextBtn.disabled = offset + limit >= total;

      for (const it of visible) {
        const tr = h("tr");

        const mediaId = it.id ?? it.media_file_id ?? "";
        const rawTitle = it.title ?? it.display_title ?? it.name ?? "";
        const dur = it.duration_seconds ?? it.duration ?? "";
        const path = it.file_path ?? it.path ?? "";
        const title = (rawTitle && String(rawTitle).trim()) ? String(rawTitle) : basenameNoExt(path);
        // Display-only normalization for movie titles (no inference; reversible via tooltip).
        const displayTitle = title
          .replace(/[._]+/g, " ")
          .replace(/\s+/g, " ")
          .trim();

        // Selection checkbox (explicit user action)
        const selTd = h("td");
        const selCb = h("input", { type: "checkbox" });
        selCb.checked = !!(mediaId && selectedMediaIds.has(String(mediaId)));
        selCb.disabled = !mediaId;
        selCb.addEventListener("change", (e) => {
          if (!mediaId) return;
          const idStr = String(mediaId);
          if (e.target.checked) selectedMediaIds.add(idStr);
          else selectedMediaIds.delete(idStr);
        });
        selTd.appendChild(selCb);
        tr.appendChild(selTd);

        // ID
        tr.appendChild(h("td", {}, [mediaId]));

        const posterUrl = getPosterUrlForMediaFileId(mediaId);
        const posterTd = h("td");
        posterTd.appendChild(
          makePosterImg(posterUrl, {
            isSet: !!posterUrl,
            onClick: () => setPosterFlowForRow({ router, row: { id: mediaId, title }, tmdbType: "movie" }),
          })
        );
        tr.appendChild(posterTd);

        tr.appendChild(h("td", { title }, [displayTitle]));
        tr.appendChild(h("td", {}, [dur]));
        tr.appendChild(h("td", { title: path }, [shortenPath(path)]));

        const actions = h("td");

        const setPosterBtn = h("button", {}, ["Set Poster"]);
        setPosterBtn.disabled = !mediaId;
        setPosterBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          await setPosterFlowForRow({ router, row: { id: mediaId, title }, tmdbType: "movie" });
        });

        const clearPosterBtn = h("button", { style: { marginLeft: "6px" } }, ["Clear Poster"]);
        clearPosterBtn.disabled = !mediaId || !getPosterUrlForMediaFileId(mediaId);
        clearPosterBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!mediaId) return;
          await setPosterUrlForMediaFileId(mediaId, null);
          load();
        });

        actions.appendChild(setPosterBtn);
        actions.appendChild(clearPosterBtn);
        tr.appendChild(actions);

        tbody.appendChild(tr);
      }

      if (visible.length === 0) {
        tbody.appendChild(h("tr", {}, [h("td", { colspan: "7" }, ["(no items to show)"])]));
      }
    } catch (e) {
      status.textContent = `ERROR: ${e?.message || String(e)}`;
      prevBtn.disabled = true;
      nextBtn.disabled = true;
    }
  }

  applyBtn.addEventListener("click", () => {
    q = qInput.value;
    order = orderSel.value;
    onlyMissing = !!missingCb.checked;
    offset = 0;
    load();
  });

  qInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      q = qInput.value;
      order = orderSel.value;
      onlyMissing = !!missingCb.checked;
      offset = 0;
      load();
    }
  });

  missingCb.addEventListener("change", () => {
    onlyMissing = !!missingCb.checked;
    offset = 0;
    load();
  });

  prevBtn.addEventListener("click", () => {
    offset = Math.max(0, offset - limit);
    load();
  });

  nextBtn.addEventListener("click", () => {
    offset = offset + limit;
    load();
  });

  load();
  return wrap;
}

function LibrariesPage({ router }) {
  const wrap = h("div");
  wrap.appendChild(renderPageTitle("Libraries", "Listing libraries from GET /libraries."));

  const postersRow = h("div", { style: { marginBottom: "10px" } });
  const postersAllBtn = h("button", {}, ["Posters (All Libraries)"]);
  postersAllBtn.addEventListener("click", () => router.navigate("/posters"));
  postersRow.appendChild(postersAllBtn);
  wrap.appendChild(postersRow);

  // Selection state for bulk actions (explicit; no background)
  let selectedLibraryIds = new Set();

  const bulkRow = h("div", { style: { marginBottom: "10px", display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" } });

  const selAllBtn = h("button", {}, ["Select All"]);
  const selClearBtn = h("button", {}, ["Clear Selection"]);
  const autoSelectedBtn = h("button", {}, ["Auto Fetch Posters (Selected)"]);
  const undoAutoBtn = h("button", {}, ["Undo Last Auto Fetch"]);

  // We'll set tbody after table is created, so define here:
  let tbody = null;
  let status = null;

  selAllBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Select all currently loaded rows (populated after load)
    if (!tbody) return;
    const rows = tbody.querySelectorAll("tr[data-lib-id]");
    for (const r of rows) {
      const id = r.getAttribute("data-lib-id");
      if (id) selectedLibraryIds.add(String(id));
    }
    // update checkboxes
    for (const cb of tbody.querySelectorAll("input[data-lib-sel]") ) cb.checked = true;
  });

  selClearBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    selectedLibraryIds = new Set();
    if (!tbody) return;
    for (const cb of tbody.querySelectorAll("input[data-lib-sel]") ) cb.checked = false;
  });

  undoAutoBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await undoLastAutoPosterRun();
  });

  autoSelectedBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const ids = Array.from(selectedLibraryIds.values());
    if (ids.length === 0) {
      alert("No libraries selected.");
      return;
    }

    const ok = prompt(
      `AUTO MODE (Selected Libraries)\n\nThis will set posters by picking the FIRST TMDB result that has a poster.\nOnly missing posters are filled.\nNo fallback between movie/tv types.\n\nSelected libraries: ${ids.length}\n\nType YES to proceed:`,
      ""
    );
    const okNorm = String(ok || "").trim().toUpperCase();
    if (okNorm !== "YES") return;

    beginAutoPosterRun(`libraries:auto:selected:${ids.length}`);
    const beforeCount = _lastAutoPosterRun?.changes?.length || 0;

    autoSelectedBtn.disabled = true;
    selAllBtn.disabled = true;
    selClearBtn.disabled = true;

    try {
      // Build a quick lookup for detected types from the rendered table
      const typeById = new Map();
      if (tbody) {
        for (const r of tbody.querySelectorAll("tr[data-lib-id]") ) {
          const id = r.getAttribute("data-lib-id");
          const t = r.getAttribute("data-lib-type");
          if (id && t) typeById.set(String(id), t);
        }
      }

      let idx = 0;
      for (const libId of ids) {
        idx++;
        const t = typeById.get(String(libId)) || getLibraryTypeForId(libId) || "movie";
        if (status) status.textContent = `Auto Fetch (${t}) — library ${idx}/${ids.length}: ${libId}`;

        if (t === "tv") {
          await autoFetchMissingTvPostersForLibrary({ libraryId: libId, statusEl: status });
        } else {
          await autoFetchMissingMoviePostersForLibrary({ libraryId: libId, statusEl: status });
        }
      }

      const afterCount = _lastAutoPosterRun?.changes?.length || 0;
      const changed = Math.max(0, afterCount - beforeCount);
      if (status) status.textContent = `Auto Fetch complete for ${ids.length} libraries. Set ${changed} posters. You can Undo Last Auto Fetch.`;
      alert(`Auto Fetch complete for ${ids.length} libraries. Set ${changed} posters.`);
    } catch (err) {
      if (status) status.textContent = `Auto Fetch ERROR: ${err?.message || String(err)}`;
      alert("Auto Fetch failed during selected-libraries run.");
    } finally {
      autoSelectedBtn.disabled = false;
      selAllBtn.disabled = false;
      selClearBtn.disabled = false;
    }
  });

  bulkRow.appendChild(selAllBtn);
  bulkRow.appendChild(selClearBtn);
  bulkRow.appendChild(autoSelectedBtn);
  bulkRow.appendChild(undoAutoBtn);
  wrap.appendChild(bulkRow);

  status = h("div", { style: { marginBottom: "10px" } }, ["Loading…"]);
  wrap.appendChild(status);

  const table = h("table", { border: "1", cellpadding: "6" });
  const thead = h("thead");
  const headRow = h("tr");
  for (const col of ["Sel", "ID", "Name", "Type", "Count", "Actions"]) {
    headRow.appendChild(h("th", {}, [col]));
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  tbody = h("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);

  (async () => {
    try {
      const res = await api.get("/libraries?limit=200&offset=0");
      const items = res?.items ?? [];

      status.textContent = `Loaded ${items.length} libraries.`;
      tbody.innerHTML = "";

      for (const lib of items) {
        const tr = h("tr");
        const detectedType = rememberLibraryTypeFromLibraryObject(lib);

        // Attach metadata for bulk actions
        tr.setAttribute("data-lib-id", String(lib.id));
        tr.setAttribute("data-lib-type", String(detectedType));

        // Selection checkbox (explicit)
        const selTd = h("td");
        const selCb = h("input", { type: "checkbox" });
        selCb.setAttribute("data-lib-sel", "1");
        selCb.checked = selectedLibraryIds.has(String(lib.id));
        selCb.addEventListener("change", (e) => {
          const idStr = String(lib.id);
          if (e.target.checked) selectedLibraryIds.add(idStr);
          else selectedLibraryIds.delete(idStr);
        });
        selTd.appendChild(selCb);
        tr.appendChild(selTd);

        tr.appendChild(h("td", {}, [lib.id]));
        tr.appendChild(h("td", {}, [lib.name ?? ""]));
        tr.appendChild(h("td", {}, [detectedType]));
        tr.appendChild(h("td", {}, [lib.media_count ?? 0]));
        const openBtn = h("button", {}, ["Open"]);
        openBtn.addEventListener("click", () => router.navigate(`/libraries/${lib.id}/browse`));

        const postersBtn = h("button", { style: { marginLeft: "6px" } }, ["Posters"]);
        postersBtn.addEventListener("click", () => router.navigate(`/posters?libraryId=${encodeURIComponent(String(lib.id))}`));

        // --- Scan button (explicit, user-configured endpoint) ---
        const scanBtn = h("button", { style: { marginLeft: "6px" } }, ["Scan"]);
        scanBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();

          const libId = String(lib.id);

          if (!LIBRARY_SCAN_PATH_TEMPLATE) {
            alert(
              "Scan is not configured. Set window.__GLITCHBOX_LIBRARY_SCAN_PATH to a path template like '/libraries/{id}/scan' and reload."
            );
            return;
          }

          const ok = prompt(
            `SCAN (Library ${libId})\n\nThis will request the server to scan this library for updates.\nIt is explicit and runs only when you click.\n\nType YES to start scan:`,
            ""
          );
          const okNorm = String(ok || "").trim().toUpperCase();
          if (okNorm !== "YES") return;

          scanBtn.disabled = true;
          status.textContent = `Scan started for library ${libId}…`;

          try {
            const tmpl = String(LIBRARY_SCAN_PATH_TEMPLATE || "").trim();
            const path = tmpl.includes("{id}")
              ? tmpl.replace("{id}", encodeURIComponent(libId))
              : tmpl;

            // Default behavior: POST /scan with an explicit library_id hint.
            // Backend may ignore library_id and scan all; this avoids 404s.
            await api.post(path, { library_id: Number(libId) });
            status.textContent = `Scan requested for library ${libId}. Refreshing…`;
            // Explicit refresh: re-fetch libraries so updated titles/counts appear.
            router.navigate(window.location.hash.replace(/^#/, "") || "/");
            router.navigate("/libraries");
          } catch (err) {
            status.textContent = `Scan ERROR for library ${libId}: ${err?.message || String(err)}`;
            alert(`Scan failed for library ${libId}.`);
          } finally {
            scanBtn.disabled = false;
          }
        });
        // --- End Scan button ---

        const autoBtn = h("button", { style: { marginLeft: "6px" } }, ["Auto Fetch Posters"]);
        autoBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();

          const libId = String(lib.id);
          const t = detectedType; // "movie" | "tv"

          const ok = prompt(
            `AUTO MODE (${t})\n\nThis will set posters by picking the FIRST TMDB result that has a poster.\nOnly missing posters are filled.\nNo fallback between types.\n\nType YES to proceed:`,
            ""
          );
          const okNorm = String(ok || "").trim().toUpperCase();
          if (okNorm !== "YES") return;

          beginAutoPosterRun(`libraries:auto:${t}:library:${libId}`);
          const beforeCount = _lastAutoPosterRun?.changes?.length || 0;

          autoBtn.disabled = true;
          status.textContent = `Auto Fetch started for library ${libId} (${t})…`;

          try {
            if (t === "tv") {
              await autoFetchMissingTvPostersForLibrary({ libraryId: libId, statusEl: status });
            } else {
              await autoFetchMissingMoviePostersForLibrary({ libraryId: libId, statusEl: status });
            }
            const afterCount = _lastAutoPosterRun?.changes?.length || 0;
            const changed = Math.max(0, afterCount - beforeCount);
            status.textContent = `Auto Fetch complete for library ${libId} (${t}). Set ${changed} posters. You can Undo Last Auto Fetch.`;
            alert(`Auto Fetch complete for library ${libId} (${t}). Set ${changed} posters.`);
          } catch (err) {
            status.textContent = `Auto Fetch ERROR for library ${libId}: ${err?.message || String(err)}`;
            alert(`Auto Fetch failed for library ${libId}.`);
          } finally {
            autoBtn.disabled = false;
          }
        });

        const undoBtn = h("button", { style: { marginLeft: "6px" } }, ["Undo Last Auto Fetch"]);
        undoBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          await undoLastAutoPosterRun();
        });

        const tdActions = h("td");
        tdActions.appendChild(openBtn);
        tdActions.appendChild(postersBtn);
        tdActions.appendChild(scanBtn);
        tdActions.appendChild(autoBtn);
        tdActions.appendChild(undoBtn);
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
      }
    } catch (e) {
      status.textContent = `ERROR: ${e?.message || String(e)}`;
      tbody.innerHTML = "";
    }
  })();

  return wrap;
}

function LibraryBrowsePage({ router, libraryId, query }) {
  const id = String(libraryId);
  const groupKey = query && query.group_key ? String(query.group_key) : "";

  const wrap = h("div");

  const headerRow = h("div", {
    style: { display: "flex", alignItems: "center", gap: "12px", marginBottom: "10px" },
  });

  const back = h("a", { href: `#/libraries/${id}` }, ["← Back to Library"]);
  back.addEventListener("click", (e) => {
    e.preventDefault();
    router.navigate(`/libraries`);
  });

  headerRow.appendChild(back);
  wrap.appendChild(headerRow);

  const libType = getLibraryTypeForId(id);
  wrap.appendChild(
    renderPageTitle(
      `Browse Library ${id}`,
      `Detected library type: ${libType}. Full library listing (paged). This is separate from Recently Added.`
    )
  );

  // Posters: explicit auto-fetch (the only allowed magic) + undo (this library)
  const postersAutoRow = h("div", {
    style: {
      display: "flex",
      gap: "8px",
      alignItems: "center",
      marginBottom: "10px",
      flexWrap: "wrap",
      position: "sticky",
      top: "0",
      zIndex: "5",
      background: "#fff",
      padding: "6px 0",
    },
  });

  // --- Scan Library button (explicit, user-configured endpoint) ---
  const scanLibBtn = h("button", {}, ["Scan Library"]);
  scanLibBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const idStr = String(id);

    if (!LIBRARY_SCAN_PATH_TEMPLATE) {
      alert(
        "Scan is not configured. Set window.__GLITCHBOX_LIBRARY_SCAN_PATH to a path template like '/libraries/{id}/scan' and reload."
      );
      return;
    }

    const ok = prompt(
      `SCAN (Library ${idStr})\n\nThis will request the server to scan this library for updates.\nIt is explicit and runs only when you click.\n\nType YES to start scan:`,
      ""
    );
    const okNorm = String(ok || "").trim().toUpperCase();
    if (okNorm !== "YES") return;

    scanLibBtn.disabled = true;
    postersAutoStatus.textContent = `Scan started for library ${idStr}…`;

    try {
      const tmpl = String(LIBRARY_SCAN_PATH_TEMPLATE || "").trim();
      const path = tmpl.includes("{id}")
        ? tmpl.replace("{id}", encodeURIComponent(idStr))
        : tmpl;

      // Default behavior: POST /scan with an explicit library_id hint.
      // Backend may ignore library_id and scan all; this avoids 404s.
      await api.post(path, { library_id: Number(idStr) });
      postersAutoStatus.textContent = `Scan requested for library ${idStr}. Refreshing…`;
      router.navigate(window.location.hash.replace(/^#/, "") || "/");
      router.navigate(`/libraries/${encodeURIComponent(idStr)}/browse`);
    } catch (err) {
      postersAutoStatus.textContent = `Scan ERROR for library ${idStr}: ${err?.message || String(err)}`;
      alert(`Scan failed for library ${idStr}.`);
    } finally {
      scanLibBtn.disabled = false;
    }
  });
  // --- End Scan Library button ---

  const autoThisLibBtn = h("button", {}, ["Auto Fetch Posters (This Library)"]);
  const undoAutoBtn = h("button", {}, ["Undo Last Auto Fetch"]);
  const postersAutoStatus = h("div", { style: { color: "#666" } }, [""]);

  undoAutoBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await undoLastAutoPosterRun();
    router.navigate(window.location.hash.replace(/^#/, "") || "/");
  });

  autoThisLibBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const idStr = String(id);

    // Determine type explicitly; NO fallback between types
    let t = getLibraryTypeForId(idStr);
    if (t !== "movie" && t !== "tv") {
      const typed = prompt("Library type is unknown here. Type movie or tv (no fallback):", "");
      const v = String(typed || "").trim().toLowerCase();
      if (v !== "movie" && v !== "tv") return;
      t = v;
      setLibraryTypeForId(idStr, t);
    }

    const ok = prompt(
      `AUTO MODE (${t})\n\nThis will set posters by picking the FIRST TMDB result that has a poster.\nOnly missing posters are filled.\nNo fallback between movie/tv types.\n\nType YES to proceed:`,
      ""
    );
    const okNorm = String(ok || "").trim().toUpperCase();
    if (okNorm !== "YES") return;

    beginAutoPosterRun(`library:auto:${t}:library:${idStr}`);
    const beforeCount = _lastAutoPosterRun?.changes?.length || 0;

    autoThisLibBtn.disabled = true;
    postersAutoStatus.textContent = `Auto Fetch started for library ${idStr} (${t})…`;
    undoAutoBtn.disabled = true;

    try {
      if (t === "tv") {
        await autoFetchMissingTvPostersForLibrary({ libraryId: idStr, statusEl: postersAutoStatus });
      } else {
        await autoFetchMissingMoviePostersForLibrary({ libraryId: idStr, statusEl: postersAutoStatus });
      }

      const afterCount = _lastAutoPosterRun?.changes?.length || 0;
      const changed = Math.max(0, afterCount - beforeCount);
      postersAutoStatus.textContent = `Auto Fetch complete for library ${idStr} (${t}). Set ${changed} posters. You can Undo Last Auto Fetch.`;
      alert(`Auto Fetch complete for library ${idStr} (${t}). Set ${changed} posters.`);
      router.navigate(window.location.hash.replace(/^#/, "") || "/");
    } catch (err) {
      postersAutoStatus.textContent = `Auto Fetch ERROR for library ${idStr}: ${err?.message || String(err)}`;
      alert(`Auto Fetch failed for library ${idStr}.`);
    } finally {
      autoThisLibBtn.disabled = false;
      undoAutoBtn.disabled = false;
    }
  });

  postersAutoRow.appendChild(scanLibBtn);
  postersAutoRow.appendChild(autoThisLibBtn);
  postersAutoRow.appendChild(undoAutoBtn);
  postersAutoRow.appendChild(postersAutoStatus);
  wrap.appendChild(postersAutoRow);

  function renderFlatBrowse() {
    const flat = h("div");

    // Controls
    let limit = 100;
    let offset = 0;
    let order = "title_asc";
    let q = "";

    const controls = h("div", { style: { display: "flex", gap: "8px", alignItems: "center", marginBottom: "10px" } });

    const qInput = h("input", { type: "text", placeholder: "Search title or path…", value: q, style: { width: "260px" } });
    const orderSel = h("select");
    for (const [val, label] of [
      ["title_asc", "Title A→Z"],
      ["title_desc", "Title Z→A"],
      ["added_desc", "Added (newest)"],
      ["added_asc", "Added (oldest)"],
    ]) {
      const opt = h("option", { value: val }, [label]);
      orderSel.appendChild(opt);
    }
    orderSel.value = order;

    const applyBtn = h("button", {}, ["Apply"]);
    const prevBtn = h("button", {}, ["Prev"]);
    const nextBtn = h("button", {}, ["Next"]);

    controls.appendChild(qInput);
    controls.appendChild(orderSel);
    controls.appendChild(applyBtn);
    controls.appendChild(prevBtn);
    controls.appendChild(nextBtn);
    flat.appendChild(controls);

    const status = h("div", { style: { marginBottom: "10px" } }, ["Loading…"]);
    flat.appendChild(status);

    const table = h("table", { border: "1", cellpadding: "6", style: "border-collapse: collapse; width: 100%;" });
    const thead = h("thead");
    const headRow = h("tr");
    for (const col of ["ID", "Poster", "Title", "Duration", "Path", "Actions"]) {
      headRow.appendChild(h("th", {}, [col]));
    }
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = h("tbody");
    table.appendChild(tbody);
    flat.appendChild(table);

    async function load() {
      status.textContent = "Loading…";
      tbody.innerHTML = "";
      await ensureArtworkCache();

      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      params.set("order", order);
      if (q && q.trim()) params.set("q", q.trim());
      if (groupKey) params.set("group_key", groupKey);

      try {
        const cwMap = await ensureContinueWatchingMap(api, 1);
        const res = await api.get(`/libraries/${id}/media-files?` + params.toString());
        const items = res?.items ?? [];
        const total = res?.total ?? items.length;

        const start = Math.min(offset + 1, total);
        const end = Math.min(offset + items.length, total);
        status.textContent = `Showing ${start}-${end} of ${total}`;

        prevBtn.disabled = offset <= 0;
        nextBtn.disabled = offset + limit >= total;

        for (const it of items) {
          const tr = h("tr");

          const mediaId = it.id ?? it.media_file_id ?? "";
          const rawTitle = it.title ?? it.display_title ?? it.name ?? "";
          const dur = it.duration_seconds ?? it.duration ?? "";
          const path = it.file_path ?? it.path ?? "";
          const title = (rawTitle && String(rawTitle).trim()) ? String(rawTitle) : basenameNoExt(path);
          // Display-only normalization for movie titles (no inference; reversible via tooltip).
          const displayTitle = title
            .replace(/[._]+/g, " ")
            .replace(/\s+/g, " ")
            .trim();

          tr.appendChild(h("td", {}, [mediaId]));

          // Poster (always shows something; mapping is server-persisted)
          const posterUrl = getPosterUrlForMediaFileId(mediaId);
          const posterTd = h("td");
          const isTv = libType === "tv";
          if (isTv) {
            posterTd.appendChild(
              makePosterImg(posterUrl, {
                isSet: !!posterUrl,
                title: "TV scope: episodes inherit posters from Season → Show. Set posters at show/season level.",
              })
            );
          } else {
            posterTd.appendChild(
              makePosterImg(posterUrl, {
                isSet: !!posterUrl,
                onClick: () => setPosterFlowForRow({ router, row: { id: mediaId, title }, tmdbType: libType }),
              })
            );
          }
          tr.appendChild(posterTd);

          if (libType === "tv") {
            tr.appendChild(h("td", {}, [title]));
          } else {
            tr.appendChild(h("td", { title }, [displayTitle]));
          }
          tr.appendChild(h("td", {}, [dur]));
          tr.appendChild(h("td", { title: path }, [shortenPath(path)]));

          const actions = h("td");

          const cw = cwMap.get(String(mediaId));
          const label = cw && !cw.completed && (cw.position_seconds || 0) > 0 ? "Resume" : "Play";
          const btn = h("button", {}, [label]);
          btn.disabled = !mediaId;
          btn.addEventListener("click", () => {
            if (!mediaId) return;
            const pos = cw && !cw.completed ? (cw.position_seconds || 0) : 0;
            navigateToPlay(router, mediaId, pos);
          });

          // Scope enforcement: TV posters are show/season scoped only.
          // In flat browse mode for TV libraries, do NOT show per-item Set/Clear controls.
          actions.appendChild(btn);
          if (libType === "tv") {
            const hint = h("span", { style: { marginLeft: "6px", color: "#666" } }, ["(TV: set posters at show/season scope)"]);
            actions.appendChild(hint);
          } else {
            const setPosterBtn = h("button", { style: { marginLeft: "6px" } }, ["Set Poster"]);
            setPosterBtn.disabled = !mediaId;
            setPosterBtn.addEventListener("click", async (e) => {
              e.preventDefault();
              e.stopPropagation();
              await setPosterFlowForRow({ router, row: { id: mediaId, title }, tmdbType: libType });
            });

            const clearPosterBtn = h("button", { style: { marginLeft: "6px" } }, ["Clear Poster"]);
            clearPosterBtn.disabled = !mediaId || !getPosterUrlForMediaFileId(mediaId);
            clearPosterBtn.addEventListener("click", async (e) => {
              e.preventDefault();
              e.stopPropagation();
              if (!mediaId) return;
              await setPosterUrlForMediaFileId(mediaId, null);
              router.navigate(window.location.hash.replace(/^#/, "") || "/");
            });

            actions.appendChild(setPosterBtn);
            actions.appendChild(clearPosterBtn);
          }
          tr.appendChild(actions);

          tbody.appendChild(tr);
        }
      } catch (e) {
        status.textContent = `ERROR: ${e?.message || String(e)}`;
        prevBtn.disabled = true;
        nextBtn.disabled = true;
      }
    }

    applyBtn.addEventListener("click", () => {
      q = qInput.value;
      order = orderSel.value;
      offset = 0;
      load();
    });

    qInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        q = qInput.value;
        order = orderSel.value;
        offset = 0;
        load();
      }
    });

    prevBtn.addEventListener("click", () => {
      offset = Math.max(0, offset - limit);
      load();
    });

    nextBtn.addEventListener("click", () => {
      offset = offset + limit;
      load();
    });

    load();

    return flat;
  }

  if (groupKey) {
    wrap.appendChild(renderFlatBrowse());
    return wrap;
  }

  const tvBox = h("div");
  wrap.appendChild(tvBox);

  (async () => {
    // Try TV hierarchy first by asking for tv: group keys.
    // If none exist, fall back to flat listing.
    try {
      await ensureArtworkCache();
      const groups = await fetchAllGroups(api, id, "tv:");
      if (!Array.isArray(groups) || groups.length === 0) {
        tvBox.appendChild(renderFlatBrowse());
        return;
      }

      // Build show map from season group_keys.
      const showMap = new Map();
      for (const g of groups) {
        const gk = g?.group_key;
        const show = tvShowFromGroupKey(gk);
        const season = tvSeasonFromGroupKey(gk);
        if (!show || season == null) continue;
        const count = Number(g?.media_count ?? 0) || 0;

        if (!showMap.has(show)) {
          showMap.set(show, { show, seasons: [], totalEpisodes: 0 });
        }
        const entry = showMap.get(show);
        entry.seasons.push({ season, group_key: gk, media_count: count });
        entry.totalEpisodes += count;
      }

      const shows = Array.from(showMap.values())
        .sort((a, b) => tvDisplayShowName(a.show).localeCompare(tvDisplayShowName(b.show)));

      const status = h("div", { style: { marginBottom: "10px" } }, [`Found ${shows.length} shows.`]);
      tvBox.appendChild(status);

      const table = h("table", { border: "1", cellpadding: "6", style: "border-collapse: collapse; width: 100%;" });
      const thead = h("thead");
      const hr = h("tr");
      for (const col of ["Poster", "Show", "Seasons", "Episodes", "Actions"]) hr.appendChild(h("th", {}, [col]));
      thead.appendChild(hr);
      table.appendChild(thead);
      const tbody = h("tbody");
      table.appendChild(tbody);
      tvBox.appendChild(table);

      for (const s of shows) {
        s.seasons.sort((x, y) => x.season - y.season);

        const tr = h("tr");
        // Poster column (show-level)
        const showName = tvDisplayShowName(s.show);
        const showPosterUrl = getPosterUrlForTvShow(s.show);
        const posterTd = h("td");
        posterTd.appendChild(
          makePosterImg(showPosterUrl, {
            isSet: !!showPosterUrl,
            title: "TV scope: this is the SHOW poster. Click to change.",
            onClick: () => setPosterFlowForTvShow({ router, showSlug: s.show, showName }),
          })
        );
        tr.appendChild(posterTd);

        tr.appendChild(h("td", {}, [showName]));
        tr.appendChild(h("td", {}, [String(s.seasons.length)]));
        tr.appendChild(h("td", {}, [String(s.totalEpisodes)]));

        const actions = h("td");
        const setShowBtn = h("button", {}, ["Set Show Poster"]);
        setShowBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          await setPosterFlowForTvShow({ router, showSlug: s.show, showName });
        });
        actions.appendChild(setShowBtn);

        if (s.seasons.length > 0) {
          const seasonSelect = h("select", { style: { marginLeft: "6px" } });
          for (const sn of s.seasons) {
            const s2 = String(sn.season).padStart(2, "0");
            const opt = h("option", { value: sn.group_key, "data-season2": s2 }, [`Season ${s2}`]);
            seasonSelect.appendChild(opt);
          }
          actions.appendChild(seasonSelect);

          const openBtn = h("button", { style: { marginLeft: "6px" } }, ["Open"]);
          openBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const gk = seasonSelect.value;
            if (!gk) return;
            router.navigate(`/libraries/${encodeURIComponent(id)}/browse?group_key=${encodeURIComponent(gk)}`);
          });
          actions.appendChild(openBtn);

          const setSeasonBtn = h("button", { style: { marginLeft: "6px" } }, ["Set Season Poster"]);
          setSeasonBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const opt = seasonSelect.options[seasonSelect.selectedIndex];
            const s2 = opt ? opt.getAttribute("data-season2") : "";
            if (!s2) return;
            await setPosterFlowForTvSeason({
              router,
              showSlug: s.show,
              showName,
              season2: s2,
            });
          });
          actions.appendChild(setSeasonBtn);
        }
        tr.appendChild(actions);
        tbody.appendChild(tr);
      }
    } catch (e) {
      tvBox.appendChild(h("div", { style: { color: "red" } }, [`ERROR: ${e?.message || String(e)}`]));
    }
  })();

  return wrap;
}

function LibraryDetailPage({ router, id }) {
  const wrap = h("div");
  wrap.appendChild(renderPageTitle(`Library ${id}`));

  const back = h("a", { href: "#/libraries" }, ["← Back to Libraries"]);
  back.addEventListener("click", (e) => {
    e.preventDefault();
    router.navigate("/libraries");
  });
  wrap.appendChild(back);

  const info = h("div", { style: { marginTop: "10px" } }, ["Loading…"]);
  wrap.appendChild(info);

  (async () => {
    try {
      const lib = await api.get(`/libraries/${encodeURIComponent(id)}`);
      info.textContent = `ID: ${lib.id}, Name: ${lib.name}, Type: ${classifyLibraryTypeFromName(lib.name)}`;
    } catch (e) {
      info.textContent = `ERROR: ${e?.message || String(e)}`;
    }
  })();

  // (If there was a Scan button snippet here, it has been removed as per instructions.)

  return wrap;
}

// -----------------
// App bootstrap
// -----------------

// const router = createRouter();
  const routes = [
    { path: "/", view: () => DashboardPage() },

    { path: "/libraries", view: () => LibrariesPage({ router }) },
    { path: "/settings", view: () => SettingsPage() },

  { path: "/posters", view: (ctx = {}) =>
      PostersPage({ router, query: ctx.query || {} })
  },

  {
    path: "/libraries/:id/browse",
    view: (ctx = {}) =>
      LibraryBrowsePage({
        router,
        libraryId: ctx && ctx.params && ctx.params.id ? ctx.params.id : "",
        query: ctx.query || {},
      }),
  },
];

const router = createRouter({ routes });

function renderRoute() {
  appEl.innerHTML = "";
  appEl.appendChild(renderTopNav(router));

  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [rawPath, rawQs] = raw.split("?");
  const path = rawPath || "/";

  // Parse query string explicitly
  const query = {};
  if (rawQs) {
    const usp = new URLSearchParams(rawQs);
    for (const [k, v] of usp.entries()) query[k] = v;
  }

  const pathParts = String(path).split("/").filter(Boolean);

  // Match routes with optional ":param" segments (explicit, minimal)
  let matched = null;
  let params = {};

  for (const r of routes) {
    const routeParts = String(r.path || "").split("/").filter(Boolean);
    if (routeParts.length !== pathParts.length) continue;

    const p = {};
    let ok = true;

    for (let i = 0; i < routeParts.length; i++) {
      const rp = routeParts[i];
      const pp = pathParts[i];

      if (rp.startsWith(":")) {
        const key = rp.slice(1);
        if (!key) {
          ok = false;
          break;
        }
        p[key] = decodeURIComponent(pp);
      } else if (rp !== pp) {
        ok = false;
        break;
      }
    }

    if (ok) {
      matched = r;
      params = p;
      break;
    }
  }

  if (!matched || typeof matched.view !== "function") {
    appEl.appendChild(renderPageTitle("Not Found", `No route for ${path}`));
    return;
  }

  const view = matched.view({ params, query });
  appEl.appendChild(view);
}

// Render once on load
renderRoute();

// Re-render on hash changes (explicit, no router magic assumed)
window.addEventListener("hashchange", () => {
  renderRoute();
});

// Start router if it exposes start()
if (typeof router.start === "function") {
  router.start();
}
