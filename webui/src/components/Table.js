export function Table({ columns, rows }) {
  const table = document.createElement("table");
  table.border = "1";
  table.cellPadding = "6";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const c of columns) {
    const th = document.createElement("th");
    th.textContent = c.header;
    hr.appendChild(th);
  }
  thead.appendChild(hr);

  const tbody = document.createElement("tbody");
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const c of columns) {
      const td = document.createElement("td");
      const v = c.cell(r);
      if (v instanceof Node) td.appendChild(v);
      else td.textContent = String(v ?? "");
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }

  table.appendChild(thead);
  table.appendChild(tbody);
  return table;
}