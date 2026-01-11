export function TopNav({ router }) {
  const el = document.createElement("div");
  el.style.display = "flex";
  el.style.gap = "12px";
  el.style.marginBottom = "16px";

  const links = [
    ["Dashboard", "/"],
    ["Libraries", "/libraries"],
    ["Continue Watching", "/continue"],
    ["Playlists", "/playlists"],
  ];

  for (const [label, path] of links) {
    const a = document.createElement("a");
    a.href = "#" + path;
    a.textContent = label;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      router.navigate(path);
    });
    el.appendChild(a);
  }

  return el;
}