import { LibrariesAPI } from "../api/libraries.js";
import { Table } from "../components/Table.js";

export function LibrariesPage({ router }) {
  const el = document.createElement("div");
  const header = document.createElement("h1");
  header.textContent = "Libraries";

  const status = document.createElement("div");
  status.textContent = "Loading...";

  el.appendChild(header);
  el.appendChild(status);

  (async () => {
    try {
      const res = await LibrariesAPI.list({ limit: 200, offset: 0 });

      const table = Table({
        columns: [
          { header: "ID", cell: (r) => r.id },
          { header: "Name", cell: (r) => r.name ?? "" },
          { header: "Count", cell: (r) => r.media_count ?? 0 },
          {
            header: "Actions",
            cell: (r) => {
              const btn = document.createElement("button");
              btn.textContent = "Manage";
              btn.addEventListener("click", () => router.navigate(`/libraries/${r.id}`));
              return btn;
            },
          },
        ],
        rows: res.items || [],
      });

      el.removeChild(status);
      el.appendChild(table);
    } catch (e) {
      status.textContent = `Error: ${e.message}`;
    }
  })();

  return el;
}