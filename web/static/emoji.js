// Emoji support for every message box (any <textarea data-mentions>):
//   1) Discord-style :name: autocomplete — type ":jo" and pick 😂
//   2) a 😊 button in the box's corner opening a searchable picker
// Loaded right after mentions.js so the autocomplete's Enter/Tab handling
// wins over each page's own submit-on-Enter, same as mentions do.
// Both popups mount inside the open <dialog> when the box lives in one —
// showModal() makes everything outside the dialog inert, so a body-mounted
// popup would be unclickable there.
(function () {
  var CATS = [
    ["Smileys", "😀", [
      ["grin","😀"],["smiley","😃"],["smile","😄"],["grinning","😁"],["laughing","😆"],
      ["sweat_smile","😅"],["joy","😂"],["rofl","🤣"],["slight_smile","🙂"],["upside_down","🙃"],
      ["wink","😉"],["blush","😊"],["innocent","😇"],["love_face","🥰"],["heart_eyes","😍"],
      ["star_struck","🤩"],["kissing_heart","😘"],["yum","😋"],["stuck_out_tongue","😛"],
      ["zany","🤪"],["money_mouth","🤑"],["hugging","🤗"],["hand_over_mouth","🤭"],
      ["shushing","🤫"],["thinking","🤔"],["salute","🫡"],["zipper_mouth","🤐"],
      ["raised_eyebrow","🤨"],["neutral","😐"],["expressionless","😑"],["smirk","😏"],
      ["unamused","😒"],["rolling_eyes","🙄"],["grimacing","😬"],["relieved","😌"],
      ["pensive","😔"],["sleepy","😪"],["drooling","🤤"],["sleeping","😴"],["melting","🫠"],
      ["mask","😷"],["sick","🤒"],["nauseated","🤢"],["vomiting","🤮"],["sneezing","🤧"],
      ["hot_face","🥵"],["cold_face","🥶"],["woozy","🥴"],["dizzy_face","😵"],
      ["exploding_head","🤯"],["cowboy","🤠"],["partying","🥳"],["sunglasses","😎"],
      ["nerd","🤓"],["monocle","🧐"],["confused","😕"],["worried","😟"],["slight_frown","🙁"],
      ["open_mouth","😮"],["astonished","😲"],["flushed","😳"],["pleading","🥺"],
      ["fearful","😨"],["anxious_sweat","😰"],["cry","😢"],["sob","😭"],["scream","😱"],
      ["confounded","😖"],["persevere","😣"],["disappointed","😞"],["weary","😩"],
      ["tired","😫"],["yawning","🥱"],["triumph","😤"],["rage","😡"],["angry","😠"],
      ["cursing","🤬"],["smiling_imp","😈"],["imp","👿"],["skull","💀"],["poop","💩"],
      ["clown","🤡"],["ghost","👻"],["alien","👽"],["robot","🤖"]
    ]],
    ["People", "👋", [
      ["wave","👋"],["hand","✋"],["vulcan","🖖"],["ok_hand","👌"],["pinched_fingers","🤌"],
      ["victory","✌️"],["crossed_fingers","🤞"],["love_you","🤟"],["metal","🤘"],
      ["call_me","🤙"],["point_left","👈"],["point_right","👉"],["point_up","👆"],
      ["point_down","👇"],["thumbsup","👍"],["thumbsdown","👎"],["fist","✊"],["punch","👊"],
      ["clap","👏"],["raised_hands","🙌"],["open_hands","👐"],["handshake","🤝"],
      ["pray","🙏"],["writing","✍️"],["nail_polish","💅"],["muscle","💪"],["ear","👂"],
      ["brain","🧠"],["eyes","👀"],["tongue","👅"],["lips","👄"],["baby","👶"],
      ["ninja","🥷"],["prince","🤴"],["princess","👸"],["superhero","🦸"],["mage","🧙"],
      ["fairy","🧚"],["vampire","🧛"],["zombie","🧟"],["santa","🎅"],["angel","👼"],
      ["shrug","🤷"],["facepalm","🤦"],["bow","🙇"],["dancer","💃"],["dancing_man","🕺"],
      ["running","🏃"],["footprints","👣"]
    ]],
    ["Hearts", "💖", [
      ["heart","❤️"],["orange_heart","🧡"],["yellow_heart","💛"],["green_heart","💚"],
      ["blue_heart","💙"],["purple_heart","💜"],["black_heart","🖤"],["white_heart","🤍"],
      ["brown_heart","🤎"],["broken_heart","💔"],["two_hearts","💕"],["revolving_hearts","💞"],
      ["heartbeat","💓"],["growing_heart","💗"],["sparkling_heart","💖"],["cupid","💘"],
      ["gift_heart","💝"],["kiss_mark","💋"],["hundred","💯"],["anger","💢"],["boom","💥"],
      ["dizzy","💫"],["sweat_drops","💦"],["dash","💨"],["zzz","💤"],["speech_balloon","💬"],
      ["thought_balloon","💭"]
    ]],
    ["Nature", "🌸", [
      ["dog","🐶"],["cat","🐱"],["mouse","🐭"],["hamster","🐹"],["rabbit","🐰"],["fox","🦊"],
      ["bear","🐻"],["panda","🐼"],["koala","🐨"],["tiger","🐯"],["lion","🦁"],["cow","🐮"],
      ["pig","🐷"],["frog","🐸"],["monkey","🐵"],["chicken","🐔"],["penguin","🐧"],
      ["bird","🐦"],["duck","🦆"],["owl","🦉"],["bat","🦇"],["wolf","🐺"],["unicorn","🦄"],
      ["bee","🐝"],["bug","🐛"],["butterfly","🦋"],["snail","🐌"],["ladybug","🐞"],
      ["turtle","🐢"],["snake","🐍"],["octopus","🐙"],["crab","🦀"],["fish","🐟"],
      ["dolphin","🐬"],["whale","🐳"],["shark","🦈"],["dragon","🐉"],["trex","🦖"],
      ["bouquet","💐"],["cherry_blossom","🌸"],["rose","🌹"],["hibiscus","🌺"],
      ["sunflower","🌻"],["tulip","🌷"],["seedling","🌱"],["evergreen","🌲"],
      ["palm_tree","🌴"],["cactus","🌵"],["herb","🌿"],["four_leaf_clover","🍀"],
      ["maple_leaf","🍁"],["mushroom","🍄"],["sun","☀️"],["moon","🌙"],["star","⭐"],
      ["glowing_star","🌟"],["shooting_star","🌠"],["cloud","☁️"],["rainbow","🌈"],
      ["rain","🌧️"],["snowflake","❄️"],["lightning","⚡"],["fire","🔥"],["droplet","💧"],
      ["ocean","🌊"],["earth","🌍"]
    ]],
    ["Food", "🍜", [
      ["apple","🍎"],["orange","🍊"],["lemon","🍋"],["banana","🍌"],["watermelon","🍉"],
      ["grapes","🍇"],["strawberry","🍓"],["blueberries","🫐"],["cherries","🍒"],
      ["peach","🍑"],["mango","🥭"],["pineapple","🍍"],["coconut","🥥"],["kiwi","🥝"],
      ["tomato","🍅"],["avocado","🥑"],["eggplant","🍆"],["potato","🥔"],["carrot","🥕"],
      ["corn","🌽"],["hot_pepper","🌶️"],["bread","🍞"],["croissant","🥐"],["pretzel","🥨"],
      ["cheese","🧀"],["egg","🥚"],["bacon","🥓"],["pancakes","🥞"],["waffle","🧇"],
      ["fries","🍟"],["pizza","🍕"],["hotdog","🌭"],["hamburger","🍔"],["sandwich","🥪"],
      ["taco","🌮"],["burrito","🌯"],["salad","🥗"],["ramen","🍜"],["spaghetti","🍝"],
      ["curry","🍛"],["sushi","🍣"],["bento","🍱"],["rice","🍚"],["dumpling","🥟"],
      ["fortune_cookie","🥠"],["icecream","🍦"],["donut","🍩"],["cookie","🍪"],
      ["birthday_cake","🎂"],["cake","🍰"],["cupcake","🧁"],["pie","🥧"],["chocolate","🍫"],
      ["candy","🍬"],["lollipop","🍭"],["popcorn","🍿"],["coffee","☕"],["tea","🍵"],
      ["boba","🧋"],["milk","🥛"],["beer","🍺"],["beers","🍻"],["wine","🍷"],
      ["cocktail","🍸"],["tropical_drink","🍹"],["champagne","🥂"],["sake","🍶"]
    ]],
    ["Activities", "🎮", [
      ["soccer","⚽"],["basketball","🏀"],["football","🏈"],["baseball","⚾"],
      ["tennis","🎾"],["volleyball","🏐"],["pool8","🎱"],["ping_pong","🏓"],["golf","⛳"],
      ["bow_arrow","🏹"],["fishing_pole","🎣"],["boxing_glove","🥊"],["skateboard","🛹"],
      ["trophy","🏆"],["medal","🏅"],["first_place","🥇"],["second_place","🥈"],
      ["third_place","🥉"],["ticket","🎫"],["performing_arts","🎭"],["art","🎨"],
      ["clapper","🎬"],["microphone","🎤"],["headphones","🎧"],["musical_note","🎵"],
      ["notes","🎶"],["guitar","🎸"],["piano","🎹"],["trumpet","🎺"],["violin","🎻"],
      ["drum","🥁"],["saxophone","🎷"],["game_die","🎲"],["chess","♟️"],["dart","🎯"],
      ["bowling","🎳"],["video_game","🎮"],["joystick","🕹️"],["slot_machine","🎰"],
      ["puzzle","🧩"],["teddy_bear","🧸"]
    ]],
    ["Places", "🚗", [
      ["car","🚗"],["taxi","🚕"],["bus","🚌"],["race_car","🏎️"],["police_car","🚓"],
      ["ambulance","🚑"],["fire_engine","🚒"],["truck","🚚"],["tractor","🚜"],["bike","🚲"],
      ["motorcycle","🏍️"],["train","🚆"],["bullet_train","🚅"],["airplane","✈️"],
      ["rocket","🚀"],["ufo","🛸"],["helicopter","🚁"],["boat","⛵"],["ship","🚢"],
      ["anchor","⚓"],["construction","🚧"],["traffic_light","🚦"],["map","🗺️"],
      ["mountain","⛰️"],["volcano","🌋"],["camping","🏕️"],["beach","🏖️"],["island","🏝️"],
      ["house","🏠"],["office","🏢"],["hospital","🏥"],["bank","🏦"],["school","🏫"],
      ["castle","🏰"],["tokyo_tower","🗼"],["fountain","⛲"],["tent","⛺"],
      ["ferris_wheel","🎡"],["roller_coaster","🎢"],["city","🏙️"],["sunrise","🌅"],
      ["night_stars","🌃"],["bridge","🌉"]
    ]],
    ["Objects", "💡", [
      ["watch","⌚"],["phone","📱"],["laptop","💻"],["keyboard","⌨️"],["desktop","🖥️"],
      ["cd","💿"],["camera","📷"],["video_camera","📹"],["tv","📺"],["radio","📻"],
      ["alarm_clock","⏰"],["hourglass","⌛"],["battery","🔋"],["plug","🔌"],["bulb","💡"],
      ["flashlight","🔦"],["candle","🕯️"],["money_bag","💰"],["dollar","💵"],
      ["credit_card","💳"],["gem","💎"],["wrench","🔧"],["hammer","🔨"],["gear","⚙️"],
      ["magnet","🧲"],["bomb","💣"],["shield","🛡️"],["crystal_ball","🔮"],
      ["telescope","🔭"],["microscope","🔬"],["pill","💊"],["syringe","💉"],["dna","🧬"],
      ["broom","🧹"],["soap","🧼"],["key","🔑"],["lock","🔒"],["unlock","🔓"],["door","🚪"],
      ["chair","🪑"],["bed","🛏️"],["gift","🎁"],["balloon","🎈"],["tada","🎉"],
      ["confetti","🎊"],["ribbon","🎀"],["lantern","🏮"],["envelope","✉️"],["package","📦"],
      ["mailbox","📫"],["pencil","✏️"],["memo","📝"],["folder","📁"],["calendar","📅"],
      ["clipboard","📋"],["pushpin","📌"],["paperclip","📎"],["scissors","✂️"],
      ["book","📖"],["books","📚"],["newspaper","📰"],["bookmark","🔖"],["magnifier","🔍"],
      ["bell","🔔"],["no_bell","🔕"],["megaphone","📣"],["loudspeaker","📢"]
    ]],
    ["Symbols", "✅", [
      ["check","✅"],["check_mark","✔️"],["cross","❌"],["plus","➕"],["minus","➖"],
      ["question","❓"],["exclamation","❗"],["double_exclamation","‼️"],["warning","⚠️"],
      ["no_entry","⛔"],["prohibited","🚫"],["recycle","♻️"],["infinity","♾️"],
      ["arrow_right","➡️"],["arrow_left","⬅️"],["arrow_up","⬆️"],["arrow_down","⬇️"],
      ["refresh","🔄"],["play","▶️"],["pause","⏸️"],["stop_button","⏹️"],
      ["fast_forward","⏩"],["rewind","⏪"],["shuffle","🔀"],["repeat","🔁"],
      ["loud_volume","🔊"],["mute","🔇"],["red_circle","🔴"],["orange_circle","🟠"],
      ["yellow_circle","🟡"],["green_circle","🟢"],["blue_circle","🔵"],
      ["purple_circle","🟣"],["new","🆕"],["free","🆓"],["cool","🆒"],["ok_button","🆗"],
      ["sos","🆘"],["vs","🆚"]
    ]]
  ];
  var ALL = [], BY_NAME = {};
  CATS.forEach(function (c) {
    c[2].forEach(function (p) { ALL.push(p); BY_NAME[p[0]] = p[1]; });
  });

  var boxes = document.querySelectorAll("textarea[data-mentions]");
  if (!boxes.length) return;

  var RECENT_KEY = "herupaEmojiRecent";
  function recents() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; }
    catch (e) { return []; }
  }
  function remember(ch) {
    var r = recents().filter(function (c) { return c !== ch; });
    r.unshift(ch);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(r.slice(0, 16))); }
    catch (e) {}
  }

  // A popup must live inside the open <dialog> if its textarea does,
  // otherwise showModal()'s inert page makes it unclickable.
  function mount(node, ta) {
    var host = ta.closest("dialog") || document.body;
    if (node.parentNode !== host) host.appendChild(node);
  }

  function insert(ta, ch) {
    var start = ta.selectionStart, end = ta.selectionEnd;
    var before = ta.value.slice(0, start), after = ta.value.slice(end);
    ta.value = before + ch + after;
    var pos = (before + ch).length;
    ta.setSelectionRange(pos, pos);
    ta.dispatchEvent(new Event("input"));
    remember(ch);
    ta.focus();
  }

  /* ---------- 1) :name: autocomplete ---------- */
  var menu = document.createElement("div");
  menu.className = "mention-menu emoji-menu";
  menu.style.position = "fixed";
  menu.hidden = true;

  var active = null, matchStart = -1, items = [], sel = 0;

  function closeMenu() { menu.hidden = true; active = null; matchStart = -1; items = []; }

  function renderMenu() {
    menu.innerHTML = "";
    items.forEach(function (p, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mention-item" + (i === sel ? " sel" : "");
      var em = document.createElement("span");
      em.className = "em-char";
      em.textContent = p[1];
      var name = document.createElement("span");
      name.textContent = ":" + p[0] + ":";
      b.appendChild(em); b.appendChild(name);
      b.addEventListener("mousedown", function (e) { e.preventDefault(); pickEmoji(p); });
      menu.appendChild(b);
    });
    menu.hidden = !items.length;
  }

  function placeMenu(ta) {
    var r = ta.getBoundingClientRect();
    menu.style.left = r.left + "px";
    menu.style.width = Math.min(r.width, 320) + "px";
    // Open upward when the box sits near the bottom of the screen.
    if (window.innerHeight - r.bottom < 200) {
      menu.style.top = "auto";
      menu.style.bottom = (window.innerHeight - r.top + 4) + "px";
    } else {
      menu.style.bottom = "auto";
      menu.style.top = (r.bottom + 4) + "px";
    }
  }

  function pickEmoji(p) {
    var ta = active;
    var before = ta.value.slice(0, matchStart);
    var after = ta.value.slice(ta.selectionStart);
    ta.value = before + p[1] + after;
    var pos = (before + p[1]).length;
    ta.setSelectionRange(pos, pos);
    ta.dispatchEvent(new Event("input"));
    remember(p[1]);
    closeMenu();
    ta.focus();
  }

  function onInput(e) {
    var ta = e.target;
    var upto = ta.value.slice(0, ta.selectionStart);

    // Discord behavior 1: a completed ":name:" converts to the emoji the
    // moment the closing colon is typed.
    var done = /:([a-z][a-z0-9_+]{1,20}):$/i.exec(upto);
    if (done && BY_NAME[done[1].toLowerCase()]) {
      var openIdx = ta.selectionStart - done[0].length;
      if (openIdx === 0 || /[\s([{]/.test(ta.value[openIdx - 1])) {
        var ch = BY_NAME[done[1].toLowerCase()];
        var rest = ta.value.slice(ta.selectionStart);
        ta.value = ta.value.slice(0, openIdx) + ch + rest;
        var pos = openIdx + ch.length;
        ta.setSelectionRange(pos, pos);
        ta.dispatchEvent(new Event("input"));
        remember(ch);
        closeMenu();
        return;
      }
    }

    // Discord behavior 2: ":na" (2+ chars) at the cursor opens the
    // autocomplete. The colon must sit at a word boundary so times
    // ("12:30") and URLs ("https://") never trigger it.
    var m = /:([a-z][a-z0-9_+]{1,20})$/i.exec(upto);
    if (!m) { closeMenu(); return; }
    var colonIdx = ta.selectionStart - m[0].length;
    if (colonIdx > 0 && !/[\s([{]/.test(ta.value[colonIdx - 1])) { closeMenu(); return; }
    var q = m[1].toLowerCase();
    var starts = [], contains = [];
    ALL.forEach(function (p) {
      var idx = p[0].indexOf(q);
      if (idx === 0) starts.push(p);
      else if (idx > 0) contains.push(p);
    });
    items = starts.concat(contains).slice(0, 8);
    if (!items.length) { closeMenu(); return; }
    active = ta; matchStart = colonIdx; sel = 0;
    mount(menu, ta);
    placeMenu(ta);
    renderMenu();
  }

  /* ---------- 2) 😊 picker ---------- */
  var panel = document.createElement("div");
  panel.className = "emoji-panel";
  panel.hidden = true;
  var panelFor = null;

  var search = document.createElement("input");
  search.type = "text";
  search.className = "emoji-search";
  search.placeholder = "Search emojis...";
  search.setAttribute("aria-label", "Search emojis");
  panel.appendChild(search);

  var body = document.createElement("div");
  body.className = "emoji-panel-body";
  panel.appendChild(body);

  function cell(p) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "emoji-cell";
    b.textContent = p[1];
    b.title = ":" + p[0] + ":";
    b.addEventListener("mousedown", function (e) {
      e.preventDefault();
      if (panelFor) insert(panelFor, p[1]);
      // Discord behavior: shift-click keeps the picker open for more.
      if (!e.shiftKey) closePanel();
    });
    return b;
  }

  function renderPanel(filter) {
    body.innerHTML = "";
    if (!filter) {
      var rec = recents();
      if (rec.length) {
        var rh = document.createElement("div");
        rh.className = "emoji-cat";
        rh.textContent = "Frequently Used";
        body.appendChild(rh);
        var rg = document.createElement("div");
        rg.className = "emoji-grid";
        rec.forEach(function (ch) {
          var found = null;
          ALL.forEach(function (p) { if (p[1] === ch) found = p; });
          rg.appendChild(cell(found || ["emoji", ch]));
        });
        body.appendChild(rg);
      }
    }
    CATS.forEach(function (c) {
      var pairs = c[2];
      if (filter) {
        pairs = pairs.filter(function (p) { return p[0].indexOf(filter) !== -1; });
        if (!pairs.length) return;
      }
      var h = document.createElement("div");
      h.className = "emoji-cat";
      h.textContent = c[1] + " " + c[0];
      body.appendChild(h);
      var g = document.createElement("div");
      g.className = "emoji-grid";
      pairs.forEach(function (p) { g.appendChild(cell(p)); });
      body.appendChild(g);
    });
    if (!body.childNodes.length) {
      body.innerHTML = '<p class="empty">No match.</p>';
    }
  }

  function placePanel(btn) {
    var r = btn.getBoundingClientRect();
    var left = Math.max(8, Math.min(r.right - 300, window.innerWidth - 308));
    panel.style.left = left + "px";
    if (r.top > 340) {                       // open upward if there's room
      panel.style.top = "auto";
      panel.style.bottom = (window.innerHeight - r.top + 6) + "px";
    } else {
      panel.style.bottom = "auto";
      panel.style.top = (r.bottom + 6) + "px";
    }
  }

  function openPanel(btn, ta) {
    panelFor = ta;
    search.value = "";
    renderPanel("");
    mount(panel, ta);
    placePanel(btn);
    panel.hidden = false;
    search.focus();
  }
  function closePanel() { panel.hidden = true; panelFor = null; }

  search.addEventListener("input", function () {
    renderPanel(search.value.trim().toLowerCase());
  });
  search.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.stopPropagation(); closePanel(); }
  });
  document.addEventListener("mousedown", function (e) {
    if (!panel.hidden && !panel.contains(e.target) &&
        !(e.target.closest && e.target.closest(".emoji-toggle"))) closePanel();
  });

  /* ---------- wire up each box ---------- */
  boxes.forEach(function (ta) {
    // Wrap so the 😊 button can sit in the box's corner without touching
    // the surrounding layout (the wrapper takes the textarea's place).
    var wrap = document.createElement("span");
    wrap.className = "emoji-wrap";
    ta.parentNode.insertBefore(wrap, ta);
    wrap.appendChild(ta);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "emoji-toggle";
    btn.title = "Insert an emoji";
    btn.setAttribute("aria-label", "Insert an emoji");
    btn.textContent = "😊";
    btn.addEventListener("click", function () {
      if (!panel.hidden && panelFor === ta) closePanel();
      else openPanel(btn, ta);
    });
    wrap.appendChild(btn);

    ta.addEventListener("input", onInput);
    ta.addEventListener("keydown", function (e) {
      if (menu.hidden || !items.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % items.length; renderMenu(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; renderMenu(); }
      else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault(); e.stopImmediatePropagation(); pickEmoji(items[sel]);
      } else if (e.key === "Escape") { e.stopImmediatePropagation(); closeMenu(); }
    });
    ta.addEventListener("blur", function () { setTimeout(closeMenu, 150); });
  });
})();
