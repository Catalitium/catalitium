/* Catalitium — AI Job Summary loader
   Fetches /api/summary/<job_id>, renders bullets + skill pills.
   Works on job_detail.html (single fetch) and index.html (IntersectionObserver for first 3).
*/
(function(){
  'use strict';

  var BULLET_ICONS = [
    /* what you'll do — briefcase */
    '<svg class="w-4 h-4 text-brand flex-shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 7H4a2 2 0 00-2 2v10a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zM16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    /* what you need — check circle */
    '<svg class="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.4"/><path d="M8.5 12.5l2.5 2.5 4-5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    /* what you get — gift */
    '<svg class="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 12v9H4v-9M22 7H2v5h20V7zM12 22V7M12 7H7.5a2.5 2.5 0 010-5C11 2 12 7 12 7zM12 7h4.5a2.5 2.5 0 000-5C13 2 12 7 12 7z" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  ];

  var BULLET_LABELS = ["What you'll do", 'What you need', 'What you get'];

  function escHtml(s){
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function renderSummary(container, data){
    var bullets = (data.bullets || []).slice(0, 3);
    var skills  = (data.skills  || []).slice(0, 8);

    var bulletsHtml = bullets.map(function(b, i){
      return '<div class="flex gap-2.5 items-start mb-2.5">'
        + BULLET_ICONS[i % 3]
        + '<div><p class="text-[11px] font-semibold uppercase tracking-wide text-slate-400 leading-none mb-0.5">'
        + escHtml(BULLET_LABELS[i]) + '</p>'
        + '<p class="text-sm text-slate-700 leading-relaxed">' + escHtml(b) + '</p></div>'
        + '</div>';
    }).join('');

    var skillsHtml = skills.length
      ? '<div class="mt-3 pt-3 border-t border-slate-100 flex flex-wrap gap-1.5">'
        + skills.map(function(s){
          return '<a href="/?title=' + encodeURIComponent(s)
            + '" class="inline-flex items-center rounded-full border border-violet-200 bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-100 transition motion-safe:transition-colors">'
            + escHtml(s) + '</a>';
        }).join('')
        + '</div>'
      : '';

    var skelEl    = container.querySelector('.ai-skeleton');
    var contentEl = container.querySelector('.ai-content');
    if(skelEl) skelEl.classList.add('hidden');
    if(contentEl){
      contentEl.innerHTML = bulletsHtml + skillsHtml;
      contentEl.classList.remove('hidden');
    }
  }

  function fetchSummary(jobId, container){
    fetch('/api/summary/' + jobId, { credentials: 'same-origin' })
      .then(function(r){ if(!r.ok) throw new Error('no_summary'); return r.json(); })
      .then(function(data){ renderSummary(container, data); })
      .catch(function(){
        /* Graceful degradation: silently hide the section */
        if(container) container.classList.add('hidden');
      });
  }

  /* ── job_detail.html: single auto-fetch ── */
  var detailEl = document.getElementById('ai-summary-detail');
  if(detailEl){
    var detailJobId = detailEl.getAttribute('data-job-id');
    if(detailJobId) fetchSummary(detailJobId, detailEl);
  }

  /* ── index.html: lazy-fetch first 3 visible job cards ── */
  if(!detailEl && 'IntersectionObserver' in window){
    var cards = document.querySelectorAll('[data-job-id]');
    var toWatch = Array.prototype.slice.call(cards, 0, 3);
    toWatch.forEach(function(card){
      var jid = card.getAttribute('data-job-id');
      if(!jid) return;
      var obs = new IntersectionObserver(function(entries, self){
        entries.forEach(function(entry){
          if(!entry.isIntersecting) return;
          self.unobserve(entry.target);
          /* Inject a mini-summary slot inside the card */
          var slotId = 'ai-card-sum-' + jid;
          if(!document.getElementById(slotId)){
            var slot = document.createElement('div');
            slot.id = slotId;
            slot.setAttribute('aria-live', 'polite');
            slot.className = 'mt-2';
            slot.innerHTML = '<div class="ai-skeleton flex gap-2 items-center"><div class="h-2 rounded-full bg-slate-100 animate-pulse w-1/2"></div><div class="h-2 rounded-full bg-slate-100 animate-pulse w-1/4"></div></div><div class="ai-content hidden"></div>';
            card.insertBefore(slot, card.querySelector('details'));
          }
          fetchSummary(jid, document.getElementById(slotId));
        });
      }, { threshold: 0.15 });
      obs.observe(card);
    });
  }
})();
