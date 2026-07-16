// Click a header on any <table class="sortable"> to sort by that column;
// click again to reverse. Cells may carry data-sort with the raw value to
// sort on (e.g. "13800" for a "13,800" display); otherwise text is used.
(function () {
  document.querySelectorAll("table.sortable").forEach(function (table) {
    if (!table.tHead || !table.tBodies.length) return;
    var headers = table.tHead.rows[0].cells;
    var curCol = -1, dir = 1;

    function value(row, idx) {
      var cell = row.cells[idx];
      if (!cell) return "";
      return cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
    }

    function sortBy(idx, th) {
      dir = (curCol === idx) ? -dir : 1;
      curCol = idx;
      var tbody = table.tBodies[0];
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var av = value(a, idx), bv = value(b, idx);
        var an = parseFloat(av), bn = parseFloat(bv);
        var cmp = (!isNaN(an) && !isNaN(bn) && av !== "" && bv !== "")
          ? an - bn : String(av).localeCompare(String(bv));
        return cmp * dir;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
      Array.prototype.forEach.call(headers, function (h) {
        h.classList.remove("sort-asc", "sort-desc");
      });
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
    }

    Array.prototype.forEach.call(headers, function (th, idx) {
      if (th.classList.contains("no-sort")) return;
      th.classList.add("th-sort");
      th.tabIndex = 0;
      th.setAttribute("role", "button");
      th.addEventListener("click", function () { sortBy(idx, th); });
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(idx, th); }
      });
    });
  });
})();
