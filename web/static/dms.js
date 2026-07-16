// DM thread: render from embedded JSON, then poll for new messages.
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
      bubble.textContent = m.content;
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
