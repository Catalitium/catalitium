(function () {
  var form = document.getElementById("troy-upload-form");
  if (!form) return;

  var uploadBtn = document.getElementById("troy-upload-btn");
  var fileInput = document.getElementById("troy-file-input");
  var textFallback = document.getElementById("troy-text-fallback");
  var errorEl = document.getElementById("troy-upload-error");
  var uploadHero = document.getElementById("troy-upload-hero");
  var workspace = document.getElementById("troy-workspace");
  var terminal = document.getElementById("troy-terminal");
  var terminalStatus = document.getElementById("troy-terminal-status");
  var chatForm = document.getElementById("troy-chat-form");
  var chatInput = document.getElementById("troy-chat-input");
  var chatLog = document.getElementById("troy-chat-log");

  var analysisState = null;
  var terminalTimer = null;

  function csrfToken() {
    var field = form.querySelector('input[name="csrf_token"]');
    return field && field.value ? String(field.value).trim() : "";
  }

  function setUploadLoading(on) {
    if (!uploadBtn) return;
    uploadBtn.disabled = !!on;
    uploadBtn.textContent = on ? "Analyzing…" : "Analyze CV";
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
    var color = p >= 55 ? "#22c55e" : "#FF7A00";
    wrapEl.style.background =
      "conic-gradient(from -90deg, " + color + " 0deg, " + color + " " + deg + "deg, #2a2a2a " + deg + "deg)";
    if (valEl) valEl.textContent = String(Math.round(p));
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
    list.forEach(function (d) {
      var li = document.createElement("li");
      li.className =
        "flex cursor-default items-center gap-3 rounded-lg border border-white/5 bg-[#111] px-3 py-2.5 transition hover:border-white/10";
      var badge =
        d.badge ?
          '<span class="shrink-0 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-400">' +
          escapeHtml(d.badge) +
          "</span>" :
          "";
      li.innerHTML =
        '<span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 text-[#FF7A00]">' +
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
      det.className = "troy-action-details group rounded-lg border border-white/5 bg-[#111] open:border-[#FF7A00]/25";
      det.open = i === 0;
      det.innerHTML =
        '<summary class="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 [&::-webkit-details-marker]:hidden">' +
        '<span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#FF7A00]/15 text-[#FF7A00]">' +
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
    list.forEach(function (item) {
      var score = Number(item.score || 0);
      var row = document.createElement("div");
      row.className = "space-y-1.5";
      row.innerHTML =
        '<div class="flex items-center justify-between text-xs">' +
        '<span class="font-medium text-[#E5E5E5]">' +
        escapeHtml(item.skill || "Skill") +
        "</span>" +
        '<span class="tabular-nums text-[#FF7A00]">' +
        score +
        "</span></div>" +
        '<div class="h-1.5 overflow-hidden rounded-full bg-[#111]">' +
        '<div class="h-full rounded-full bg-gradient-to-r from-[#FF7A00] to-[#22c55e]" style="width:' +
        Math.min(100, Math.max(0, score)) +
        '%"></div></div>';
      root.appendChild(row);
    });
  }

  function vitalClass(v) {
    var n = Number(v) || 0;
    return n >= 60 ? "text-emerald-400" : "text-[#FF7A00]";
  }

  function renderOverview(overview) {
    setText("troy-headline", overview.headline || "Analysis complete");
    setText("troy-fit-summary", overview.fitSummary || "");
    var personaLine = (overview.persona || "—") + " · " + (overview.level || "—");
    setText("troy-persona-line", personaLine);
    setText("troy-level", overview.level || "—");
    setText("troy-confidence", overview.confidence ? overview.confidence + "%" : "—");
    setText("troy-word-count", overview.wordCount != null ? String(overview.wordCount) : "—");

    var scores = overview.signalScores || {};
    var sStruct = scores.structure;
    var sKey = scores.keywords;
    var sImpact = scores.impact;
    var sNarr = scores.narrative;

    setGauge(document.getElementById("troy-gauge-structure"), document.getElementById("troy-gauge-structure-val"), sStruct);
    setGauge(document.getElementById("troy-gauge-keywords"), document.getElementById("troy-gauge-keywords-val"), sKey);

    setVital("troy-vital-structure", sStruct);
    setVital("troy-vital-keywords", sKey);
    setVital("troy-vital-impact", sImpact);
    setVital("troy-vital-narrative", sNarr);
  }

  function setVital(id, v) {
    var el = document.getElementById(id);
    if (!el) return;
    var n = Math.round(Number(v) || 0);
    el.textContent = String(n);
    el.className = "mt-1 text-lg font-semibold tabular-nums " + vitalClass(n);
  }

  function renderAts(ats) {
    setText("troy-ats-score", String(ats.score || 0));
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
      clearInterval(terminalTimer);
      terminalTimer = null;
    }
    terminal.innerHTML = "";
    var lines = safeList(logs, ["> [TROY] no terminal lines"]);
    var index = 0;
    if (terminalStatus) terminalStatus.textContent = "Streaming";
    terminalTimer = setInterval(function () {
      var row = document.createElement("div");
      row.className = "whitespace-pre-wrap border-l-2 border-[#FF7A00]/30 pl-2";
      row.textContent = "> " + lines[index];
      terminal.appendChild(row);
      terminal.scrollTop = terminal.scrollHeight;
      index += 1;
      if (index >= lines.length) {
        clearInterval(terminalTimer);
        terminalTimer = null;
        if (terminalStatus) terminalStatus.textContent = "Complete";
      }
    }, 280);
  }

  function addChatMessage(role, text) {
    if (!chatLog) return;
    var item = document.createElement("div");
    var isUser = role === "user";
    item.className = isUser
      ? "ml-6 rounded-xl border border-[#FF7A00]/35 bg-[#FF7A00]/12 px-3 py-2 text-sm text-white"
      : "mr-2 rounded-xl border border-white/10 bg-[#0D0D0D] px-3 py-2 text-sm leading-relaxed text-[#E5E5E5]";
    item.textContent = text;
    chatLog.appendChild(item);
    chatLog.scrollTop = chatLog.scrollHeight;
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

  function hydrateDashboard(analysis) {
    analysisState = analysis || {};
    document.body.classList.add("troy-dashboard-active");
    if (uploadHero) uploadHero.classList.add("hidden");
    if (workspace) {
      workspace.classList.remove("hidden");
      workspace.classList.add("flex");
    }

    renderOverview(analysisState.overview || {});
    renderAts(analysisState.atsScore || {});
    renderSkills(analysisState.skillsRadar || []);
    renderDocuments(analysisState.documents || []);
    renderActions(analysisState.actionFeed || []);

    renderList("troy-timeline", analysisState.experienceTimeline, function (item) {
      return (
        '<span class="font-semibold text-[#FF7A00]">' +
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
    playTerminal(analysisState.terminalLogs || []);
    initTabs();
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    setError("");
    setUploadLoading(true);

    var payload = new FormData(form);
    fetch("/troy/analyze", {
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
          throw new Error((result.data && result.data.message) || "Could not analyze CV.");
        }
        var analysis = result.data.data && result.data.data.analysis;
        if (!analysis) throw new Error("Analysis payload missing.");
        hydrateDashboard(analysis);
      })
      .catch(function (err) {
        setError(err && err.message ? err.message : "Could not analyze CV. Please try again.");
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
      addChatMessage("user", message);
      if (chatInput) chatInput.value = "";

      fetch("/troy/chat", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({
          message: message,
          chat_context: analysisState.chatContext || {},
          missing_keywords: (analysisState.atsScore && analysisState.atsScore.missingKeywords) || [],
        }),
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
            throw new Error((result.data && result.data.message) || "Unable to send chat message.");
          }
          var reply = result.data.data && result.data.data.reply;
          addChatMessage("assistant", reply || "I can help with ATS, strengths, or rewrite suggestions.");
        })
        .catch(function () {
          addChatMessage("assistant", "Temporary chat issue. Ask again in a moment.");
        });
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
