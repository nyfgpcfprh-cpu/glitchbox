import { createApiClient } from "../api/client.js";

const api = createApiClient();

export function DashboardPage() {
  const el = document.createElement("div");
  el.innerHTML = `<h1>Dashboard</h1><div id="status">Loading...</div>`;

  (async () => {
    try {
      await api.get("/health");
      el.querySelector("#status").textContent = "Server OK";
    } catch (e) {
      el.querySelector("#status").textContent = `Server error: ${e.message}`;
    }
  })();

  return el;
}