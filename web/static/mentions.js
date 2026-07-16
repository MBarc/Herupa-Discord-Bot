// @-mention autocomplete for any <textarea data-mentions>. Typing "@name"
// shows a member picker; choosing one inserts the real <@id> token that
// Discord turns into a ping. Loaded before page scripts so its Enter/Tab
// handler wins over a textarea's own submit-on-Enter.
(function () {
  window.MENTION_NAMES = window.MENTION_NAMES || {};   // id -> name, for previews
  var boxes = document.querySelectorAll("textarea[data-mentions]");
  if (!boxes.length) return;

  var menu = document.createElement("div");
  menu.className = "mention-menu";
  menu.hidden = true;
  document.body.appendChild(menu);

  var active = null, matchStart = -1, items = [], sel = 0, timer = null;

  function close() { menu.hidden = true; active = null; matchStart = -1; items = []; }

  function render() {
    menu.innerHTML = "";
    items.forEach(function (m, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mention-item" + (i === sel ? " sel" : "");
      var img = document.createElement("img");
      img.src = m.avatar; img.alt = "";
      var span = document.createElement("span");
      span.textContent = m.name;
      b.appendChild(img); b.appendChild(span);
      b.addEventListener("mousedown", function (e) { e.preventDefault(); pick(m); });
      menu.appendChild(b);
    });
    menu.hidden = !items.length;
  }

  function place(ta) {
    var r = ta.getBoundingClientRect();
    menu.style.left = (window.scrollX + r.left) + "px";
    menu.style.top = (window.scrollY + r.bottom + 4) + "px";
    menu.style.width = Math.min(r.width, 320) + "px";
  }

  function pick(m) {
    window.MENTION_NAMES[m.id] = m.name;
    var val = active.value;
    var token = "<@" + m.id + "> ";
    var before = val.slice(0, matchStart);
    var after = val.slice(active.selectionStart);
    active.value = before + token + after;
    var pos = (before + token).length;
    active.setSelectionRange(pos, pos);
    active.dispatchEvent(new Event("input"));
    var ta = active;
    close();
    ta.focus();
  }

  function onInput(e) {
    var ta = e.target;
    var upto = ta.value.slice(0, ta.selectionStart);
    var m = /@([\w ]{0,25})$/.exec(upto);
    if (!m) { close(); return; }
    var atIdx = ta.selectionStart - m[0].length;
    if (atIdx > 0 && !/\s/.test(ta.value[atIdx - 1])) { close(); return; }  // @ mid-word
    var q = m[1].trim();
    if (q.length < 1) { close(); return; }
    active = ta; matchStart = atIdx;
    clearTimeout(timer);
    timer = setTimeout(function () {
      fetch("/dms/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          if (active !== ta) return;
          items = rows.slice(0, 6); sel = 0;
          place(ta); render();
        }).catch(close);
    }, 160);
  }

  boxes.forEach(function (ta) {
    ta.addEventListener("input", onInput);
    ta.addEventListener("keydown", function (e) {
      if (menu.hidden || !items.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % items.length; render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; render(); }
      else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault(); e.stopImmediatePropagation(); pick(items[sel]);
      } else if (e.key === "Escape") { e.stopImmediatePropagation(); close(); }
    });
    ta.addEventListener("blur", function () { setTimeout(close, 150); });
  });
})();
