import { LibrariesAPI } from "../api/libraries.js";
import { Table } from "../components/Table.js";

export function LibraryDetailPage({ params, router }) {
  const libraryId = params.id;

  const el = document.createElement("div");
  el.innerHTML = `<h1>Library ${libraryId}</h1>`;

  const actions = document.createElement("div");
  actions.style.display = "flex";
  actions.style.gap = "8px";
  actions.style.marginBottom = "12px";

  const back = document.createElement("button");
  back.textContent = "Back";
  back.onclick = () => router.navigate("/libraries");

  const scan = document.createElement("button");
  scan.textContent = "Scan (simple)";
  scan.onclick = async () => {
    scan.disabled = true;
    scan.textContent = "Scanning...";
    try {
      await LibrariesAPI.scan({ engine: "simple", dry_run: false });
      scan.textContent = "Scan complete";
    } catch (e) {
      scan.textContent = `Scan failed: ${e.message}`;
    } finally {
      setTimeout(() => {
        scan.disabled = false;
        scan.textContent = "Scan (simple)";
      }, 1000);
    }
  };

  actions.appendChild(back);
  actions.appendChild(scan);
  el.appendChild(actions);

  const rootsStatus = document.createElement("div");
  rootsStatus.textContent = "Loading roots...";
  el.appendChild(rootsStatus);

  (async () => {
    try {
      const roots = await LibrariesAPI.roots(libraryId, { limit: 200, offset: 0 });

      const table = Table({
        columns: [
          { header: "Root ID", cell: (r) => r.id },
          { header: "Path", cell: (r) => r.root_path },
          { header: "Recursive", cell: (r) => String(!!r.recursive) },
          {
            header: "Actions",
            cell: (r) => {
              const btn = document.createElement("button");
              btn.textContent = "Remove";
              btn.onclick = async () => {
                btn.disabled = true;
                try {
                  await LibrariesAPI.removeRoot(r.id);
                  router.navigate(`/libraries/${libraryId}`, { replace: true });
                } catch (e) {
                  btn.disabled = false;
                  alert(e.message);
                }
              };
              return btn;
            },
          },
        ],
        rows: roots.items || [],
      });

      el.removeChild(rootsStatus);
      el.appendChild(document.createElement("h2")).textContent = "Roots";
      el.appendChild(table);
    } catch (e) {
      rootsStatus.textContent = `Error: ${e.message}`;
    }
  })();

  return el;
}