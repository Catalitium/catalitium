(function () {
  var form = document.getElementById("troy-upload-form");
  if (!form) return;
  document.body.classList.add("troy-carl-page");

  var uploadBtn = document.getElementById("troy-upload-btn");
  var fileInput = document.getElementById("troy-file-input");
  var textFallback = document.getElementById("troy-text-fallback");
  var errorEl = document.getElementById("troy-upload-error");
  var uploadHero = document.getElementById("troy-upload-hero");
  var uploadLoading = document.getElementById("troy-upload-loading");
  var uploadLoadingStatus = document.getElementById("troy-upload-loading-status");
  var workspace = document.getElementById("troy-workspace");
  var terminal = document.getElementById("troy-terminal");
  var terminalStatus = document.getElementById("troy-terminal-status");
  var chatForm = document.getElementById("troy-chat-form");
  var chatInput = document.getElementById("troy-chat-input");
  var chatLog = document.getElementById("troy-chat-log");
  var chatChips = document.getElementById("troy-chat-chips");
  var apiCta = document.getElementById("carl-api-cta");
  var chatSubmit = document.getElementById("troy-chat-submit");

  var analysisState = null;
  var terminalTimer = null;
  var loadingStatusTimer = null;
  var MIN_ANALYZE_MS = 3600;
  var LOADING_STATUS_MS = 1080;
  var LOADING_STEPS = [
    "Preparing your workspace…",
    "Reading layout, structure, and section flow…",
    "Mapping skills, scope, and evidence signals…",
    "Scoring ATS alignment and keyword fit…",
    "Weaving narrative, risks, and quick wins…",
    "Composing your live dashboard…",
  ];
  var REVEAL_BASE_DELAY_MS = 140;
  var REVEAL_STAGGER_MS = 240;
  var METER_START_OFFSET_MS = 700;
  var CHAT_START_OFFSET_MS = 1220;
  var METER_ANIMATION_MS = 1900;
  var ATS_ANIMATION_MS = 2050;
  var TERMINAL_BASE_MS = 360;
  var TERMINAL_VARIANCE_MS = 130;
  var ROW_STAGGER_DOCUMENT_MS = 135;
  var ROW_STAGGER_ACTION_MS = 155;
  var ROW_STAGGER_SKILL_MS = 120;

  function csrfToken() {
    var field = form.querySelector('input[name="csrf_token"]');
    return field && field.value ? String(field.value).trim() : "";
  }

  function setUploadLoading(on) {
    if (!uploadBtn) return;
    uploadBtn.disabled = !!on;
    uploadBtn.textContent = on ? "Running analysis…" : "Analyze CV";
  }

  function delay(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function clearLoadingStatusTimer() {
    if (loadingStatusTimer) {
      clearInterval(loadingStatusTimer);
      loadingStatusTimer = null;
    }
  }

  function startUploadPremiumLoading() {
    if (!uploadLoading) return;
    clearLoadingStatusTimer();
    uploadLoading.setAttribute("aria-busy", "true");
    uploadLoading.classList.remove("is-leaving");
    var step = 0;
    if (uploadLoadingStatus) uploadLoadingStatus.textContent = LOADING_STEPS[0];
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        uploadLoading.classList.add("is-visible");
      });
    });
    loadingStatusTimer = setInterval(function () {
      step = (step + 1) % LOADING_STEPS.length;
      if (uploadLoadingStatus) uploadLoadingStatus.textContent = LOADING_STEPS[step];
    }, LOADING_STATUS_MS);
  }

  function hideUploadPremiumLoading(transitionMs, thenFn) {
    clearLoadingStatusTimer();
    if (!uploadLoading) {
      if (thenFn) thenFn();
      return;
    }
    uploadLoading.classList.remove("is-visible");
    uploadLoading.classList.add("is-leaving");
    uploadLoading.setAttribute("aria-busy", "false");
    setTimeout(function () {
      uploadLoading.classList.remove("is-leaving");
      if (thenFn) thenFn();
    }, transitionMs);
  }

  function setError(message) {
    if (!errorEl) return;
    if (!message) {
      errorEl.classList.add("hidden");
      errorEl.textContent = "";
      return;
    }
    errorEl.textContent = message;
    errorEl.classList.remove("hidden");
  }

  function safeList(items, fallback) {
    return Array.isArray(items) && items.length ? items : fallback;
  }

  function setGauge(wrapEl, valEl, pct) {
    if (!wrapEl) return;
    var p = Math.max(0, Math.min(100, Number(pct) || 0));
    var deg = p * 3.6;
    var color = p >= 55 ? "#00BFFF" : "#1A73E8";
    wrapEl.style.background =
      "conic-gradient(from -90deg, " + color + " 0deg, " + color + " " + deg + "deg, #2a2a2a " + deg + "deg)";
    if (valEl) valEl.textContent = String(Math.round(p));
  }

  function easeInOutCubic(t) {
    if (t < 0.5) return 4 * t * t * t;
    return 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function animateGaugeTo(wrapEl, valEl, targetPct, durationMs, done) {
    if (!wrapEl) {
      if (done) done();
      return;
    }
    var target = Math.max(0, Math.min(100, Number(targetPct) || 0));
    var start = performance.now();
    function frame(now) {
      var t = Math.min(1, (now - start) / durationMs);
      var eased = easeInOutCubic(t);
      setGauge(wrapEl, valEl, target * eased);
      if (t < 1) requestAnimationFrame(frame);
      else if (done) done();
    }
    requestAnimationFrame(frame);
  }

  function animateNumberEl(el, from, to, durationMs, done) {
    if (!el) {
      if (done) done();
      return;
    }
    var a = Math.round(Number(from) || 0);
    var b = Math.round(Number(to) || 0);
    var start = performance.now();
    function frame(now) {
      var t = Math.min(1, (now - start) / durationMs);
      var eased = easeInOutCubic(t);
      var val = Math.round(a + (b - a) * eased);
      el.textContent = String(val);
      if (t < 1) requestAnimationFrame(frame);
      else if (done) done();
    }
    requestAnimationFrame(frame);
  }

  function renderList(id, items, formatter) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = "";
    var list = safeList(items, []);
    if (!list.length) {
      el.innerHTML = '<li class="text-[#6B7280] text-xs">No data yet.</li>';
      return;
    }
    list.forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML = formatter(item);
      el.appendChild(li);
    });
  }

  function renderDocuments(docs) {
    var root = document.getElementById("troy-documents");
    if (!root) return;
    root.innerHTML = "";
    var list = safeList(docs, []);
    if (!list.length) {
      root.innerHTML = '<li class="text-xs text-[#6B7280]">No documents.</li>';
      return;
    }
    list.forEach(function (d, i) {
      var li = document.createElement("li");
      li.className =
        "carl-animate-row flex cursor-default items-center gap-3 rounded-lg border border-white/10 bg-[#0f1c3a]/65 px-3 py-2.5 transition hover:border-[#18A7EC]/45";
      li.style.animationDelay = i * ROW_STAGGER_DOCUMENT_MS + "ms";
      var badge =
        d.badge ?
          '<span class="shrink-0 rounded bg-[#18A7EC]/18 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-[#00BFFF]">' +
          escapeHtml(d.badge) +
          "</span>" :
          "";
      li.innerHTML =
        '<span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#18A7EC]/18 text-[#18A7EC]">' +
        '<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg></span>' +
        '<div class="min-w-0 flex-1">' +
        '<p class="truncate text-sm font-medium text-white">' +
        escapeHtml(d.title || "") +
        "</p>" +
        '<p class="truncate text-xs text-[#6B7280]">' +
        escapeHtml(d.subtitle || "") +
        "</p></div>" +
        badge +
        '<span class="text-[#6B7280]">›</span>';
      root.appendChild(li);
    });
  }

  function renderActions(actions) {
    var root = document.getElementById("troy-actions");
    if (!root) return;
    root.innerHTML = "";
    var list = safeList(actions, []);
    if (!list.length) {
      root.innerHTML = '<p class="text-xs text-[#6B7280]">No actions.</p>';
      return;
    }
    list.forEach(function (a, i) {
      var det = document.createElement("details");
      det.className =
        "carl-animate-row troy-action-details group rounded-lg border border-white/10 bg-[#0f1c3a]/65 open:border-[#18A7EC]/40";
      det.style.animationDelay = i * ROW_STAGGER_ACTION_MS + "ms";
      det.open = i === 0;
      det.innerHTML =
        '<summary class="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 [&::-webkit-details-marker]:hidden">' +
        '<span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#18A7EC]/18 text-[#00BFFF]">' +
        (i === 0 ?
          '<svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249z"/></svg>' :
          '<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>') +
        "</span>" +
        '<div class="min-w-0 flex-1">' +
        '<p class="text-sm font-medium text-white">' +
        escapeHtml(a.title || "") +
        "</p>" +
        '<p class="truncate text-xs text-[#9CA3AF]">' +
        escapeHtml(a.subtitle || "") +
        "</p></div>" +
        '<svg class="troy-chevron h-4 w-4 shrink-0 text-[#6B7280] transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>' +
        "</summary>" +
        '<p class="border-t border-white/5 px-3 py-2 text-xs leading-relaxed text-[#9CA3AF]">' +
        escapeHtml(a.detail || "") +
        "</p>";
      root.appendChild(det);
    });
  }

  function renderSkills(skills) {
    var root = document.getElementById("troy-skills");
    if (!root) return;
    root.innerHTML = "";
    var list = safeList(skills, []);
    if (!list.length) {
      root.innerHTML = '<p class="text-xs text-[#6B7280]">No skills extracted.</p>';
      return;
    }
    list.forEach(function (item, i) {
      var score = Number(item.score || 0);
      var row = document.createElement("div");
      row.className = "carl-animate-row space-y-1.5";
      row.style.animationDelay = i * ROW_STAGGER_SKILL_MS + "ms";
      row.innerHTML =
        '<div class="flex items-center justify-between text-xs">' +
        '<span class="font-medium text-[#E5E5E5]">' +
        escapeHtml(item.skill || "Skill") +
        "</span>" +
        '<span class="tabular-nums text-[#18A7EC]">' +
        score +
        "</span></div>" +
        '<div class="h-1.5 overflow-hidden rounded-full bg-[#111]">' +
        '<div class="h-full rounded-full bg-gradient-to-r from-[#1A73E8] via-[#18A7EC] to-[#00BFFF]" style="width:' +
        Math.min(100, Math.max(0, score)) +
        '%"></div></div>';
      root.appendChild(row);
    });
  }

  function vitalClass(v) {
    var n = Number(v) || 0;
    return n >= 60 ? "text-[#00BFFF]" : "text-[#1A73E8]";
  }

  function renderOverview(overview, skipMeters) {
    setText("troy-headline", overview.headline || "Analysis complete");
    setText("troy-fit-summary", overview.fitSummary || "");
    var personaLine = (overview.persona || "—") + " · " + (overview.level || "—");
    setText("troy-persona-line", personaLine);
    setText("troy-level", overview.level || "—");
    setText("troy-confidence", overview.confidence ? overview.confidence + "%" : "—");
    setText("troy-word-count", overview.wordCount != null ? String(overview.wordCount) : "—");

    if (skipMeters) return;

    var scores = overview.signalScores || {};
    var sStruct = scores.structure;
    var sKey = scores.keywords;
    var sImpact = scores.impact;
    var sNarr = scores.narrative;

    setGauge(document.getElementById("troy-gauge-structure"), document.getElementById("troy-gauge-structure-val"), sStruct);
    setGauge(document.getElementById("troy-gauge-keywords"), document.getElementById("troy-gauge-keywords-val"), sKey);
    setGauge(document.getElementById("troy-gauge-impact"), document.getElementById("troy-gauge-impact-val"), sImpact);

    setVital("troy-vital-structure", sStruct);
    setVital("troy-vital-keywords", sKey);
    setVital("troy-vital-impact", sImpact);
    setVital("troy-vital-narrative", sNarr);

    var premium = overview.premiumSignals || {};
    setMetric("troy-metric-leadership", premium.leadership);
    setMetric("troy-metric-role-match", premium.roleMatch);
    setMetric("troy-metric-evidence", premium.evidenceDensity);
  }

  function resetDashboardMeters() {
    setGauge(document.getElementById("troy-gauge-structure"), document.getElementById("troy-gauge-structure-val"), 0);
    setGauge(document.getElementById("troy-gauge-keywords"), document.getElementById("troy-gauge-keywords-val"), 0);
    setGauge(document.getElementById("troy-gauge-impact"), document.getElementById("troy-gauge-impact-val"), 0);
    setText("troy-ats-score", "0");
    ["troy-vital-structure", "troy-vital-keywords", "troy-vital-impact", "troy-vital-narrative"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.textContent = "0";
      el.className = "mt-1 text-lg font-semibold tabular-nums text-[#5c7caf]";
    });
    ["troy-metric-leadership", "troy-metric-role-match", "troy-metric-evidence"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.textContent = "0";
    });
  }

  function animateDashboardMeters(overview, ats) {
    var scores = (overview && overview.signalScores) || {};
    var premium = (overview && overview.premiumSignals) || {};
    var atsScore = Math.round(Number((ats && ats.score) || 0));
    var dur = METER_ANIMATION_MS;

    animateGaugeTo(
      document.getElementById("troy-gauge-structure"),
      document.getElementById("troy-gauge-structure-val"),
      scores.structure,
      dur
    );
    animateGaugeTo(
      document.getElementById("troy-gauge-keywords"),
      document.getElementById("troy-gauge-keywords-val"),
      scores.keywords,
      dur
    );
    animateGaugeTo(
      document.getElementById("troy-gauge-impact"),
      document.getElementById("troy-gauge-impact-val"),
      scores.impact,
      dur
    );

    var elAts = document.getElementById("troy-ats-score");
    animateNumberEl(elAts, 0, atsScore, ATS_ANIMATION_MS);

    animateNumberEl(document.getElementById("troy-vital-structure"), 0, scores.structure, dur, function () {
      setVital("troy-vital-structure", scores.structure);
    });
    animateNumberEl(document.getElementById("troy-vital-keywords"), 0, scores.keywords, dur, function () {
      setVital("troy-vital-keywords", scores.keywords);
    });
    animateNumberEl(document.getElementById("troy-vital-impact"), 0, scores.impact, dur, function () {
      setVital("troy-vital-impact", scores.impact);
    });
    animateNumberEl(document.getElementById("troy-vital-narrative"), 0, scores.narrative, dur, function () {
      setVital("troy-vital-narrative", scores.narrative);
    });

    animateNumberEl(document.getElementById("troy-metric-leadership"), 0, premium.leadership, dur);
    animateNumberEl(document.getElementById("troy-metric-role-match"), 0, premium.roleMatch, dur);
    animateNumberEl(document.getElementById("troy-metric-evidence"), 0, premium.evidenceDensity, dur);
  }

  function setVital(id, v) {
    var el = document.getElementById(id);
    if (!el) return;
    var n = Math.round(Number(v) || 0);
    el.textContent = String(n);
    el.className = "mt-1 text-lg font-semibold tabular-nums " + vitalClass(n);
  }

  function setMetric(id, v) {
    var el = document.getElementById(id);
    if (!el) return;
    var n = Math.round(Number(v) || 0);
    el.textContent = String(n);
  }

  function renderAts(ats, skipScore) {
    if (!skipScore) setText("troy-ats-score", String(ats.score || 0));
    setText("troy-ats-coverage", "Keyword coverage · " + (ats.keywordCoverage || 0) + "%");
    setText("troy-keywords-hit", safeList(ats.matchedKeywords, ["—"]).join(", "));
    setText("troy-keywords-missing", safeList(ats.missingKeywords, ["—"]).join(", "));
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value || "";
  }

  function playTerminal(logs) {
    if (!terminal) return;
    if (terminalTimer) {
      clearTimeout(terminalTimer);
      terminalTimer = null;
    }
    terminal.innerHTML = "";
    var lines = safeList(logs, ["[Carl] no terminal lines"]);
    var index = 0;
    if (terminalStatus) terminalStatus.textContent = "Streaming";
    function tick() {
      if (index >= lines.length) {
        terminalTimer = null;
        if (terminalStatus) terminalStatus.textContent = "Complete";
        return;
      }
      var row = document.createElement("div");
      row.className = "carl-terminal-row-in whitespace-pre-wrap border-l-2 border-[#18A7EC]/45 pl-2";
      row.textContent = "> " + lines[index];
      terminal.appendChild(row);
      terminal.scrollTop = terminal.scrollHeight;
      index += 1;
      var line = String(row.textContent || "");
      var pauseBoost = /[.?!]$/.test(line.trim()) ? 120 : 0;
      var jitter = Math.floor(Math.random() * TERMINAL_VARIANCE_MS);
      terminalTimer = setTimeout(tick, TERMINAL_BASE_MS + jitter + pauseBoost);
    }
    tick();
  }

  function addChatMessage(role, text) {
    if (!chatLog) return;
    var item = document.createElement("div");
    var isUser = role === "user";
    item.className = isUser
      ? "ml-6 rounded-xl border border-[#18A7EC]/35 bg-[#18A7EC]/12 px-3 py-2 text-sm text-white"
      : "mr-2 rounded-xl border border-white/10 bg-[#0D0D0D] px-3 py-2 text-sm leading-relaxed text-[#E5E5E5]";
    item.classList.add("carl-chat-bubble-in");
    item.textContent = text;
    chatLog.appendChild(item);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function setChatLocked(locked) {
    if (chatInput) chatInput.disabled = !!locked;
    if (chatSubmit) chatSubmit.disabled = !!locked;
    if (chatChips) {
      var buttons = chatChips.querySelectorAll("button");
      for (var i = 0; i < buttons.length; i++) buttons[i].disabled = !!locked;
    }
  }

  function resetCarlChatGate() {
    if (apiCta) apiCta.classList.add("hidden");
    setChatLocked(false);
  }

  function applyCarlChatLimit(inner) {
    if (apiCta) apiCta.classList.remove("hidden");
    if (inner && inner.cta) {
      var d = document.getElementById("carl-cta-developers");
      var p = document.getElementById("carl-cta-pricing");
      if (d && inner.cta.developers) d.setAttribute("href", inner.cta.developers);
      if (p && inner.cta.pricing) p.setAttribute("href", inner.cta.pricing);
    }
    if (chatChips) chatChips.classList.add("hidden");
    setChatLocked(true);
  }

  function renderSuggestedChips(prompts) {
    if (!chatChips) return;
    chatChips.innerHTML = "";
    var list = Array.isArray(prompts) && prompts.length ? prompts.slice(0, 3) : [];
    if (!list.length) {
      chatChips.classList.add("hidden");
      return;
    }
    chatChips.classList.remove("hidden");
    list.forEach(function (text, idx) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "max-w-full rounded-full border border-white/10 bg-[#111] px-3 py-1.5 text-left text-xs text-[#E5E5E5] hover:border-[#FF7A00]/40 hover:text-white";
      btn.setAttribute("aria-label", "Suggested question " + (idx + 1));
      var label = String(text || "").trim();
      btn.title = label;
      btn.textContent = label.length > 72 ? label.slice(0, 69) + "…" : label;
      btn.addEventListener("click", function () {
        sendCarlChat({ promptId: idx, displayText: label });
      });
      chatChips.appendChild(btn);
    });
  }

  function sendCarlChat(opts) {
    opts = opts || {};
    if (!analysisState) return;
    if (chatInput && chatInput.disabled) return;

    var promptId = opts.promptId;
    var displayText = opts.displayText;
    var rawMsg = opts.message != null ? String(opts.message).trim() : "";

    if (promptId === undefined && !rawMsg) return;

    var userShow = displayText || rawMsg;
    if (userShow) addChatMessage("user", userShow);
    if (opts.message != null && chatInput) chatInput.value = "";

    var body = {};
    if (promptId !== undefined && promptId !== null) {
      body.prompt_id = promptId;
      if (rawMsg) body.message = rawMsg;
    } else {
      body.message = rawMsg;
    }

    fetch("/carl/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        return resp
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { httpOk: resp.ok, data: data };
          });
      })
      .then(function (result) {
        var env = result.data || {};
        if (!result.httpOk || env.ok === false) {
          addChatMessage("assistant", env.message || "Unable to send chat message.");
          return;
        }
        var inner = env.data || {};
        var reply = inner.reply;
        addChatMessage("assistant", reply || "I can help with ATS, strengths, or rewrite suggestions.");
        if (inner.chat_limit_reached) applyCarlChatLimit(inner);
      })
      .catch(function () {
        addChatMessage("assistant", "Temporary chat issue. Ask again in a moment.");
      });
  }

  var troyTabsBound = false;

  function initTabs() {
    var tabs = document.querySelectorAll("[data-troy-tab]");
    var panels = {
      overview: document.getElementById("troy-panel-overview"),
      skills: document.getElementById("troy-panel-skills"),
      risks: document.getElementById("troy-panel-risks"),
    };
    function activate(name) {
      Object.keys(panels).forEach(function (key) {
        if (panels[key]) panels[key].classList.toggle("hidden", key !== name);
      });
      tabs.forEach(function (btn) {
        var on = btn.getAttribute("data-troy-tab") === name;
        btn.classList.toggle("troy-tab-active", on);
        btn.classList.toggle("text-[#9CA3AF]", !on);
        btn.classList.toggle("hover:text-white", !on);
      });
    }
    if (!troyTabsBound) {
      troyTabsBound = true;
      tabs.forEach(function (btn) {
        btn.addEventListener("click", function () {
          activate(btn.getAttribute("data-troy-tab") || "overview");
        });
      });
    }
    activate("overview");
  }

  function renderProfileSync(sync, source) {
    var el = document.getElementById("troy-profile-sync");
    if (!el) return;
    if (!sync) {
      el.textContent = "";
      el.classList.add("hidden");
      return;
    }
    el.classList.remove("hidden");
    var fn = source && source.filename != null ? String(source.filename) : "—";
    var st = sync.status || "";
    var at = sync.saved_at ? " · " + String(sync.saved_at) : "";
    if (st === "saved") {
      el.textContent = "Profile: saved " + fn + " to your account." + at;
    } else if (st === "error") {
      el.textContent = "Profile sync failed. Preview still works locally." + (sync.message ? " (" + sync.message + ")" : "");
    } else {
      el.textContent = "Profile sync skipped" + (sync.message ? ": " + sync.message : ".");
    }
  }

  function hydrateDashboard(analysis, extras) {
    extras = extras || {};
    analysisState = analysis || {};
    document.body.classList.add("troy-dashboard-active");
    if (uploadHero) uploadHero.classList.add("hidden");
    if (workspace) {
      workspace.classList.remove("hidden");
      workspace.classList.add("flex");
    }

    document.querySelectorAll("[data-carl-reveal]").forEach(function (el) {
      el.classList.remove("carl-reveal-in");
    });

    resetDashboardMeters();
    renderOverview(analysisState.overview || {}, true);
    renderAts(analysisState.atsScore || {}, true);
    renderSkills(analysisState.skillsRadar || []);
    renderDocuments(analysisState.documents || []);
    renderProfileSync(extras.profileSync, extras.source);
    renderActions(analysisState.actionFeed || []);

    renderList("troy-timeline", analysisState.experienceTimeline, function (item) {
      return (
        '<span class="font-semibold text-[#18A7EC]">' +
        escapeHtml(item.period || "") +
        "</span> · " +
        escapeHtml(item.role || "") +
        " — " +
        escapeHtml(item.impact || "")
      );
    });
    renderList("troy-quick-wins", analysisState.quickWins, function (item) {
      return escapeHtml(item || "");
    });
    renderList("troy-risk-flags", analysisState.riskFlags, function (item) {
      return escapeHtml(item || "");
    });

    if (chatLog) {
      chatLog.innerHTML = "";
      addChatMessage(
        "assistant",
        (analysisState.chatContext && analysisState.chatContext.summary) || "Analysis ready. Ask about ATS, rewrites, or risks."
      );
    }
    resetCarlChatGate();
    renderSuggestedChips((analysisState.chatContext && analysisState.chatContext.suggestedPrompts) || []);
    if (terminalStatus) terminalStatus.textContent = "Streaming";
    playTerminal(analysisState.terminalLogs || []);
    initTabs();

    requestAnimationFrame(function () {
      if (!workspace) return;
      void workspace.offsetWidth;
      var nodes = workspace.querySelectorAll("[data-carl-reveal]");
      nodes.forEach(function (el, i) {
        setTimeout(function () {
          el.classList.add("carl-reveal-in");
        }, REVEAL_BASE_DELAY_MS + i * REVEAL_STAGGER_MS);
      });

      var meterDelay = REVEAL_BASE_DELAY_MS + 2 * REVEAL_STAGGER_MS + METER_START_OFFSET_MS;
      setTimeout(function () {
        animateDashboardMeters(analysisState.overview || {}, analysisState.atsScore || {});
      }, meterDelay);
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    setError("");
    setUploadLoading(true);
    startUploadPremiumLoading();

    var started = performance.now();
    var payload = new FormData(form);
    fetch("/carl/analyze", {
      method: "POST",
      body: payload,
      credentials: "same-origin",
      headers: {
        "X-CSRF-Token": csrfToken(),
      },
    })
      .then(function (resp) {
        return resp
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: resp.ok, data: data };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.data || result.data.ok === false) {
          var em = (result.data && result.data.message) || "Could not analyze CV.";
          if (result.data && result.data.code === "login_required") {
            em = "Sign in to use Carl, then try again.";
          }
          throw new Error(em);
        }
        var inner = (result.data && result.data.data) || {};
        var analysis = inner.analysis;
        if (!analysis) throw new Error("Analysis payload missing.");
        var extras = {
          profileSync: inner.profile_sync,
          source: inner.source,
        };
        var elapsed = performance.now() - started;
        var remain = Math.max(0, MIN_ANALYZE_MS - elapsed);
        return delay(remain).then(function () {
          return { analysis: analysis, extras: extras };
        });
      })
      .then(function (payload) {
        hideUploadPremiumLoading(540, function () {
          hydrateDashboard(payload.analysis, payload.extras);
        });
      })
      .catch(function (err) {
        hideUploadPremiumLoading(220, function () {
          setError(err && err.message ? err.message : "Could not analyze CV. Please try again.");
        });
      })
      .finally(function () {
        setUploadLoading(false);
      });
  });

  if (chatForm) {
    chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!analysisState) return;
      var message = (chatInput && chatInput.value) || "";
      message = message.trim();
      if (!message) return;
      sendCarlChat({ message: message });
    });
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      if (fileInput.files && fileInput.files[0] && textFallback) {
        textFallback.value = "";
      }
    });
  }
})();
