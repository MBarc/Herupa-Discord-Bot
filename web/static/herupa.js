// Checkbox-driven show/hide (embed fields on schedule + composer).
document.querySelectorAll("input[data-toggles]").forEach(function (box) {
  var target = document.getElementById(box.dataset.toggles);
  var sync = function () { target.hidden = !box.checked; };
  box.addEventListener("change", sync);
  sync();
});

// Live Discord-style preview on the composer page.
(function () {
  var content = document.getElementById("c-content");
  if (!content) return;
  var ids = ["c-use-embed", "c-etitle", "c-edesc", "c-ecolor", "c-efooter"];
  var el = {};
  ids.forEach(function (i) { el[i] = document.getElementById(i); });

  function render() {
    document.getElementById("p-content").textContent = content.value;
    var on = el["c-use-embed"].checked &&
             (el["c-etitle"].value.trim() || el["c-edesc"].value.trim());
    document.getElementById("p-embed").hidden = !on;
    document.getElementById("p-title").textContent = el["c-etitle"].value;
    document.getElementById("p-desc").textContent = el["c-edesc"].value;
    document.getElementById("p-footer").textContent = el["c-efooter"].value;
    document.getElementById("p-bar").style.background = el["c-ecolor"].value;
  }
  [content, el["c-use-embed"], el["c-etitle"], el["c-edesc"], el["c-ecolor"], el["c-efooter"]]
    .forEach(function (n) { n.addEventListener("input", render); n.addEventListener("change", render); });
  render();
})();
