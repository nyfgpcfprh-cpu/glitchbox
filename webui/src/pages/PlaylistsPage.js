import { PlaylistsAPI } from "../api/playlists.js";
import { Table } from "../components/Table.js";

export function PlaylistsPage() {
  const el = document.createElement("div");
  el.innerHTML = `<h1>Playlists</h1><div id="status">Loading...</div>`;

  (async () => {
    try {
      const res = await PlaylistsAPI.list({ limit: 200, offset: 0 });

      const table = Table({
        columns: [
          { header: "ID", cell: (r) => r.id },
          { header: "Name", cell: (r) => r.name ?? "" },
        ],
        rows: res.items || [],
      });

      el.querySelector("#status").remove();
      el.appendChild(table);
    } catch (e) {
      el.querySelector("#status").textContent = `Error: ${e.message}`;
    }
  })();

  return el;
}