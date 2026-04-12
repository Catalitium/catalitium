(function () {
  var form = document.getElementById("carl4b2b-market-form");
  if (!form) return;
  document.body.classList.add("carl4b2b-page");

  var analyzeBtn = document.getElementById("carl4b2b-analyze-btn");
  var errEl = document.getElementById("carl4b2b-form-error");
  var hero = document.getElementById("carl4b2b-query-hero");
  var workspace = document.getElementById("carl4b2b-workspace");
  var terminal = document.getElementById("carl4b2b-terminal");
  var terminalStatus = document.getElementById("carl4b2b-terminal-status");
  var chatForm = document.getElementById("carl4b2b-chat-form");
  var chatInput = document.getElementById("carl4b2b-chat-input");
  var chatLog = document.getElementById("carl4b2b-chat-log");
  var chatChips = document.getElementById("carl4b2b-chat-chips");
  var apiCta = document.getElementById("carl4b2b-api-cta");
  var chatSubmit = document.getElementById("carl4b2b-chat-submit");

  var analysisState = null;
  var terminalTimer = null;
  var MIN_ANALYZE_MS = 1200;
  var REVEAL_BASE_DELAY_MS = 120;
  var REVEAL_STAGGER_MS = 200;
  var METER_START_OFFSET_MS = 600;
  var METER_ANIMATION_MS = 1600;
  var ATS_ANIMATION_MS = 1800;
  var ROW_STAGGER_DOCUMENT_MS = 120;
  var ROW_STAGGER_SKILL_MS = 100;

  function csrfToken() {
    var field = form.querySelector('input[name="csrf_token"]');
    return field && field.value ? String(field.value).trim() : "";
  }

  function setAnalyzeLoading(on) {
    if (!analyzeBtn) return;
    analyzeBtn.disabled = !!on;
    var sp = document.getElementById("carl4b2b-analyze-spinner");
    var tx = document.getElementById("carl4b2b-analyze-text");
    if (sp) sp.classList.toggle("hidden", !on);
    if (tx) tx.textContent = on ? "Mapping catalog…" : "Run market map";
  }

  function delay(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function setError(msg) {
    if (!errEl) return;
    if (!msg) {
      errEl.classList.add("hidden");
      errEl.textContent = "";
      return;
    }
    errEl.textContent = msg;
    errEl.classList.remove("hidden");
  }

  function safeList(items, fallback) {
    return Array.isArray(items) && items.length ? items : fallback;
  }

  function setGauge(wrapEl, valEl, pct) {
    if (!wrapEl) return;
    var p = Math.max(0, Math.min(100, Number(pct) || 0));
    var deg = p * 3.6;
    var color = p >= 55 ? "#38bdf8" : "#f59e0b";
    wrapEl.style.background =
      "conic-gradient(from -90deg, " + color + " 0deg, " + color + " " + deg + "deg, #1e293b " + deg + "deg)";
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
      el.textContent = String(Math.round(a + (b - a) * eased));
      if (t < 1) requestAnimationFrame(frame);
      else if (done) done();
    }
    requestAnimationFrame(frame);
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderList(id, items, formatter) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = "";
    var list = safeList(items, []);
    if (!list.length) {
      el.innerHTML = '<li class="text-xs text-slate-500">No data yet.</li>';
      return;
    }
    list.forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML = formatter(item);
      el.appendChild(li);
    });
  }

  function renderDocuments(docs) {
    var root = document.getElementById("carl4b2b-documents");
    if (!root) return;
    root.innerHTML = "";
    var list = safeList(docs, []);
    if (!list.length) {
      root.innerHTML = '<li class="text-xs text-slate-500">No documents.</li>';
      return;
    }
    list.forEach(function (d, i) {
      var li = document.createElement("li");
      li.className =
        "c4b-animate-row flex cursor-default items-center gap-3 rounded-lg border border-white/10 bg-slate-900/60 px-3 py-2.5";
      li.style.animationDelay = i * ROW_STAGGER_DOCUMENT_MS + "ms";
      var badge = d.badge
        ? '<span class="shrink-0 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-300">' +
          escapeHtml(d.badge) +
          "</span>"
        : "";
      li.innerHTML =
        '<span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-500/20 text-sky-300">' +
        '<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg></span>' +
        '<div class="min-w-0 flex-1">' +
        '<p class="truncate text-sm font-medium text-white">' +
        escapeHtml(d.title || "") +
        "</p>" +
        '<p class="truncate text-xs text-slate-500">' +
        escapeHtml(d.subtitle || "") +
        "</p></div>" +
        badge;
      root.appendChild(li);
    });
  }

  function renderSkills(skills) {
    var root = document.getElementById("carl4b2b-skills");
    if (!root) return;
    root.innerHTML = "";
    var list = safeList(skills, []);
    if (!list.length) {
      root.innerHTML = '<p class="text-xs text-slate-500">No radar rows.</p>';
      return;
    }
    list.forEach(function (item, i) {
      var score = Number(item.score || 0);
      var row = document.createElement("div");
      row.className = "c4b-animate-row space-y-1.5";
      row.style.animationDelay = i * ROW_STAGGER_SKILL_MS + "ms";
      row.innerHTML =
        '<div class="flex items-center justify-between text-xs">' +
        '<span class="font-medium text-slate-200">' +
        escapeHtml(item.skill || "Employer") +
        "</span>" +
        '<span class="tabular-nums text-amber-300">' +
        score +
        "</span></div>" +
        '<div class="h-1.5 overflow-hidden rounded-full bg-slate-900">' +
        '<div class="h-full rounded-full bg-gradient-to-r from-blue-600 via-sky-500 to-amber-400" style="width:' +
        Math.min(100, Math.max(0, score)) +
        '%"></div></div>';
      root.appendChild(row);
    });
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value || "";
  }

  function vitalClass(v) {
    var n = Number(v) || 0;
    return n >= 60 ? "text-sky-300" : "text-amber-300";
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
    el.textContent = String(Math.round(Number(v) || 0));
  }

  function renderOverview(overview, skipMeters) {
    setText("carl4b2b-headline", overview.headline || "Analysis complete");
    setText("carl4b2b-fit-summary", overview.fitSummary || "");
    var personaLine = (overview.persona || "—") + " · " + (overview.level || "—");
    setText("carl4b2b-persona-line", personaLine);
    setText("carl4b2b-level", overview.level || "—");
    setText("carl4b2b-confidence", overview.confidence ? overview.confidence + "%" : "—");
    setText("carl4b2b-word-count", overview.wordCount != null ? String(overview.wordCount) : "—");
    if (skipMeters) return;
    var scores = overview.signalScores || {};
    setGauge(document.getElementById("carl4b2b-gauge-structure"), document.getElementById("carl4b2b-gauge-structure-val"), scores.structure);
    setGauge(document.getElementById("carl4b2b-gauge-keywords"), document.getElementById("carl4b2b-gauge-keywords-val"), scores.keywords);
    setGauge(document.getElementById("carl4b2b-gauge-impact"), document.getElementById("carl4b2b-gauge-impact-val"), scores.impact);
    setVital("carl4b2b-vital-structure", scores.structure);
    setVital("carl4b2b-vital-keywords", scores.keywords);
    setVital("carl4b2b-vital-impact", scores.impact);
    setVital("carl4b2b-vital-narrative", scores.narrative);
    var premium = overview.premiumSignals || {};
    setMetric("carl4b2b-metric-leadership", premium.leadership);
    setMetric("carl4b2b-metric-role-match", premium.roleMatch);
    setMetric("carl4b2b-metric-evidence", premium.evidenceDensity);
  }

  function resetDashboardMeters() {
    setGauge(document.getElementById("carl4b2b-gauge-structure"), document.getElementById("carl4b2b-gauge-structure-val"), 0);
    setGauge(document.getElementById("carl4b2b-gauge-keywords"), document.getElementById("carl4b2b-gauge-keywords-val"), 0);
    setGauge(document.getElementById("carl4b2b-gauge-impact"), document.getElementById("carl4b2b-gauge-impact-val"), 0);
    setText("carl4b2b-ats-score", "0");
    ["carl4b2b-vital-structure", "carl4b2b-vital-keywords", "carl4b2b-vital-impact", "carl4b2b-vital-narrative"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.textContent = "0";
      el.className = "mt-1 text-lg font-semibold tabular-nums text-slate-500";
    });
  }

  function renderAts(ats, skipScore) {
    if (!skipScore) setText("carl4b2b-ats-score", String(ats.score || 0));
    setText("carl4b2b-ats-coverage", "Employer diversity · " + (ats.keywordCoverage || 0) + "%");
    setText("carl4b2b-keywords-hit", safeList(ats.matchedKeywords, ["—"]).join(", "));
    setText("carl4b2b-keywords-missing", safeList(ats.missingKeywords, ["—"]).join(", "));
  }

  function animateDashboardMeters(overview, ats) {
    var scores = (overview && overview.signalScores) || {};
    var premium = (overview && overview.premiumSignals) || {};
    var atsScore = Math.round(Number((ats && ats.score) || 0));
    var dur = METER_ANIMATION_MS;
    animateGaugeTo(
      document.getElementById("carl4b2b-gauge-structure"),
      document.getElementById("carl4b2b-gauge-structure-val"),
      scores.structure,
      dur
    );
    animateGaugeTo(
      document.getElementById("carl4b2b-gauge-keywords"),
      document.getElementById("carl4b2b-gauge-keywords-val"),
      scores.keywords,
      dur
    );
    animateGaugeTo(
      document.getElementById("carl4b2b-gauge-impact"),
      document.getElementById("carl4b2b-gauge-impact-val"),
      scores.impact,
      dur
    );
    animateNumberEl(document.getElementById("carl4b2b-ats-score"), 0, atsScore, ATS_ANIMATION_MS);
    animateNumberEl(document.getElementById("carl4b2b-vital-structure"), 0, scores.structure, dur, function () {
      setVital("carl4b2b-vital-structure", scores.structure);
    });
    animateNumberEl(document.getElementById("carl4b2b-vital-keywords"), 0, scores.keywords, dur, function () {
      setVital("carl4b2b-vital-keywords", scores.keywords);
    });
    animateNumberEl(document.getElementById("carl4b2b-vital-impact"), 0, scores.impact, dur, function () {
      setVital("carl4b2b-vital-impact", scores.impact);
    });
    animateNumberEl(document.getElementById("carl4b2b-vital-narrative"), 0, scores.narrative, dur, function () {
      setVital("carl4b2b-vital-narrative", scores.narrative);
    });
    setMetric("carl4b2b-metric-leadership", premium.leadership);
    setMetric("carl4b2b-metric-role-match", premium.roleMatch);
    setMetric("carl4b2b-metric-evidence", premium.evidenceDensity);
  }

  function playTerminal(logs) {
    if (!terminal) return;
    if (terminalTimer) {
      clearTimeout(terminalTimer);
      terminalTimer = null;
    }
    terminal.innerHTML = "";
    var lines = safeList(logs, ["[Carl4B2B] no terminal lines"]);
    var index = 0;
    if (terminalStatus) terminalStatus.textContent = "Streaming";
    function tick() {
      if (index >= lines.length) {
        terminalTimer = null;
        if (terminalStatus) terminalStatus.textContent = "Complete";
        return;
      }
      var row = document.createElement("div");
      row.className = "c4b-terminal-row-in whitespace-pre-wrap border-l-2 border-amber-400/50 pl-2";
      row.textContent = "> " + lines[index];
      terminal.appendChild(row);
      terminal.scrollTop = terminal.scrollHeight;
      index += 1;
      terminalTimer = setTimeout(tick, 28);
    }
    tick();
  }

  function addChatMessage(role, text) {
    if (!chatLog) return;
    var item = document.createElement("div");
    var isUser = role === "user";
    item.className = isUser
      ? "ml-6 rounded-xl border border-sky-500/35 bg-sky-500/10 px-3 py-2 text-sm text-white"
      : "mr-2 rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-sm leading-relaxed text-slate-200";
    item.classList.add("c4b-chat-bubble-in");
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

  function resetChatGate() {
    if (apiCta) apiCta.classList.add("hidden");
    setChatLocked(false);
  }

  function applyChatLimit(inner) {
    if (apiCta) apiCta.classList.remove("hidden");
    if (inner && inner.cta) {
      var d = document.getElementById("carl4b2b-cta-developers");
      var p = document.getElementById("carl4b2b-cta-pricing");
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
        "max-w-full rounded-full border border-white/10 bg-slate-900 px-3 py-1.5 text-left text-xs text-slate-200 hover:border-amber-400/50";
      var label = String(text || "").trim();
      btn.title = label;
      btn.textContent = label.length > 72 ? label.slice(0, 69) + "…" : label;
      btn.addEventListener("click", function () {
        sendChat({ promptId: idx, displayText: label });
      });
      chatChips.appendChild(btn);
    });
  }

  function renderMatches(matches) {
    var jRoot = document.getElementById("carl4b2b-match-jobs");
    var cRoot = document.getElementById("carl4b2b-match-companies");
    var nRoot = document.getElementById("carl4b2b-match-niche");
    if (!jRoot || !cRoot || !nRoot || !matches) return;
    jRoot.innerHTML = "";
    cRoot.innerHTML = "";
    nRoot.innerHTML = "";
    function card(title, subtitle, href) {
      return (
        '<div class="rounded-2xl border border-white/10 bg-white/[0.03] p-4">' +
        '<p class="text-sm font-bold text-white">' +
        escapeHtml(title) +
        "</p>" +
        '<p class="mt-1 text-xs text-slate-400">' +
        escapeHtml(subtitle) +
        '</p><a href="' +
        escapeHtml(href || "/jobs") +
        '" class="mt-3 inline-flex text-xs font-semibold text-sky-400 hover:text-white">Open →</a></div>'
      );
    }
    safeList(matches.jobs, []).forEach(function (j) {
      jRoot.innerHTML += card(j.title, (j.company || "") + " · " + (j.location || ""), j.link);
    });
    safeList(matches.top_companies, []).forEach(function (c) {
      cRoot.innerHTML += card(c.name, c.reason || "", "/jobs");
    });
    safeList(matches.niche_companies, []).forEach(function (n) {
      nRoot.innerHTML += card(n.name, n.reason || "", "/jobs");
    });
    var sec = document.getElementById("carl4b2b-matches-section");
    if (sec) {
      sec.classList.remove("hidden");
      setTimeout(function () {
        sec.classList.add("c4b-reveal-in");
      }, REVEAL_BASE_DELAY_MS * 3);
    }
  }

  function renderProfileSync(sync, source) {
    var el = document.getElementById("carl4b2b-profile-sync");
    if (!el) return;
    if (!sync) {
      el.textContent = "";
      el.classList.add("hidden");
      return;
    }
    el.classList.remove("hidden");
    var st = sync.status || "";
    var at = sync.saved_at ? " · " + String(sync.saved_at) : "";
    if (st === "saved") {
      el.textContent = "Profile: B2B snapshot saved." + at;
    } else if (st === "error") {
      el.textContent = "Profile sync failed. Dashboard still works in-session.";
    } else {
      el.textContent = "Profile sync skipped.";
    }
  }

  function initTabs() {
    var tabs = document.querySelectorAll("[data-c4b-tab]");
    var panels = {
      overview: document.getElementById("carl4b2b-panel-overview"),
      skills: document.getElementById("carl4b2b-panel-skills"),
      risks: document.getElementById("carl4b2b-panel-risks"),
    };
    function activate(name) {
      Object.keys(panels).forEach(function (key) {
        if (panels[key]) panels[key].classList.toggle("hidden", key !== name);
      });
      tabs.forEach(function (btn) {
        var on = btn.getAttribute("data-c4b-tab") === name;
        btn.classList.toggle("c4b-tab-active", on);
        btn.classList.toggle("text-slate-400", !on);
        btn.classList.toggle("hover:text-white", !on);
      });
    }
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        activate(btn.getAttribute("data-c4b-tab") || "overview");
      });
    });
    activate("overview");
  }

  function hydrate(analysis, extras) {
    extras = extras || {};
    analysisState = analysis || {};
    document.body.classList.add("carl4b2b-dashboard-active");
    if (hero) hero.classList.add("hidden");
    if (workspace) {
      workspace.classList.remove("hidden");
      workspace.classList.add("flex");
    }
    document.querySelectorAll("[data-c4b-reveal]").forEach(function (el) {
      el.classList.remove("c4b-reveal-in");
    });
    resetDashboardMeters();
    renderOverview(analysisState.overview || {}, true);
    renderAts(analysisState.atsScore || {}, true);
    renderSkills(analysisState.skillsRadar || []);
    renderDocuments(analysisState.documents || []);
    renderProfileSync(extras.profileSync, extras.source);
    renderList("carl4b2b-timeline", analysisState.experienceTimeline, function (item) {
      return (
        '<span class="font-semibold text-sky-400">' +
        escapeHtml(item.period || "") +
        "</span> · " +
        escapeHtml(item.role || "") +
        " — " +
        escapeHtml(item.impact || "")
      );
    });
    renderList("carl4b2b-quick-wins", analysisState.quickWins, function (item) {
      return escapeHtml(item || "");
    });
    renderList("carl4b2b-risk-flags", analysisState.riskFlags, function (item) {
      return escapeHtml(item || "");
    });
    if (chatLog) {
      chatLog.innerHTML = "";
      addChatMessage(
        "assistant",
        (analysisState.chatContext && analysisState.chatContext.summary) || "Market map ready. Ask about saturation or competitors."
      );
    }
    resetChatGate();
    renderSuggestedChips((analysisState.chatContext && analysisState.chatContext.suggestedPrompts) || []);
    if (terminalStatus) terminalStatus.textContent = "Streaming";
    playTerminal(analysisState.terminalLogs || []);
    initTabs();
    requestAnimationFrame(function () {
      if (!workspace) return;
      void workspace.offsetWidth;
      var nodes = workspace.querySelectorAll("[data-c4b-reveal]");
      nodes.forEach(function (el, i) {
        setTimeout(function () {
          el.classList.add("c4b-reveal-in");
        }, REVEAL_BASE_DELAY_MS + i * REVEAL_STAGGER_MS);
      });
      var meterDelay = REVEAL_BASE_DELAY_MS + 2 * REVEAL_STAGGER_MS + METER_START_OFFSET_MS;
      setTimeout(function () {
        animateDashboardMeters(analysisState.overview || {}, analysisState.atsScore || {});
        renderMatches(analysisState.matches || null);
      }, meterDelay);
    });
  }

  function sendChat(opts) {
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
    fetch("/carl/b2b/chat", {
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
          addChatMessage("assistant", env.message || "Unable to send message.");
          return;
        }
        var inner = env.data || {};
        addChatMessage("assistant", inner.reply || "Ask about this catalog pass.");
        if (inner.chat_limit_reached) applyChatLimit(inner);
      })
      .catch(function () {
        addChatMessage("assistant", "Temporary issue. Try again shortly.");
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var title = (document.getElementById("carl4b2b-title") && document.getElementById("carl4b2b-title").value) || "";
    var country = (document.getElementById("carl4b2b-country") && document.getElementById("carl4b2b-country").value) || "";
    if (String(title).trim().length < 2 && String(country).trim().length < 2) {
      setError("Enter at least a meaningful title or country (two+ characters).");
      return;
    }
    setError("");
    setAnalyzeLoading(true);
    var started = performance.now();
    var payload = {
      title_q: String(title).trim(),
      country_q: String(country).trim(),
      exclude_company: (document.getElementById("carl4b2b-exclude") && document.getElementById("carl4b2b-exclude").value) || "",
      business_url: (document.getElementById("carl4b2b-url") && document.getElementById("carl4b2b-url").value) || "",
      company_email: (document.getElementById("carl4b2b-email") && document.getElementById("carl4b2b-email").value) || "",
    };
    fetch("/carl/b2b/analyze", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(payload),
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
          var em = (result.data && result.data.message) || "Could not build market map.";
          if (result.data && result.data.code === "login_required") {
            em = "Sign in first, then try again.";
          }
          throw new Error(em);
        }
        var inner = (result.data && result.data.data) || {};
        var analysis = inner.analysis;
        if (!analysis) throw new Error("Missing analysis payload.");
        var extras = { profileSync: inner.profile_sync, source: inner.source };
        var elapsed = performance.now() - started;
        var remain = Math.max(0, MIN_ANALYZE_MS - elapsed);
        return delay(remain).then(function () {
          return { analysis: analysis, extras: extras };
        });
      })
      .then(function (pack) {
        hydrate(pack.analysis, pack.extras);
      })
      .catch(function (err) {
        setError(err && err.message ? err.message : "Request failed.");
      })
      .finally(function () {
        setAnalyzeLoading(false);
      });
  });

  if (chatForm) {
    chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!analysisState) return;
      var message = (chatInput && chatInput.value) || "";
      message = message.trim();
      if (!message) return;
      sendChat({ message: message });
    });
  }

  if (chatInput) {
    chatInput.addEventListener("input", function () {
      var c = document.getElementById("carl4b2b-chat-counter");
      if (c) c.textContent = chatInput.value.length + "/280";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var pre = document.getElementById("preloaded-carl4b2b-data");
    if (pre && pre.textContent) {
      try {
        var data = JSON.parse(pre.textContent);
        if (data && data.overview) {
          hydrate(data, {});
        }
      } catch (e) {
        console.error("Carl4B2B: preload parse failed", e);
      }
    }
  });
})();
