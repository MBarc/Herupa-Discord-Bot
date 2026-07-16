// Month calendar for the schedule page. Click a day to compose; click an
// event chip to manage it. Holidays are computed by rule so every year works.

(function () {
  var body = document.getElementById("cal-body");
  if (!body) return;

  var EVENTS = JSON.parse(document.getElementById("sched-data").textContent || "[]");
  var bdayEl = document.getElementById("bday-data");
  var BDAYS = bdayEl ? JSON.parse(bdayEl.textContent || "[]") : [];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];

  // ---------- holidays ----------
  function nthWeekday(y, m, weekday, n) {         // m: 0-11, weekday: 0=Sun
    var first = new Date(y, m, 1).getDay();
    return 1 + ((weekday - first + 7) % 7) + (n - 1) * 7;
  }
  function lastWeekday(y, m, weekday) {
    var lastDay = new Date(y, m + 1, 0);
    return lastDay.getDate() - ((lastDay.getDay() - weekday + 7) % 7);
  }
  function easterDay(y) {                          // Anonymous Gregorian computus
    var a = y % 19, b = Math.floor(y / 100), c = y % 100;
    var d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25);
    var g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
    var i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7;
    var m = Math.floor((a + 11 * h + 22 * l) / 451);
    var month = Math.floor((h + l - 7 * m + 114) / 31);   // 3=March, 4=April
    var day = ((h + l - 7 * m + 114) % 31) + 1;
    return [month - 1, day];
  }
  // Floating holidays move each year; their key doubles as the value of the
  // "Yearly on <holiday>" repeat rule (repeat = "holiday:<key>").
  var FLOATING = {
    mlk:          { name: "MLK Day",         md: function (y) { return [0, nthWeekday(y, 0, 1, 3)]; } },
    presidents:   { name: "Presidents' Day", md: function (y) { return [1, nthWeekday(y, 1, 1, 3)]; } },
    easter:       { name: "Easter",          md: function (y) { return easterDay(y); } },
    mothersday:   { name: "Mother's Day",    md: function (y) { return [4, nthWeekday(y, 4, 0, 2)]; } },
    memorial:     { name: "Memorial Day",    md: function (y) { return [4, lastWeekday(y, 4, 1)]; } },
    fathersday:   { name: "Father's Day",    md: function (y) { return [5, nthWeekday(y, 5, 0, 3)]; } },
    labor:        { name: "Labor Day",       md: function (y) { return [8, nthWeekday(y, 8, 1, 1)]; } },
    thanksgiving: { name: "Thanksgiving",    md: function (y) { return [10, nthWeekday(y, 10, 4, 4)]; } }
  };

  function holidays(y) {
    var out = {};
    function put(m, d, name, key) { out[m + "-" + d] = { name: name, key: key || "" }; }
    put(0, 1, "New Year's Day");
    put(1, 14, "Valentine's Day");
    put(2, 17, "St. Patrick's Day");
    put(3, 1, "April Fools' Day");
    put(5, 19, "Juneteenth");
    put(6, 4, "Independence Day");
    put(9, 31, "Halloween");
    put(10, 11, "Veterans Day");
    put(11, 24, "Christmas Eve");
    put(11, 25, "Christmas");
    put(11, 31, "New Year's Eve");
    Object.keys(FLOATING).forEach(function (key) {
      var md = FLOATING[key].md(y);
      put(md[0], md[1], FLOATING[key].name, key);
    });
    return out;
  }

  function repeatLabel(repeat) {
    if (repeat && repeat.indexOf("holiday:") === 0) {
      var f = FLOATING[repeat.slice(8)];
      return f ? "every " + f.name : repeat;
    }
    return repeat;
  }

  // ---------- event projection ----------
  function wallDate(ev) {                           // date part of "YYYY-MM-DDTHH:MM"
    var p = ev.wall.split("T")[0].split("-");
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }
  function sameDay(a, b) { return a.getTime() === b.getTime(); }
  function daysInMonth(y, m) { return new Date(y, m + 1, 0).getDate(); }
  function occursOn(ev, day) {                      // day: Date at midnight
    var start = wallDate(ev);
    if (day < start) return false;
    if (ev.repeat && ev.repeat.indexOf("holiday:") === 0) {
      var f = FLOATING[ev.repeat.slice(8)];
      if (!f) return false;
      var md = f.md(day.getFullYear());
      return day.getMonth() === md[0] && day.getDate() === md[1];
    }
    switch (ev.repeat) {
      case "daily":   return true;
      case "weekly":  return day.getDay() === start.getDay();
      case "monthly":
        var clamped = Math.min(start.getDate(), daysInMonth(day.getFullYear(), day.getMonth()));
        return day.getDate() === clamped;
      case "yearly":
        if (day.getMonth() !== start.getMonth()) return false;
        var c = Math.min(start.getDate(), daysInMonth(day.getFullYear(), day.getMonth()));
        return day.getDate() === c;
      default:        return sameDay(day, start);
    }
  }

  // ---------- render ----------
  var now = new Date();
  var view = { y: now.getFullYear(), m: now.getMonth() };

  function render() {
    document.getElementById("cal-title").textContent = MONTHS[view.m] + " " + view.y;
    var holi = holidays(view.y);
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var firstDow = new Date(view.y, view.m, 1).getDay();
    var gridStart = new Date(view.y, view.m, 1 - firstDow);
    body.innerHTML = "";

    for (var i = 0; i < 42; i++) {
      var day = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
      var inMonth = day.getMonth() === view.m;
      var cell = document.createElement("div");
      cell.className = "cal-cell" + (inMonth ? "" : " cal-dim") +
                       (sameDay(day, today) ? " cal-today" : "");
      cell.setAttribute("role", "button");
      cell.tabIndex = 0;
      cell.dataset.date = day.getFullYear() + "-" +
        String(day.getMonth() + 1).padStart(2, "0") + "-" +
        String(day.getDate()).padStart(2, "0");

      var num = document.createElement("span");
      num.className = "cal-num";
      num.textContent = day.getDate();
      cell.appendChild(num);

      var hol = inMonth ? holi[day.getMonth() + "-" + day.getDate()] : null;
      if (hol) {
        var h = document.createElement("span");
        h.className = "chip chip-holiday";
        h.textContent = hol.name;
        h.title = hol.name;
        cell.appendChild(h);
        cell.dataset.holiday = hol.name;
        cell.dataset.holidayKey = hol.key;
      }

      if (inMonth) {
        BDAYS.filter(function (b) {
          return b.month === day.getMonth() + 1 && b.day === day.getDate();
        }).forEach(function (b) {
          var bc = document.createElement("span");
          bc.className = "chip chip-birthday";
          bc.textContent = "🎂 " + b.name;
          bc.title = b.name + "'s birthday";
          cell.appendChild(bc);
        });
      }

      var todays = EVENTS.filter(function (ev) { return occursOn(ev, day); });
      todays.slice(0, 3).forEach(function (ev) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip chip-event" + (ev.enabled ? "" : " chip-off");
        chip.textContent = ev.name;
        chip.title = ev.name + " · " + ev.channel;
        chip.dataset.eventId = ev.id;
        cell.appendChild(chip);
      });
      if (todays.length > 3) {
        var more = document.createElement("span");
        more.className = "cal-more";
        more.textContent = "+" + (todays.length - 3) + " more";
        cell.appendChild(more);
      }
      body.appendChild(cell);
    }
  }

  // ---------- interactions ----------
  var compose = document.getElementById("compose");
  var manage = document.getElementById("manage");

  function openCompose(dateStr, holidayName, holidayKey) {
    var d = dateStr.split("-");
    var pretty = new Date(+d[0], +d[1] - 1, +d[2]).toDateString();
    document.getElementById("compose-title").textContent = "Schedule for " + pretty;
    document.getElementById("compose-holiday").textContent = holidayName ? "🌸 " + holidayName : "";
    document.getElementById("s-wall").value = dateStr + "T09:00";
    // Floating holidays get a rule-based repeat so next year lands on the
    // holiday, not on this year's date.
    var sel = document.getElementById("s-repeat");
    var injected = document.getElementById("s-repeat-holiday");
    if (injected) injected.remove();
    if (holidayKey) {
      var opt = document.createElement("option");
      opt.id = "s-repeat-holiday";
      opt.value = "holiday:" + holidayKey;
      opt.textContent = "Yearly on " + holidayName;
      sel.appendChild(opt);
    }
    sel.value = "none";
    compose.showModal();
    document.getElementById("s-name").focus();
  }

  function openManage(id) {
    var ev = EVENTS.find(function (e) { return e.id === id; });
    if (!ev) return;
    document.getElementById("manage-title").textContent = ev.name;
    document.getElementById("manage-meta").textContent =
      ev.channel + " · repeats " + repeatLabel(ev.repeat) + " · " +
      (ev.enabled ? ("next " + ev.when) : (ev.last ? "sent " + ev.last : "paused"));
    document.getElementById("manage-content").textContent = ev.content || "(embed only)";
    document.getElementById("manage-toggle-id").value = id;
    document.getElementById("manage-delete-id").value = id;
    document.getElementById("manage-toggle-btn").textContent = ev.enabled ? "Pause" : "Enable";
    manage.showModal();
  }

  body.addEventListener("click", function (e) {
    var chip = e.target.closest(".chip-event");
    if (chip) { openManage(chip.dataset.eventId); return; }
    var cell = e.target.closest(".cal-cell");
    if (cell) openCompose(cell.dataset.date, cell.dataset.holiday, cell.dataset.holidayKey);
  });
  body.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var cell = e.target.closest(".cal-cell");
    if (cell) { e.preventDefault(); openCompose(cell.dataset.date, cell.dataset.holiday, cell.dataset.holidayKey); }
  });

  document.querySelectorAll("[data-closes]").forEach(function (b) {
    b.addEventListener("click", function () {
      document.getElementById(b.dataset.closes).close();
    });
  });

  document.getElementById("cal-prev").addEventListener("click", function () {
    view.m--; if (view.m < 0) { view.m = 11; view.y--; } render();
  });
  document.getElementById("cal-next").addEventListener("click", function () {
    view.m++; if (view.m > 11) { view.m = 0; view.y++; } render();
  });
  document.getElementById("cal-today").addEventListener("click", function () {
    view.y = now.getFullYear(); view.m = now.getMonth(); render();
  });

  render();
})();
