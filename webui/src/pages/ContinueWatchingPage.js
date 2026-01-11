import { PlaybackAPI } from "../api/playback.js";
import { Table } from "../components/Table.js";

export function ContinueWatchingPage({ router }) {
  const el = document.createElement("div");
  el.innerHTML = `<h1>Continue Watching</h1>`;

  const status = document.createElement("div");
  status.textContent = "Loading...";
  el.appendChild(status);

  (async () => {
    try {
      const res = await PlaybackAPI.continueWatching({ limit: 200, offset: 0 });

      const table = Table({
        columns: [
          { header: "Media File ID", cell: (r) => r.media_file_id ?? r.id ?? "" },
          { header: "Title", cell: (r) => r.title ?? "" },
          { header: "Position", cell: (r) => r.position_seconds ?? "" },
          { header: "Duration", cell: (r) => r.duration_seconds ?? "" },
          {
            header: "Actions",
            cell: (r) => {
              const id = r.media_file_id ?? r.id;
              const btn = document.createElement("button");
              btn.textContent = "Resume";
              btn.onclick = () => router.navigate(`/play/${id}?resume=1`);
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