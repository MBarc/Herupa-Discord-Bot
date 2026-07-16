// New-message dialog: live recipient search, then compose.
(function () {
  var openBtn = document.getElementById("dm-new-btn");
  var dialog = document.getElementById("dm-new");
  if (!openBtn || !dialog) return;
  var input = document.getElementById("dm-recipient");
  var picker = document.getElementById("dm-picker");
  var hidden = document.getElementById("dm-recipient-id");
  var chosen = document.getElementById("dm-chosen");
  var sendBtn = document.getElementById("dm-new-send");
  var timer = null;

  openBtn.addEventListener("click", function () {
    hidden.value = ""; sendBtn.disabled = true;
    chosen.hidden = true; input.hidden = false; picker.innerHTML = "";
    input.value = "";
    dialog.showModal();
    input.focus();
  });

  function choose(id, name, avatar) {
    hidden.value = id;
    document.getElementById("dm-chosen-name").textContent = name;
    document.getElementById("dm-chosen-avatar").src = avatar;
    chosen.hidden = false; input.hidden = true; picker.innerHTML = "";
    sendBtn.disabled = false;
  }

  document.getElementById("dm-clear").addEventListener("click", function () {
    hidden.value = ""; sendBtn.disabled = true;
    chosen.hidden = true; input.hidden = false; input.value = ""; input.focus();
  });

  input.addEventListener("input", function () {
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) { picker.innerHTML = ""; return; }
    timer = setTimeout(function () {
      fetch("/dms/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          picker.innerHTML = "";
          rows.forEach(function (m) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "dm-pick-row";
            b.innerHTML = '<img src="' + m.avatar + '" alt="" class="dm-avatar">';
            var span = document.createElement("span");
            span.textContent = m.name;
            b.appendChild(span);
            b.addEventListener("click", function () { choose(m.id, m.name, m.avatar); });
            picker.appendChild(b);
          });
          if (!rows.length) picker.innerHTML = '<p class="empty">No match.</p>';
        }).catch(function () {});
    }, 250);
  });
})();

// Render Discord-flavored markdown to safe HTML: escape first, pull code
// spans out (so their contents aren't formatted) behind a control-char
// marker that can't occur in a message, format the rest, then restore them.
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}
function renderMarkdown(raw) {
  var MARK = String.fromCharCode(0);
  var codes = [];
  function stash(html) { codes.push(html); return MARK + (codes.length - 1) + MARK; }
  var text = escapeHtml(raw);
  text = text.replace(/```([\s\S]*?)```/g, function (_, code) {
    return stash('<pre class="md-pre">' + code.replace(/^\n/, "").replace(/\n$/, "") + "</pre>");
  });
  text = text.replace(/`([^`\n]+?)`/g, function (_, code) {
    return stash('<code class="md-code">' + code + "</code>");
  });
  text = text.replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__([\s\S]+?)__/g, "<u>$1</u>");
  text = text.replace(/~~([\s\S]+?)~~/g, "<s>$1</s>");
  text = text.replace(/\*([^*\n]+?)\*/g, "<em>$1</em>");
  text = text.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/g, "$1<em>$2</em>");
  text = text.replace(/(https?:\/\/[^\s<]+)/g,
                      '<a href="$1" target="_blank" rel="noopener">$1</a>');
  return text.replace(new RegExp(MARK + "(\\d+)" + MARK, "g"),
                      function (_, i) { return codes[+i]; });
}

// Press and hold Send to reveal a schedule option (Teams-style).
(function () {
  var btn = document.getElementById("dm-send-btn");
  var menu = document.getElementById("dm-send-menu");
  if (!btn || !menu) return;
  var held = false, timer = null;

  function startHold() {
    held = false;
    timer = setTimeout(function () { held = true; menu.hidden = false; }, 450);
  }
  function endHold() { clearTimeout(timer); }

  btn.addEventListener("mousedown", startHold);
  btn.addEventListener("mouseup", endHold);
  btn.addEventListener("mouseleave", endHold);
  btn.addEventListener("touchstart", startHold, { passive: true });
  btn.addEventListener("touchend", endHold);
  // A long-press ends in a click; swallow it so the form doesn't send.
  btn.addEventListener("click", function (e) {
    if (held) { e.preventDefault(); held = false; }
  });

  document.addEventListener("click", function (e) {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) menu.hidden = true;
  });

  var input = document.getElementById("dm-input");
  document.getElementById("dm-send-now").addEventListener("click", function () {
    menu.hidden = true;
    if (input.value.trim()) input.form.submit();
  });
  document.getElementById("dm-send-schedule").addEventListener("click", function () {
    menu.hidden = true;
    var pad = function (n) { return String(n).padStart(2, "0"); };
    var d = new Date(Date.now() + 3600000);   // default: an hour from now
    document.getElementById("dm-sched-content").value = input.value;
    document.getElementById("dm-sched-wall").value =
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
    document.getElementById("dm-sched").showModal();
    document.getElementById("dm-sched-content").focus();
  });
})();

(function () {
  var pane = document.getElementById("dm-thread");
  if (!pane) return;
  var user = pane.dataset.user;
  var lastId = "";

  function render(msgs) {
    if (!msgs.length) {
      pane.innerHTML = '<p class="empty">No messages yet. Say hi as Herupa below.</p>';
      return;
    }
    pane.innerHTML = "";
    msgs.forEach(function (m) {
      var row = document.createElement("div");
      row.className = "dm-msg " + (m.her ? "dm-her" : "dm-them");
      var bubble = document.createElement("div");
      bubble.className = "dm-bubble";
      bubble.innerHTML = renderMarkdown(m.content);
      m.attachments.forEach(function (a) {
        var link = document.createElement("a");
        link.href = a.url;
        link.textContent = "📎 " + a.name;
        link.className = "dm-attachment";
        bubble.appendChild(document.createElement("br"));
        bubble.appendChild(link);
      });
      var time = document.createElement("span");
      time.className = "dm-time";
      time.textContent = m.when;
      row.appendChild(bubble);
      row.appendChild(time);
      pane.appendChild(row);
    });
    pane.scrollTop = pane.scrollHeight;
    lastId = msgs[msgs.length - 1].id;
  }

  render(JSON.parse(document.getElementById("thread-data").textContent || "[]"));

  setInterval(function () {
    fetch("/dms/thread?u=" + encodeURIComponent(user))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (msgs) {
        if (!msgs || !msgs.length) return;
        if (msgs[msgs.length - 1].id !== lastId) render(msgs);
      })
      .catch(function () {});
  }, 5000);

  // Enter sends, Shift+Enter for a newline.
  var input = document.getElementById("dm-input");
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (input.value.trim()) input.form.submit();
    }
  });
})();
