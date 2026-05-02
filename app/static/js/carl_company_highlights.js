/* Shared B2C Carl + Carl4B2B: context ribbon + directory spotlight strip. */
(function (global) {
  "use strict";

  function esc(t) {
    return String(t || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderCompanyHighlights(prefix, analysis) {
    var root = document.getElementById(prefix + "-company-highlights");
    if (!root) return;
    var cs = (analysis && analysis.companies_summary) || {};
    var sample = cs.sample_rows != null ? Number(cs.sample_rows) : 0;
    if (!sample) {
      root.classList.add("hidden");
      return;
    }
    root.classList.remove("hidden");

    var ribbon = document.getElementById(prefix + "-company-context-ribbon");
    if (ribbon) {
      ribbon.textContent = cs.context_ribbon ? String(cs.context_ribbon) : "";
    }

    var stripWrap = document.getElementById(prefix + "-company-spotlight-wrap");
    var strip = document.getElementById(prefix + "-company-spotlight-strip");
    var tailEl = document.getElementById(prefix + "-company-spotlight-tail");
    var foot = document.getElementById(prefix + "-company-highlights-footnote");
    var empty = document.getElementById(prefix + "-company-highlights-empty");
    var spot = (analysis && analysis.spotlight_employers) || [];
    var matched = cs.total_matched != null ? Number(cs.total_matched) : 0;

    if (empty) {
      if (matched < 1) {
        empty.classList.remove("hidden");
        if (foot) foot.classList.add("hidden");
      } else {
        empty.classList.add("hidden");
        if (foot) foot.classList.remove("hidden");
      }
    }

    if (!stripWrap || !strip) return;
    if (!spot.length) {
      stripWrap.classList.add("hidden");
      strip.innerHTML = "";
      if (tailEl) {
        tailEl.classList.add("hidden");
        tailEl.textContent = "";
      }
      return;
    }
    stripWrap.classList.remove("hidden");
    strip.innerHTML = "";
    var tileClass =
      prefix === "carl4b2b"
        ? "rounded-xl border border-white/10 bg-white/[0.04] p-3 transition hover:border-sky-400/40 focus-within:ring-1 focus-within:ring-sky-500/40"
        : "rounded-xl border border-[#214f86]/50 bg-[#0b1324]/80 p-3 transition hover:border-[#2b71b8] focus-within:ring-1 focus-within:ring-[#18a7ec]/35";

    spot.forEach(function (s) {
      var a = document.createElement("a");
      a.href = s.link || "#";
      a.className = "block min-w-0 flex-1 sm:max-w-[220px] " + tileClass;
      var title = esc(s.name || "Employer");
      var meta = [];
      if (s.industry_bucket) meta.push(esc(s.industry_bucket));
      if (s.company_region) meta.push(esc(s.company_region));
      if (s.headcount_band) meta.push(esc(s.headcount_band) + " employees");
      if (s.page_score != null && s.page_score !== "") meta.push("score " + esc(String(s.page_score)));
      var subColor = prefix === "carl4b2b" ? "text-slate-400" : "text-[#A7B8D7]";
      a.innerHTML =
        '<p class="text-sm font-semibold text-white leading-tight">' +
        title +
        "</p>" +
        '<p class="mt-1 text-[10px] ' +
        subColor +
        ' leading-snug">' +
        (meta.length ? meta.join(" · ") : "Directory match") +
        "</p>";
      strip.appendChild(a);
    });

    var more = cs.spotlight_more_count != null ? Number(cs.spotlight_more_count) : 0;
    if (tailEl && more > 0) {
      tailEl.textContent = "+" + more + " more directory-linked employers in this sample.";
      tailEl.classList.remove("hidden");
    } else if (tailEl) {
      tailEl.classList.add("hidden");
      tailEl.textContent = "";
    }
  }

  global.CarlCompanyHighlights = { render: renderCompanyHighlights };
})(typeof window !== "undefined" ? window : this);
