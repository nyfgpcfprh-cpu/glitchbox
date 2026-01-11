// Single place for HTTP calls.
// Why: keeps pages/controllers from duplicating fetch logic.

// During development, the WebUI runs on port 5173 and the backend API on port 8765.
// This is intentional for split-port dev: always call API at 127.0.0.1:8765.
const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

export function createApiClient({ baseUrl = DEFAULT_BASE_URL } = {}) {
  async function request(path, { method = "GET", json, headers = {} } = {}) {
    // If baseUrl is empty, use relative (same-origin) paths.
    const url = baseUrl ? (baseUrl + path) : path;

    const init = { method, headers: { ...headers } };
    if (json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(json);
    }

    const res = await fetch(url, init);

    // API returns JSON for both ok + error; parse defensively.
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }

    if (!res.ok) {
      const msg = data?.detail || data?.error || `HTTP ${res.status}`;
      throw new Error(msg);
    }

    return data;
  }

  return {
    get: (path) => request(path),
    post: (path, json) => request(path, { method: "POST", json }),
    patch: (path, json) => request(path, { method: "PATCH", json }),
    del: (path, json) => request(path, { method: "DELETE", json }),
  };
}