
function parseHashLocation() {
  const hash = window.location.hash || "#/";
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const [pathPart, queryPart] = raw.split("?");
  const path = pathPart || "/";
  const query = new URLSearchParams(queryPart || "");
  return { path, query };
}

function compileRoute(pathPattern) {
  const names = [];
  const regexStr = pathPattern
    .split("/")
    .map((seg) => {
      if (seg.startsWith(":")) {
        names.push(seg.slice(1));
        return "([^/]+)";
      }
      return seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { regex: new RegExp("^" + regexStr + "$"), names };
}

export function createRouter({ routes }) {
  const compiled = routes.map((r) => ({ ...r, ...compileRoute(r.path) }));
  let onRouteCb = null;

  function match(path) {
    for (const r of compiled) {
      const m = path.match(r.regex);
      if (!m) continue;
      const params = {};
      r.names.forEach((n, i) => (params[n] = m[i + 1]));
      return { render: r.render, params };
    }
    return null;
  }

  function navigate(path, { replace = false } = {}) {
    const nextHash = "#" + path;
    if (replace) window.location.replace(nextHash);
    else window.location.hash = nextHash;
  }

  function handle() {
    const { path, query } = parseHashLocation();
    const found = match(path);
    if (!found) return navigate("/", { replace: true });
    if (onRouteCb) onRouteCb({ render: found.render, params: found.params, query });
  }

  return {
    navigate,
    onRoute(cb) { onRouteCb = cb; },
    start() { window.addEventListener("hashchange", handle); handle(); },
  };
}
