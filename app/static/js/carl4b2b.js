(function () {
  var form = document.getElementById("carl4b2b-market-form");
  if (!form) return;
  document.body.classList.add("carl4b2b-page");

  var c4bShell = document.getElementById("carl4b2b-shell");
  var fallbackJobsHref = (c4bShell && c4bShell.getAttribute("data-fallback-jobs-href")) || "/jobs";

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
  var analyzeTextEl = document.getElementById("carl4b2b-analyze-text");

  var analysisState = null;

  function buildC4bJobsHref(mm) {
    mm = mm || {};
    try {
      var u = new URL(fallbackJobsHref, window.location.origin);
      if (mm.title_q) u.searchParams.set("title", String(mm.title_q));
      if (mm.country_q) u.searchParams.set("country", String(mm.country_q));
      return u.pathname + (u.search || "");
    } catch (eB) {
      return fallbackJobsHref;
    }
  }

  function syncC4bJobsSearchLink() {
    var el = document.getElementById("carl4b2b-matches-jobs-search");
    if (!el) return;
    var mm = (analysisState && analysisState.marketMeta) || {};
    el.setAttribute("href", buildC4bJobsHref(mm));
  }

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

  function hasUrlInput() {
    var urlEl = document.getElementById("carl4b2b-url");
    return !!(urlEl && String(urlEl.value || "").trim());
  }

  function updateCtaFromUrl() {
    if (!analyzeTextEl) return;
    analyzeTextEl.textContent = hasUrlInput() ? "Map this company" : "Map this market";
  }

  var urlHintsTimer = null;
  var urlDirectoryMatched = false;
  var DEFAULT_REFINE_REGION = "Global";

  function updateFieldsRowVisibility() {
    var row = document.getElementById("carl4b2b-fields-row");
    if (!row) return;
    var show = !hasUrlInput() || !urlDirectoryMatched;
    row.classList.toggle("hidden", !show);
  }

  function setDirectoryHint(msg) {
    var el = document.getElementById("carl4b2b-directory-hint");
    if (!el) return;
    if (!msg) {
      el.textContent = "";
      el.classList.add("hidden");
      return;
    }
    el.textContent = msg;
    el.classList.remove("hidden");
  }

  function scheduleDirectoryLookup() {
    if (urlHintsTimer) clearTimeout(urlHintsTimer);
    urlHintsTimer = setTimeout(runDirectoryLookup, 300);
  }

  function runDirectoryLookup() {
    if (!hasUrlInput()) {
      setDirectoryHint("");
      urlDirectoryMatched = false;
      updateFieldsRowVisibility();
      return;
    }
    var urlEl = document.getElementById("carl4b2b-url");
    if (!urlEl) return;
    var raw = String(urlEl.value || "").trim();
    if (!raw) {
      setDirectoryHint("");
      urlDirectoryMatched = false;
      updateFieldsRowVisibility();
      return;
    }
    var probe = raw;
    if (!/^https?:\/\//i.test(probe)) probe = "https://" + probe;
    try {
      var parsedProbe = new URL(probe);
      if (!parsedProbe.hostname) throw new Error("host");
    } catch (eP) {
      setDirectoryHint("");
      urlDirectoryMatched = false;
      updateFieldsRowVisibility();
      return;
    }
    var q = encodeURIComponent(raw.length > 2048 ? raw.slice(0, 2048) : raw);
    fetch("/carl/b2b/url-hints?url=" + q, { credentials: "same-origin" })
      .then(function (r) {
        return r
          .json()
          .catch(function () {
            return {};
          });
      })
      .then(function (env) {
        if (!hasUrlInput()) return;
        if (!env || env.ok !== true || !env.data) {
          urlDirectoryMatched = false;
          updateFieldsRowVisibility();
          return;
        }
        var hints = env.data.hints;
        if (!hints) {
          setDirectoryHint("");
          urlDirectoryMatched = false;
          updateFieldsRowVisibility();
          return;
        }
        var hasSignal = !!(hints.comp_name || hints.industry || hints.region);
        if (!hasSignal) {
          setDirectoryHint("");
          urlDirectoryMatched = false;
          updateFieldsRowVisibility();
          return;
        }
        urlDirectoryMatched = true;
        var refT = document.getElementById("carl4b2b-refine-title");
        var refC = document.getElementById("carl4b2b-refine-country");
        if (refT) refT.value = "";
        if (refC) refC.value = DEFAULT_REFINE_REGION;
        updateFieldsRowVisibility();
        var parts = [];
        if (hints.comp_name) parts.push(String(hints.comp_name));
        if (hints.industry) parts.push(String(hints.industry));
        if (hints.region) parts.push(String(hints.region));
        if (parts.length) {
          setDirectoryHint("Recognized: " + parts.join(" · "));
        }
      })
      .catch(function () {
        urlDirectoryMatched = false;
        updateFieldsRowVisibility();
      });
  }

  function setAnalyzeLoading(on) {
    if (!analyzeBtn) return;
    analyzeBtn.disabled = !!on;
    var sp = document.getElementById("carl4b2b-analyze-spinner");
    if (sp) sp.classList.toggle("hidden", !on);
    if (analyzeTextEl) {
      if (on) {
        analyzeTextEl.textContent = "Mapping catalog…";
      } else {
        updateCtaFromUrl();
      }
    }
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
      errEl.innerHTML = "";
      return;
    }
    errEl.innerHTML = "";
    errEl.textContent = msg;
    errEl.classList.remove("hidden");
  }

  function setSignupRequiredMarketError(registerUrl) {
    if (!errEl) return;
    var href = registerUrl || "/register";
    errEl.innerHTML =
      '<p class="text-sm text-amber-100/95">' +
      escapeHtml(
        "You've reached this session's free market maps. Create a free account to keep mapping and save snapshots."
      ) +
      '</p><p class="mt-2"><a href="' +
      escapeHtml(href) +
      '" class="font-semibold text-sky-300 underline underline-offset-2 hover:text-white">Create an account</a></p>';
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

  function pageScoreChipHtml(jobMeta) {
    jobMeta = jobMeta || {};
    var ps = jobMeta.page_score;
    var matched = !!jobMeta.directory_match;
    if (ps != null && ps !== "") {
      var n = Number(ps);
      if (!isNaN(n)) {
        var band = "border-slate-500/40 bg-slate-900/60 text-slate-300";
        if (n >= 0.7) band = "border-emerald-500/35 bg-emerald-950/40 text-emerald-200";
        else if (n >= 0.4) band = "border-amber-500/35 bg-amber-950/35 text-amber-200";
        return (
          '<span class="inline-flex rounded-full border ' +
          band +
          ' px-2 py-0.5 text-[10px] font-medium tabular-nums" title="Employer profile strength (directory page_score)">Score ' +
          escapeHtml(String(n)) +
          "</span>"
        );
      }
    }
    if (matched) {
      return (
        '<span class="inline-flex rounded-full border border-slate-600/40 bg-slate-950/50 px-2 py-0.5 text-[10px] text-slate-500" title="Matched to directory; no page_score on file">Profile score —</span>'
      );
    }
    return "";
  }

  function jobCompanyChipsHtml(jobMeta) {
    if (!jobMeta) return "";
    var parts = [];
    if (jobMeta.industry_bucket) {
      parts.push(
        '<span class="inline-flex rounded-full border border-sky-500/30 bg-slate-950/60 px-2 py-0.5 text-[10px] text-sky-100">' +
          escapeHtml(jobMeta.industry_bucket) +
          "</span>"
      );
    }
    var psc = pageScoreChipHtml(jobMeta);
    if (psc) parts.push(psc);
    if (jobMeta.is_global) {
      parts.push(
        '<span class="inline-flex rounded-full border border-emerald-500/35 bg-emerald-950/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-200">Global</span>'
      );
    }
    if (!parts.length) return "";
    return '<div class="mt-2 flex flex-wrap gap-1.5">' + parts.join("") + "</div>";
  }

  function renderCompaniesKpi(cs) {
    var block = document.getElementById("carl4b2b-companies-kpi-block");
    if (!block) return;
    cs = cs || {};
    var sample = cs.sample_rows != null ? Number(cs.sample_rows) : 0;
    if (!sample) {
      block.classList.add("hidden");
      return;
    }
    block.classList.remove("hidden");
    var matched = cs.total_matched != null ? Number(cs.total_matched) : 0;
    var elMatch = document.getElementById("carl4b2b-kpi-companies-matched");
    var elLbl = document.getElementById("carl4b2b-kpi-companies-matched-label");
    if (elLbl) elLbl.textContent = "Matched rows (sample " + sample + ")";
    if (elMatch) elMatch.textContent = String(matched);
    var elMr = document.getElementById("carl4b2b-kpi-match-rate");
    if (elMr) {
      elMr.textContent =
        cs.match_rate_pct != null && cs.match_rate_pct !== ""
          ? String(cs.match_rate_pct) + "%"
          : "—";
    }
    var pg = document.getElementById("carl4b2b-kpi-pct-global");
    if (pg) {
      pg.textContent =
        cs.pct_global != null && cs.pct_global !== "" ? String(cs.pct_global) + "%" : "—";
    }
    var av = document.getElementById("carl4b2b-kpi-avg-score");
    if (av) {
      av.textContent =
        cs.avg_page_score != null && cs.avg_page_score !== "" ? String(cs.avg_page_score) : "—";
    }
    var sp = document.getElementById("carl4b2b-kpi-score-spread");
    if (sp) {
      var mn = cs.min_page_score,
        mx = cs.max_page_score,
        md = cs.median_page_score;
      if (mn != null && md != null && mx != null && mn !== "" && md !== "" && mx !== "") {
        sp.textContent = String(mn) + " · " + String(md) + " · " + String(mx);
      } else if (mn != null && mx != null && mn !== "" && mx !== "") {
        sp.textContent = String(mn) + "–" + String(mx);
      } else {
        sp.textContent = "—";
      }
    }
    var ti = document.getElementById("carl4b2b-kpi-top-industry");
    if (ti) ti.textContent = cs.top_industry ? String(cs.top_industry) : "—";
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
      root.innerHTML = '<p class="text-xs text-slate-500">No employers in this sample.</p>';
      return;
    }
    list.forEach(function (item, i) {
      var score = Number(item.score || 0);
      var posts = item.post_count != null ? Number(item.post_count) : null;
      var intensity = (item.intensity_label || "").trim();
      var right = [];
      if (intensity) right.push(intensity);
      if (posts != null && !isNaN(posts)) right.push(posts + " posts");
      var row = document.createElement("div");
      row.className = "c4b-animate-row space-y-1.5";
      row.style.animationDelay = i * ROW_STAGGER_SKILL_MS + "ms";
      row.innerHTML =
        '<div class="flex items-center justify-between gap-2 text-xs">' +
        '<span class="min-w-0 font-medium text-slate-200">' +
        escapeHtml(item.skill || "Employer") +
        "</span>" +
        '<span class="shrink-0 tabular-nums text-amber-300">' +
        escapeHtml(right.length ? right.join(" · ") : String(score)) +
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

  function setMetricPercent(id, v) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = String(Math.round(Number(v) || 0)) + "%";
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
    setMetricPercent("carl4b2b-metric-leadership", premium.leadership);
    setMetricPercent("carl4b2b-metric-role-match", premium.roleMatch);
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
    setText("carl4b2b-metric-leadership", "—");
    setText("carl4b2b-metric-role-match", "—");
    setText("carl4b2b-metric-evidence", "—");
  }

  function renderAts(ats, skipScore) {
    var bp = (analysisState && analysisState.b2bPanel) || {};
    var mm = (analysisState && analysisState.marketMeta) || {};
    var hero = bp.kpi_sample_rows != null ? Number(bp.kpi_sample_rows) : Math.round(Number((ats && ats.score) || 0));
    if (!skipScore) setText("carl4b2b-ats-score", String(hero));
    var cat = bp.kpi_catalog_total != null ? bp.kpi_catalog_total : mm.total_count;
    var cap = bp.kpi_sample_cap != null ? bp.kpi_sample_cap : mm.sample_cap;
    var pulled = bp.kpi_sample_rows != null ? bp.kpi_sample_rows : mm.sample_rows;
    var scope = bp.scope_line || [mm.title_q || "—", mm.country_q || "—"].filter(Boolean).join(" · ");
    setText(
      "carl4b2b-ats-coverage",
      "Scope: " +
        scope +
        " · Catalog " +
        (cat != null ? String(cat) : "—") +
        " postings · pulled " +
        (pulled != null ? String(pulled) : "—") +
        "/" +
        (cap != null ? String(cap) : "—") +
        " · spread " +
        (ats.keywordCoverage != null ? String(ats.keywordCoverage) : "—") +
        "% distinct hirers vs rows"
    );
    setText("carl4b2b-keywords-hit", safeList(ats.matchedKeywords, ["—"]).join(", "));
    var missParts = safeList(ats.missingKeywords, []);
    setText("carl4b2b-keywords-missing", missParts.length ? missParts.join(", ") : "No coverage flags");
  }

  function renderB2bAnalyticsChrome() {
    var bp = (analysisState && analysisState.b2bPanel) || {};
    var mm = (analysisState && analysisState.marketMeta) || {};
    var scope =
      bp.scope_line ||
      [mm.title_q || "", mm.country_q || ""].filter(Boolean).join(" · ") ||
      "";
    setText("carl4b2b-analytics-scope", scope ? "Industry · Region: " + scope : "");
    var rs = document.getElementById("carl4b2b-risks-scope");
    if (rs) rs.textContent = scope ? "Scoped to: " + scope + "." : "";
    var ss = document.getElementById("carl4b2b-skills-scope");
    if (ss)
      ss.textContent = scope
        ? "Posting intensity (High / Medium / Low) is relative to this pulled sample for " + scope + "."
        : "";
    var na = document.getElementById("carl4b2b-next-actions");
    if (na) {
      na.innerHTML = "";
      safeList(bp.next_actions, []).forEach(function (line) {
        var li = document.createElement("li");
        li.textContent = line;
        na.appendChild(li);
      });
    }
    var bh = document.getElementById("carl4b2b-brave-scope-hint");
    if (bh) {
      var t = mm.title_q || "";
      var c = mm.country_q || "";
      bh.textContent =
        t || c
          ? "Pins must stay relevant to " + (t || "your industry") + " in " + (c || "your region") + "."
          : "";
    }
  }

  function renderMarketFooter(mm) {
    var wrap = document.getElementById("carl4b2b-catalog-footer");
    var line = document.getElementById("carl4b2b-footer-metrics-line");
    var dem = document.getElementById("carl4b2b-candidate-demand");
    if (!wrap || !line) return;
    if (!mm || mm.total_count == null) {
      wrap.classList.add("hidden");
      line.textContent = "";
      if (dem) {
        dem.textContent = "";
        dem.classList.add("hidden");
      }
      return;
    }
    var parts = [];
    parts.push("Catalog total postings (filtered): " + String(mm.total_count));
    parts.push("Sample rows pulled: " + String(mm.sample_rows != null ? mm.sample_rows : "—"));
    parts.push("Sample cap: " + String(mm.sample_cap != null ? mm.sample_cap : "—"));
    parts.push("Distinct employers in sample: " + String(mm.distinct_employers_sample != null ? mm.distinct_employers_sample : "—"));
    if (mm.title_q) parts.push("Title filter: " + mm.title_q);
    if (mm.country_q) parts.push("Geo filter: " + mm.country_q);
    if (mm.exclude_company && String(mm.exclude_company).trim()) {
      parts.push('Exclude substring: "' + String(mm.exclude_company).trim() + '"');
    }
    line.textContent = parts.join(" · ");
    wrap.classList.remove("hidden");
    if (dem) {
      var ds = mm.demandSignal;
      if (ds && ds.count != null && Number(ds.count) > 0) {
        var w = ds.window_days != null ? String(ds.window_days) : "90";
        dem.textContent = "Candidate demand (" + w + "d): " + String(ds.count) + " profiles";
        dem.classList.remove("hidden");
      } else {
        dem.textContent = "";
        dem.classList.add("hidden");
      }
    }
  }

  function renderExecSummary(overview) {
    var wrap = document.getElementById("carl4b2b-exec-summary-wrap");
    var el = document.getElementById("carl4b2b-exec-summary");
    if (!wrap || !el) return;
    var h = (overview && overview.headline) || "";
    var fs = (overview && overview.fitSummary) || "";
    var text = [h, fs].filter(Boolean).join("\n\n");
    if (!text.trim()) {
      wrap.classList.add("hidden");
      el.textContent = "";
      return;
    }
    el.textContent = text;
    wrap.classList.remove("hidden");
  }

  function buildStakeholderSummary() {
    if (!analysisState) return "";
    var mm = analysisState.marketMeta || {};
    var ov = analysisState.overview || {};
    var lines = [];
    lines.push("Carl B2B — market map (Catalitium catalog)");
    lines.push("");
    lines.push(ov.headline || "");
    lines.push(ov.fitSummary || "");
    lines.push("");
    lines.push(
      "Catalog total: " +
        String(mm.total_count != null ? mm.total_count : "—") +
        " · Sample: " +
        String(mm.sample_rows != null ? mm.sample_rows : "—") +
        "/" +
        String(mm.sample_cap != null ? mm.sample_cap : "—") +
        " rows · Distinct employers in sample: " +
        String(mm.distinct_employers_sample != null ? mm.distinct_employers_sample : "—")
    );
    if (mm.title_q) lines.push("Title: " + mm.title_q);
    if (mm.country_q) lines.push("Geo: " + mm.country_q);
    if (mm.exclude_company && String(mm.exclude_company).trim()) {
      lines.push("Exclude: " + String(mm.exclude_company).trim());
    }
    var comps = ((analysisState.matches || {}).top_companies) || [];
    if (comps.length) {
      lines.push("");
      lines.push("Top hirers (sample intensity):");
      comps.slice(0, 8).forEach(function (c) {
        var tier = c.intensity_label || "";
        var cnt = c.post_count != null ? c.post_count : "";
        lines.push("- " + (c.name || "") + " · " + tier + " · " + cnt + " postings in sample");
      });
    }
    lines.push("");
    lines.push("Full JSON export available from dashboard.");
    return lines.join("\n");
  }

  function copySummaryToClipboard() {
    var text = buildStakeholderSummary();
    if (!text) return;
    function fallback() {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } catch (e) {}
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(fallback);
    } else {
      fallback();
    }
  }

  function exportAnalysisJson() {
    if (!analysisState) return;
    try {
      var blob = new Blob([JSON.stringify(analysisState, null, 2)], { type: "application/json" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = "carl-b2b-market-map-" + new Date().toISOString().slice(0, 19).replace(/:/g, "") + ".json";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {}
  }

  function renderSalaryDrift(drift) {
    var card = document.getElementById("carl4b2b-salary-drift-card");
    if (!card) return;
    if (!drift || !drift.status) {
      card.classList.add("hidden");
      return;
    }
    var scopePrefix = drift.scope_context ? String(drift.scope_context) + " — " : "";
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
      if (labelEl) labelEl.textContent = "Insufficient listings for pay drift";
      if (noteEl)
        noteEl.textContent =
          scopePrefix + (drift.note || "Not enough salary + date rows in this pulled sample.");
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
    if (noteEl) noteEl.textContent = scopePrefix + (drift.note || "");
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
      var host = "";
      try {
        host = new URL(String(it.url || "")).hostname;
      } catch (eH) {
        host = "";
      }
      var cite = document.createElement("p");
      cite.className = "mb-1 font-mono text-[10px] text-slate-500";
      cite.textContent = (host || "web") + " · external source";
      li.appendChild(cite);
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
    var bp = (analysisState && analysisState.b2bPanel) || {};
    var atsScore =
      bp.kpi_sample_rows != null
        ? Math.round(Number(bp.kpi_sample_rows))
        : Math.round(Number((ats && ats.score) || 0));
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
    setMetricPercent("carl4b2b-metric-leadership", premium.leadership);
    setMetricPercent("carl4b2b-metric-role-match", premium.roleMatch);
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
    addOne("Slice: " + (mm.title_q || "") + " · " + (mm.country_q || "—"));
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
      addOne("Run ready — try prompts in chat or the terminal feed.");
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
    function card(title, subtitle, href, ghost, jobMeta) {
      return (
        '<div class="rounded-2xl border border-white/10 bg-white/[0.03] p-4">' +
        '<div class="flex items-start justify-between gap-2">' +
        '<p class="text-sm font-bold text-white">' + escapeHtml(title) + "</p>" +
        ghostBadgeHtml(ghost) +
        "</div>" +
        '<p class="mt-1 text-xs text-slate-400">' + escapeHtml(subtitle) + "</p>" +
        jobCompanyChipsHtml(jobMeta) +
        '<a href="' + escapeHtml(href || fallbackJobsHref) + '"' +
        ' class="mt-3 inline-flex text-xs font-semibold text-sky-400 hover:text-white">Open →</a></div>'
      );
    }
    safeList(matches.jobs, []).forEach(function (j) {
      jRoot.innerHTML += card(j.title, (j.company || "") + " · " + (j.location || ""), j.link, j.ghost, j);
    });
    safeList(matches.top_companies, []).forEach(function (c) {
      var tier = c.intensity_label ? String(c.intensity_label) + " intensity · " : "";
      var pc = c.post_count != null ? String(c.post_count) + " postings in sample · " : "";
      var sub = tier + pc + (c.reason || "");
      cRoot.innerHTML += card(c.name, sub, fallbackJobsHref);
    });
    safeList(matches.niche_companies, []).forEach(function (n) {
      nRoot.innerHTML += card(n.name, n.reason || "", fallbackJobsHref);
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

  var c4bTabsClickBound = false;
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
    if (!c4bTabsClickBound) {
      c4bTabsClickBound = true;
      tabs.forEach(function (btn) {
        btn.addEventListener("click", function () {
          activate(btn.getAttribute("data-c4b-tab") || "overview");
        });
      });
    }
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
    var tsReset = document.getElementById("carl4b2b-term-slice");
    if (tsReset) {
      tsReset.textContent = "";
      tsReset.classList.add("hidden");
    }

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
    var shareRowR = document.getElementById("carl4b2b-share-row");
    if (shareRowR) shareRowR.classList.add("hidden");
    var execW = document.getElementById("carl4b2b-exec-summary-wrap");
    if (execW) {
      execW.classList.add("hidden");
      var execEl = document.getElementById("carl4b2b-exec-summary");
      if (execEl) execEl.textContent = "";
    }
    var foot = document.getElementById("carl4b2b-catalog-footer");
    if (foot) {
      foot.classList.add("hidden");
      var fl = document.getElementById("carl4b2b-footer-metrics-line");
      if (fl) fl.textContent = "";
    }
    document.querySelectorAll("[data-c4b-reveal]").forEach(function (el) {
      el.classList.remove("c4b-reveal-in");
    });

    setAnalyzeLoading(false);
    setError("");
    renderProfileSync(null, null);

    resetDashboardMeters();
    setText("carl4b2b-analytics-scope", "");
    var ck = document.getElementById("carl4b2b-companies-kpi-block");
    if (ck) {
      ck.classList.add("hidden");
      ["carl4b2b-kpi-companies-matched", "carl4b2b-kpi-pct-global", "carl4b2b-kpi-avg-score", "carl4b2b-kpi-top-industry"].forEach(
        function (kid) {
          var el = document.getElementById(kid);
          if (el) el.textContent = "—";
        }
      );
      var lb = document.getElementById("carl4b2b-kpi-companies-matched-label");
      if (lb) lb.textContent = "Matched rows";
    }
    setText("carl4b2b-risks-scope", "");
    setText("carl4b2b-skills-scope", "");
    setText("carl4b2b-brave-scope-hint", "");
    var naClear = document.getElementById("carl4b2b-next-actions");
    if (naClear) naClear.innerHTML = "";
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
    if (hero) {
      try {
        hero.scrollIntoView({ block: "start", behavior: "smooth" });
      } catch (eH) {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
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
    renderB2bAnalyticsChrome();
    renderSalaryDrift(analysisState.salaryDrift || null);
    renderCompaniesKpi(analysisState.companies_summary || null);
    if (window.CarlCompanyHighlights) {
      window.CarlCompanyHighlights.render("carl4b2b", analysisState);
    }
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
        (analysisState.chatContext && analysisState.chatContext.summary) ||
          "This run is ready. Use a quick prompt or type your own question about this slice."
      );
    }
    var termSlice = document.getElementById("carl4b2b-term-slice");
    if (termSlice) {
      var mmx = (analysisState.marketMeta || {});
      var pz = [];
      if (mmx.business_url) {
        try {
          var ux = new URL(mmx.business_url);
          pz.push(ux.hostname || mmx.business_url);
        } catch (eU) {
          pz.push(String(mmx.business_url).slice(0, 64));
        }
      }
      if (mmx.market_company) pz.push(String(mmx.market_company));
      if (mmx.title_q) pz.push(String(mmx.title_q));
      if (mmx.country_q) pz.push(String(mmx.country_q));
      var line2 = pz.filter(Boolean).join(" · ");
      if (line2) {
        termSlice.textContent = "Slice: " + line2;
        termSlice.classList.remove("hidden");
      } else {
        termSlice.classList.add("hidden");
      }
    }
    resetChatGate();
    renderSuggestedChips((analysisState.chatContext && analysisState.chatContext.suggestedPrompts) || []);
    renderExecSummary(analysisState.overview || {});
    renderMarketFooter(analysisState.marketMeta || {});
    syncC4bJobsSearchLink();
    var shareRow = document.getElementById("carl4b2b-share-row");
    if (shareRow) shareRow.classList.remove("hidden");
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
        addChatMessage("assistant", inner.reply || "No reply. Ask about this run or retry.");
        if (inner.chat_limit_reached) applyChatLimit(inner);
      })
      .catch(function () {
        addChatMessage("assistant", "Temporary issue. Try again shortly.");
      });
  }

  function deriveMarketCompany(titleStr, businessUrlNorm) {
    var t = titleStr && String(titleStr).trim();
    if (t) return t.length > 64 ? t.slice(0, 64) : t;
    if (businessUrlNorm) {
      try {
        var pu = new URL(businessUrlNorm);
        var h = String(pu.hostname || "").replace(/^www\./i, "");
        if (h) return h.length > 64 ? h.slice(0, 64) : h;
      } catch (eMc) {}
    }
    return "Market";
  }

  var urlElHints = document.getElementById("carl4b2b-url");
  if (urlElHints) {
    urlElHints.addEventListener("input", function () {
      setDirectoryHint("");
      urlDirectoryMatched = false;
      updateFieldsRowVisibility();
      updateCtaFromUrl();
      scheduleDirectoryLookup();
    });
    urlElHints.addEventListener("blur", function () {
      scheduleDirectoryLookup();
    });
  }
  updateCtaFromUrl();
  updateFieldsRowVisibility();

  var btnCopySummary = document.getElementById("btn-c4b-copy-summary");
  if (btnCopySummary) {
    btnCopySummary.addEventListener("click", function () {
      copySummaryToClipboard();
    });
  }
  var btnExportJson = document.getElementById("btn-c4b-export-json");
  if (btnExportJson) {
    btnExportJson.addEventListener("click", function () {
      exportAnalysisJson();
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var urlEl = document.getElementById("carl4b2b-url");
    var refT = document.getElementById("carl4b2b-refine-title");
    var refC = document.getElementById("carl4b2b-refine-country");
    var businessUrlRaw = urlEl && urlEl.value ? String(urlEl.value).trim() : "";
    var title = refT && refT.value ? String(refT.value).trim() : "";
    var region = refC && refC.value ? String(refC.value).trim() : "";
    if (!region) region = DEFAULT_REFINE_REGION;

    var businessUrlNorm = "";
    if (businessUrlRaw) {
      var norm = businessUrlRaw;
      if (!/^https?:\/\//i.test(norm)) norm = "https://" + norm;
      try {
        var parsed = new URL(norm);
        if (!parsed.hostname) throw new Error("host");
        businessUrlNorm = parsed.href;
      } catch (eUrl) {
        setError("Enter a valid URL (we accept example.com or https://example.com).");
        return;
      }
    }

    if (!businessUrlNorm && !title) {
      setError("Enter a URL or choose an industry to continue.");
      return;
    }

    var omitRefinements = !!(businessUrlNorm && urlDirectoryMatched);
    var payload = {
      market_company: deriveMarketCompany(omitRefinements ? "" : title, businessUrlNorm || null),
    };
    if (businessUrlNorm) payload.business_url = businessUrlNorm;
    if (!omitRefinements) {
      if (title) payload.title = title;
      payload.country = region;
    }

    setError("");
    stopB2bTerminalLiveFeed();
    setAnalyzeLoading(true);
    var started = performance.now();
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
          var failCode = result.data && result.data.code;
          if (failCode === "signup_required") {
            var det = (result.data && result.data.details) || {};
            var regUrl = det.register_url || "/register";
            var signupErr = new Error("signup_required");
            signupErr.carl4b2bSignupRequired = true;
            signupErr.registerUrl = regUrl;
            throw signupErr;
          }
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
        var guestRem =
          inner.guest_analyzes_remaining !== undefined && inner.guest_analyzes_remaining !== null ?
            Number(inner.guest_analyzes_remaining) :
            null;
        var elapsed = performance.now() - started;
        var remain = Math.max(0, MIN_ANALYZE_MS - elapsed);
        return delay(remain).then(function () {
          return { analysis: analysis, extras: extras, guestRemaining: guestRem };
        });
      })
      .then(function (pack) {
        hydrate(pack.analysis, pack.extras);
        if (pack.guestRemaining !== null && !Number.isNaN(pack.guestRemaining)) {
          var bc = document.getElementById("carl4b2b-guest-banner-count");
          if (bc) bc.textContent = String(pack.guestRemaining);
        }
      })
      .catch(function (err) {
        if (err && err.carl4b2bSignupRequired) {
          setSignupRequiredMarketError(err.registerUrl);
        } else {
          setError(err && err.message ? err.message : "Request failed.");
        }
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
