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
  var terminalLiveTimer = null;
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

  function renderSalaryDrift(drift) {
    var card = document.getElementById("carl4b2b-salary-drift-card");
    if (!card) return;
    if (!drift || !drift.status) {
      card.classList.add("hidden");
      return;
    }
    var arrow = document.getElementById("carl4b2b-salary-drift-arrow");
    var labelEl = document.getElementById("carl4b2b-salary-drift-label");
    var newEl = document.getElementById("carl4b2b-salary-drift-new");
    var oldEl = document.getElementById("carl4b2b-salary-drift-old");
    var deltaEl = document.getElementById("carl4b2b-salary-drift-delta");
    var noteEl = document.getElementById("carl4b2b-salary-drift-note");
    var body = document.getElementById("carl4b2b-salary-drift-body");
    card.classList.remove("hidden");

    if (drift.status !== "ok") {
      if (body) body.classList.add("hidden");
      if (deltaEl) deltaEl.classList.add("hidden");
      if (arrow) {
        arrow.textContent = "—";
        arrow.className = "c4b-drift-arrow c4b-drift-flat";
      }
      if (labelEl) labelEl.textContent = "Insufficient salary data";
      if (noteEl) noteEl.textContent = drift.note || "Sample too small to compute drift.";
      return;
    }

    if (body) body.classList.remove("hidden");
    if (deltaEl) deltaEl.classList.remove("hidden");

    var dir = drift.direction || "flat";
    var arrowGlyph = dir === "up" ? "↑" : dir === "down" ? "↓" : "→";
    if (arrow) {
      arrow.textContent = arrowGlyph;
      arrow.className = "c4b-drift-arrow c4b-drift-" + dir;
    }
    if (labelEl) labelEl.textContent = drift.direction_label || "Stable";

    function fmtUsd(n) {
      var x = Math.round(Number(n) || 0);
      return "$" + x.toLocaleString("en-US");
    }
    var newer = drift.newer_half || {};
    var older = drift.older_half || {};
    if (newEl) {
      newEl.textContent = fmtUsd(newer.median_salary) + " · n=" + (newer.count || 0) +
        " (" + (newer.age_min || 0) + "-" + (newer.age_max || 0) + "d)";
    }
    if (oldEl) {
      oldEl.textContent = fmtUsd(older.median_salary) + " · n=" + (older.count || 0) +
        " (" + (older.age_min || 0) + "-" + (older.age_max || 0) + "d)";
    }
    if (deltaEl) {
      var signAbs = (drift.delta_abs > 0 ? "+" : "") + fmtUsd(drift.delta_abs);
      var signPct = (drift.delta_pct > 0 ? "+" : "") + String(drift.delta_pct) + "%";
      deltaEl.textContent = "Delta: " + signAbs + " (" + signPct + ")";
    }
    if (noteEl) noteEl.textContent = drift.note || "";
  }

  var braveBusy = false;
  var braveRemaining = null;

  function renderBraveCard(show) {
    var card = document.getElementById("carl4b2b-brave-card");
    if (!card) return;
    if (!show) {
      card.classList.add("hidden");
      return;
    }
    card.classList.remove("hidden");
    if (braveRemaining === null) braveRemaining = 3;
    var rem = document.getElementById("carl4b2b-brave-remaining");
    if (rem) rem.textContent = String(braveRemaining) + " left";
    var status = document.getElementById("carl4b2b-brave-status");
    var list = document.getElementById("carl4b2b-brave-results");
    var footer = document.getElementById("carl4b2b-brave-footer");
    if (status) {
      status.classList.add("hidden");
      status.textContent = "";
    }
    if (list) {
      list.classList.add("hidden");
      list.innerHTML = "";
    }
    if (footer) footer.classList.add("hidden");
    setBraveButtonsDisabled(false);
  }

  function setBraveButtonsDisabled(disabled) {
    var btns = document.querySelectorAll(".c4b-brave-btn");
    btns.forEach(function (btn) {
      btn.disabled = !!disabled;
    });
  }

  function setBraveStatus(text, tone) {
    var status = document.getElementById("carl4b2b-brave-status");
    if (!status) return;
    if (!text) {
      status.classList.add("hidden");
      status.textContent = "";
      return;
    }
    status.textContent = text;
    status.className =
      "mt-2 text-[10px] " +
      (tone === "warn" ? "text-amber-300" : "text-slate-400");
    status.classList.remove("hidden");
  }

  function renderBraveResults(items) {
    var list = document.getElementById("carl4b2b-brave-results");
    var footer = document.getElementById("carl4b2b-brave-footer");
    if (!list) return;
    list.innerHTML = "";
    if (!items || !items.length) {
      list.classList.add("hidden");
      if (footer) footer.classList.add("hidden");
      return;
    }
    items.forEach(function (it) {
      var li = document.createElement("li");
      li.className = "rounded-lg border border-white/10 bg-slate-950/40 p-2";
      var a = document.createElement("a");
      a.href = String(it.url || "#");
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.className = "font-semibold text-sky-300 hover:text-white";
      a.textContent = String(it.title || "—");
      li.appendChild(a);
      if (it.description) {
        var p = document.createElement("p");
        p.className = "mt-1 text-[10px] text-slate-400";
        p.textContent = String(it.description);
        li.appendChild(p);
      }
      if (it.age) {
        var meta = document.createElement("p");
        meta.className = "mt-0.5 text-[10px] text-slate-500";
        meta.textContent = String(it.age);
        li.appendChild(meta);
      }
      list.appendChild(li);
    });
    list.classList.remove("hidden");
    if (footer) footer.classList.remove("hidden");
  }

  function updateBraveRemaining(remaining) {
    braveRemaining = typeof remaining === "number" ? Math.max(0, remaining) : braveRemaining;
    var rem = document.getElementById("carl4b2b-brave-remaining");
    if (rem) rem.textContent = String(braveRemaining) + " left";
    if (braveRemaining === 0) setBraveButtonsDisabled(true);
  }

  function onBraveClick(ctxType) {
    if (braveBusy) return;
    if (braveRemaining === 0) return;
    braveBusy = true;
    setBraveButtonsDisabled(true);
    setBraveStatus("Fetching external context…");
    fetch("/carl/b2b/brave/context", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify({ context_type: ctxType }),
    })
      .then(function (resp) {
        return resp.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        var payload = (data && data.ok && data.data) || data || {};
        var status = payload.status || "unavailable";
        if (typeof payload.remaining === "number") {
          updateBraveRemaining(payload.remaining);
        }
        if (status === "ok") {
          renderBraveResults(payload.items || []);
          setBraveStatus("");
        } else if (status === "no_results") {
          renderBraveResults([]);
          setBraveStatus("No external signals for this query.", "warn");
        } else if (status === "limit_reached") {
          renderBraveResults([]);
          updateBraveRemaining(0);
          setBraveStatus("External context limit reached for this session.", "warn");
        } else if (status === "unavailable") {
          renderBraveResults([]);
          setBraveStatus("External context temporarily unavailable.", "warn");
        } else {
          renderBraveResults([]);
          setBraveStatus("Could not fetch external context.", "warn");
        }
      })
      .catch(function () {
        renderBraveResults([]);
        setBraveStatus("Network error while fetching external context.", "warn");
      })
      .finally(function () {
        braveBusy = false;
        if (braveRemaining > 0) setBraveButtonsDisabled(false);
      });
  }

  function wireBraveButtons() {
    var btns = document.querySelectorAll(".c4b-brave-btn");
    btns.forEach(function (btn) {
      if (btn.dataset.c4bBraveWired === "1") return;
      btn.dataset.c4bBraveWired = "1";
      btn.addEventListener("click", function () {
        var t = btn.getAttribute("data-brave-type") || "";
        if (!t) return;
        onBraveClick(t);
      });
    });
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

  function stopB2bTerminalLiveFeed() {
    if (terminalLiveTimer) {
      clearInterval(terminalLiveTimer);
      terminalLiveTimer = null;
    }
    var liveEl = document.getElementById("carl4b2b-terminal-live");
    if (liveEl) liveEl.textContent = "";
  }

  function buildMarketSentencePool(analysis) {
    var pool = [];
    var seen = {};
    function addOne(t) {
      t = String(t || "")
        .trim()
        .replace(/\s+/g, " ");
      if (t.length < 22 || t.length > 280) return;
      var k = t.toLowerCase().slice(0, 64);
      if (seen[k]) return;
      seen[k] = true;
      pool.push(t);
    }
    function addFromBlob(blob) {
      if (!blob) return;
      String(blob)
        .split(/[.!?]+/)
        .forEach(function (chunk) {
          addOne(chunk);
        });
    }
    if (!analysis) {
      return ["Run a market map with role + country or a company URL to populate this feed."];
    }
    var mm = analysis.marketMeta || {};
    if (mm.business_url) {
      addOne("Source URL: " + mm.business_url);
    }
    addOne("Catalog slice: " + (mm.title_q || "") + " · " + (mm.country_q || "—"));
    var ov = analysis.overview || {};
    addOne(ov.headline);
    addFromBlob(ov.fitSummary);
    var cc = analysis.chatContext || {};
    addFromBlob(cc.summary);
    (analysis.documents || []).forEach(function (d) {
      addOne((d.title || "") + " — " + (d.subtitle || ""));
    });
    (analysis.strengths || []).forEach(function (s) {
      addOne(s);
    });
    (analysis.riskFlags || []).forEach(function (x) {
      addOne(x);
    });
    (analysis.quickWins || []).forEach(function (x) {
      addOne(x);
    });
    (analysis.terminalLogs || []).forEach(function (line) {
      addOne(String(line).replace(/^\[Carl4B2B\]\s*/i, "").trim());
    });
    var matches = analysis.matches || {};
    (matches.top_companies || []).slice(0, 6).forEach(function (c) {
      addOne((c.name || "") + " — " + (c.reason || ""));
    });
    if (!pool.length) {
      addOne("Catalog pass ready — ask Carl about saturation, competitors, or sample limits.");
    }
    return pool.slice(0, 40);
  }

  function startB2bTerminalLiveFeed() {
    stopB2bTerminalLiveFeed();
    if (!analysisState) return;
    var pool = buildMarketSentencePool(analysisState);
    var liveEl = document.getElementById("carl4b2b-terminal-live");
    if (!liveEl || !pool.length) return;
    var idx = 0;
    function show() {
      liveEl.style.opacity = "0";
      setTimeout(function () {
        liveEl.textContent = pool[idx % pool.length];
        liveEl.style.opacity = "1";
        idx += 1;
      }, 120);
    }
    show();
    terminalLiveTimer = setInterval(show, 15000);
  }

  function playTerminal(logs, onComplete) {
    if (!terminal) return;
    stopB2bTerminalLiveFeed();
    if (terminalTimer) {
      clearTimeout(terminalTimer);
      terminalTimer = null;
    }
    terminal.innerHTML = "";
    var liveClear = document.getElementById("carl4b2b-terminal-live");
    if (liveClear) liveClear.textContent = "";
    var lines = safeList(logs, ["[Carl4B2B] no terminal lines"]);
    var index = 0;
    if (terminalStatus) terminalStatus.textContent = "stream";
    function tick() {
      if (index >= lines.length) {
        terminalTimer = null;
        if (terminalStatus) {
          setTimeout(function () {
            terminalStatus.textContent = "idle";
            if (onComplete) onComplete();
          }, 260);
        } else if (onComplete) {
          onComplete();
        }
        return;
      }
      var row = document.createElement("div");
      row.className = "c4b-terminal-row-in c4b-term-log-line";
      row.innerHTML =
        '<span class="c4b-term-prompt-mono">b2b<span class="c4b-term-at">@</span>catalog<span class="c4b-term-at">:</span>~<span class="c4b-term-at">$</span></span>' +
        '<span class="c4b-term-line-text">' +
        escapeHtml(lines[index]) +
        "</span>";
      terminal.appendChild(row);
      terminal.scrollTop = terminal.scrollHeight;
      index += 1;
      terminalTimer = setTimeout(tick, 22);
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
    function ghostBadgeHtml(ghost) {
      if (!ghost || typeof ghost.score !== "number") return "";
      var tone = "c4b-ghost-active";
      if (ghost.score >= 50) tone = "c4b-ghost-low";
      else if (ghost.score >= 25) tone = "c4b-ghost-uncertain";
      var payload = encodeURIComponent(JSON.stringify(ghost));
      return (
        '<button type="button" class="c4b-ghost-badge ' + tone + '"' +
        ' data-ghost="' + payload + '"' +
        ' aria-label="Ghost likelihood score: ' + escapeHtml(ghost.label || "") + '">' +
        "Ghost " + ghost.score + " · " + escapeHtml(ghost.label || "") +
        "</button>"
      );
    }
    function card(title, subtitle, href, ghost) {
      return (
        '<div class="rounded-2xl border border-white/10 bg-white/[0.03] p-4">' +
        '<div class="flex items-start justify-between gap-2">' +
        '<p class="text-sm font-bold text-white">' + escapeHtml(title) + "</p>" +
        ghostBadgeHtml(ghost) +
        "</div>" +
        '<p class="mt-1 text-xs text-slate-400">' + escapeHtml(subtitle) + "</p>" +
        '<a href="' + escapeHtml(href || "/jobs") + '"' +
        ' class="mt-3 inline-flex text-xs font-semibold text-sky-400 hover:text-white">Open →</a></div>'
      );
    }
    safeList(matches.jobs, []).forEach(function (j) {
      jRoot.innerHTML += card(j.title, (j.company || "") + " · " + (j.location || ""), j.link, j.ghost);
    });
    safeList(matches.top_companies, []).forEach(function (c) {
      cRoot.innerHTML += card(c.name, c.reason || "", "/jobs");
    });
    safeList(matches.niche_companies, []).forEach(function (n) {
      nRoot.innerHTML += card(n.name, n.reason || "", "/jobs");
    });
    jRoot.querySelectorAll(".c4b-ghost-badge").forEach(function (btn) {
      btn.addEventListener("click", function () {
        try {
          var ghost = JSON.parse(decodeURIComponent(btn.getAttribute("data-ghost") || ""));
          openGhostModal(ghost);
        } catch (err) { /* no-op */ }
      });
    });
    var sec = document.getElementById("carl4b2b-matches-section");
    if (sec) {
      sec.classList.remove("hidden");
      setTimeout(function () {
        sec.classList.add("c4b-reveal-in");
      }, REVEAL_BASE_DELAY_MS * 3);
    }
  }

  function openGhostModal(ghost) {
    var modal = document.getElementById("carl4b2b-ghost-modal");
    var body = document.getElementById("carl4b2b-ghost-modal-body");
    if (!modal || !body || !ghost) return;
    var rows = (ghost.factors || []).map(function (f) {
      return (
        '<tr><td class="py-1 pr-3 text-slate-300">' + escapeHtml(f.label || f.key || "") + "</td>" +
        '<td class="py-1 pr-3 text-slate-400">' + escapeHtml(f.detail || "") + "</td>" +
        '<td class="py-1 text-right font-semibold text-white">' + String(f.points || 0) + "</td></tr>"
      );
    }).join("");
    body.innerHTML =
      '<p class="text-xs uppercase tracking-wider text-slate-500">Ghost likelihood</p>' +
      '<p class="mt-1 text-2xl font-bold text-white">' + String(ghost.score || 0) + " / 100</p>" +
      '<p class="text-sm text-slate-300">' + escapeHtml(ghost.label || "") + "</p>" +
      '<table class="mt-4 w-full text-xs"><tbody>' + rows + "</tbody></table>";
    modal.classList.remove("hidden");
  }
  document.addEventListener("click", function (e) {
    var modal = document.getElementById("carl4b2b-ghost-modal");
    if (!modal) return;
    if (e.target && (e.target.id === "carl4b2b-ghost-modal-close" || e.target.id === "carl4b2b-ghost-modal")) {
      modal.classList.add("hidden");
    }
  });

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

  /** Return to the market-map form; skip one server preload on next full page load (mirrors B2C `carl_skip_preload_once`). */
  function resetCarl4b2bToFormView() {
    try {
      sessionStorage.setItem("carl4b2b_skip_preload_once", "1");
    } catch (eSt) {}
    analysisState = null;
    stopB2bTerminalLiveFeed();
    if (terminalTimer) {
      clearTimeout(terminalTimer);
      terminalTimer = null;
    }
    if (terminal) terminal.innerHTML = "";
    var liveClear = document.getElementById("carl4b2b-terminal-live");
    if (liveClear) liveClear.textContent = "";
    if (terminalStatus) terminalStatus.textContent = "ready";

    document.body.classList.remove("carl4b2b-dashboard-active");

    if (hero) hero.classList.remove("hidden");
    if (workspace) {
      workspace.classList.add("hidden");
      workspace.classList.remove("flex");
    }

    var matchesSection = document.getElementById("carl4b2b-matches-section");
    if (matchesSection) {
      matchesSection.classList.add("hidden");
      matchesSection.classList.remove("c4b-reveal-in");
    }
    document.querySelectorAll("[data-c4b-reveal]").forEach(function (el) {
      el.classList.remove("c4b-reveal-in");
    });

    setAnalyzeLoading(false);
    setError("");
    renderProfileSync(null, null);

    resetDashboardMeters();
    if (chatLog) chatLog.innerHTML = "";
    if (chatInput) chatInput.value = "";
    var cc = document.getElementById("carl4b2b-chat-counter");
    if (cc) cc.textContent = "0/280";
    resetChatGate();
    if (chatChips) {
      chatChips.innerHTML = "";
      chatChips.classList.add("hidden");
    }

    initTabs();
    window.scrollTo({ top: 0, behavior: "smooth" });
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
    renderSalaryDrift(analysisState.salaryDrift || null);
    braveRemaining = 3;
    renderBraveCard(true);
    wireBraveButtons();
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
    playTerminal(analysisState.terminalLogs || [], startB2bTerminalLiveFeed);
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
    var urlEl = document.getElementById("carl4b2b-url");
    var titleEl = document.getElementById("carl4b2b-title");
    var countryEl = document.getElementById("carl4b2b-country");
    var excludeEl = document.getElementById("carl4b2b-exclude");
    var businessUrl = urlEl && urlEl.value ? String(urlEl.value).trim() : "";
    var title = titleEl && titleEl.value ? String(titleEl.value).trim() : "";
    var country = countryEl && countryEl.value ? String(countryEl.value).trim() : "";
    var excludeCompany = excludeEl && excludeEl.value ? String(excludeEl.value).trim() : "";
    if (!title && !country && !businessUrl) {
      setError("Enter a role title and country, or a company / careers URL.");
      return;
    }
    if ((title && !country) || (!title && country)) {
      setError("Enter both role title and country, or leave both empty and use a URL only.");
      return;
    }
    setError("");
    stopB2bTerminalLiveFeed();
    setAnalyzeLoading(true);
    var started = performance.now();
    var payload = { business_url: businessUrl };
    if (title && country) {
      payload.title = title;
      payload.country = country;
      if (excludeCompany) payload.exclude_company = excludeCompany;
    }
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

  var btnCarl4b2bNewMap = document.getElementById("btn-carl4b2b-new-map");
  if (btnCarl4b2bNewMap) {
    btnCarl4b2bNewMap.addEventListener("click", function () {
      resetCarl4b2bToFormView();
    });
  }

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
    var skipPreload = false;
    try {
      skipPreload = sessionStorage.getItem("carl4b2b_skip_preload_once") === "1";
      if (skipPreload) sessionStorage.removeItem("carl4b2b_skip_preload_once");
    } catch (eSkip) {}
    if (skipPreload) {
      document.body.classList.remove("carl4b2b-dashboard-active");
      if (hero) hero.classList.remove("hidden");
      if (workspace) {
        workspace.classList.add("hidden");
        workspace.classList.remove("flex");
      }
      return;
    }
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
