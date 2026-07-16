// DM thread: render from embedded JSON, then poll for new messages.
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
