/* Catalitium — Application Tracker (localStorage Kanban)
   Zero backend. All data lives in localStorage key: catalitium_tracker_v1
*/
(function(){
  'use strict';

  var STORE = 'catalitium_tracker_v1';

  var STAGES = [
    { id: 'applied',      label: 'Applied',       color: 'blue',   dot: 'bg-blue-500'   },
    { id: 'screen',       label: 'Phone Screen',  color: 'indigo', dot: 'bg-indigo-500' },
    { id: 'interview',    label: 'Interview',     color: 'amber',  dot: 'bg-amber-500'  },
    { id: 'offer',        label: 'Offer',         color: 'emerald',dot: 'bg-emerald-500'},
    { id: 'closed',       label: 'Closed',        color: 'rose',   dot: 'bg-rose-400'   },
  ];

  var STAGE_IDS = STAGES.map(function(s){ return s.id; });

  /* ── Data layer ─────────────────────────────────────────────── */
  function getState(){
    try{ return JSON.parse(localStorage.getItem(STORE) || '{"cards":[]}'); }
    catch(_){ return {cards:[]}; }
  }
  function setState(s){
    try{ localStorage.setItem(STORE, JSON.stringify(s)); }catch(_){}
  }
  function getCards(){ return getState().cards || []; }

  function updateCard(id, patch){
    var s = getState();
    s.cards = (s.cards||[]).map(function(c){
      if(String(c.id) !== String(id)) return c;
      return Object.assign({}, c, patch);
    });
    setState(s);
  }

  function moveCard(id, toStage){
    updateCard(id, { stage: toStage, enteredStageAt: new Date().toISOString() });
  }

  function deleteCard(id){
    var s = getState();
    s.cards = (s.cards||[]).filter(function(c){ return String(c.id) !== String(id); });
    setState(s);
  }

  function updateNote(id, note){
    updateCard(id, { note: note });
  }

  /* ── Helpers ────────────────────────────────────────────────── */
  function escHtml(s){
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function daysAgo(iso){
    if(!iso) return null;
    var diff = Date.now() - new Date(iso).getTime();
    var d = Math.floor(diff / 86400000);
    if(d === 0) return 'today';
    if(d === 1) return '1 day';
    return d + ' days';
  }

  function stageIndex(stageId){
    return STAGE_IDS.indexOf(stageId);
  }

  /* ── Stats ──────────────────────────────────────────────────── */
  function computeStats(cards){
    var total = cards.length;
    var active = cards.filter(function(c){ return c.stage !== 'closed'; }).length;
    var responded = cards.filter(function(c){
      return ['screen','interview','offer'].indexOf(c.stage) >= 0;
    }).length;
    var applied = cards.filter(function(c){
      return ['applied','screen','interview','offer','closed'].indexOf(c.stage) >= 0;
    }).length;
    var rate = applied > 0 ? Math.round((responded / applied) * 100) : 0;
    return { total: total, active: active, rate: rate };
  }

  /* ── Render ─────────────────────────────────────────────────── */
  function renderStats(stats){
    var el = document.getElementById('tracker-stats');
    if(!el) return;
    el.innerHTML = ''
      + '<div class="flex items-center gap-1.5"><span class="text-2xl font-bold text-slate-900">' + stats.total + '</span><span class="text-sm text-slate-500">tracked</span></div>'
      + '<div class="w-px h-8 bg-slate-200 hidden sm:block"></div>'
      + '<div class="flex items-center gap-1.5"><span class="text-2xl font-bold text-slate-900">' + stats.active + '</span><span class="text-sm text-slate-500">active</span></div>'
      + '<div class="w-px h-8 bg-slate-200 hidden sm:block"></div>'
      + '<div class="flex items-center gap-1.5"><span class="text-2xl font-bold text-brand">' + stats.rate + '%</span><span class="text-sm text-slate-500">response rate</span></div>';
  }

  function renderCard(card){
    var si = stageIndex(card.stage || 'applied');
    var canBack    = si > 0;
    var canForward = si < STAGES.length - 1;
    var prevLabel  = canBack    ? STAGES[si - 1].label : '';
    var nextLabel  = canForward ? STAGES[si + 1].label : '';
    var age = daysAgo(card.enteredStageAt || card.trackedAt);
    var jobUrl = card.id ? '/jobs/' + escHtml(String(card.id)) : (card.link ? escHtml(card.link) : '#');

    return '<article class="group relative bg-white rounded-xl border border-slate-200 p-3.5 shadow-sm hover:shadow-md transition-shadow motion-safe:transition-shadow select-none" data-card-id="' + escHtml(String(card.id)) + '" draggable="true">'
      /* delete btn */
      + '<button type="button" class="absolute top-2 right-2 p-1 rounded-md text-slate-300 hover:text-rose-500 hover:bg-rose-50 transition opacity-0 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300" data-delete-card data-id="' + escHtml(String(card.id)) + '" aria-label="Remove from tracker"><svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"><path d="M3 6h18M19 6l-1 14H6L5 6M10 11v6M14 11v6M9 6V4h6v2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
      /* title */
      + '<a href="' + jobUrl + '" class="block font-semibold text-slate-800 text-sm leading-snug hover:text-brand transition-colors pr-5 truncate" title="' + escHtml(card.title) + '">' + escHtml(card.title) + '</a>'
      + '<p class="text-xs text-slate-500 mt-0.5 truncate">' + escHtml(card.company || '') + (card.location ? ' · ' + escHtml(card.location) : '') + '</p>'
      /* age badge */
      + (age ? '<p class="text-[11px] text-slate-400 mt-1">' + escHtml(age) + ' in this stage</p>' : '')
      /* note */
      + '<textarea class="mt-2.5 w-full text-xs text-slate-600 placeholder-slate-300 border border-slate-100 rounded-lg p-2 resize-none focus:outline-none focus:ring-1 focus:ring-brand/40 bg-slate-50 hover:bg-white transition" rows="2" placeholder="Add a note…" data-note-input data-id="' + escHtml(String(card.id)) + '">' + escHtml(card.note || '') + '</textarea>'
      /* move buttons */
      + '<div class="mt-2.5 flex gap-1.5">'
      + (canBack
        ? '<button type="button" class="flex-1 inline-flex items-center justify-center gap-1 rounded-lg border border-slate-200 py-1.5 text-xs text-slate-500 hover:text-brand hover:border-brand transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40" data-move-card data-id="' + escHtml(String(card.id)) + '" data-to="' + STAGE_IDS[si-1] + '" title="Move to ' + escHtml(prevLabel) + '"><svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clip-rule="evenodd"/></svg>' + escHtml(prevLabel) + '</button>'
        : '')
      + (canForward
        ? '<button type="button" class="flex-1 inline-flex items-center justify-center gap-1 rounded-lg border border-slate-200 py-1.5 text-xs text-slate-500 hover:text-brand hover:border-brand transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40" data-move-card data-id="' + escHtml(String(card.id)) + '" data-to="' + STAGE_IDS[si+1] + '" title="Move to ' + escHtml(nextLabel) + '">' + escHtml(nextLabel) + '<svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd"/></svg></button>'
        : '')
      + '</div>'
      + '</article>';
  }

  function renderBoard(){
    var cards = getCards();
    renderStats(computeStats(cards));

    /* Empty state */
    var emptyEl = document.getElementById('tracker-empty');
    if(emptyEl) emptyEl.classList.toggle('hidden', cards.length > 0);

    STAGES.forEach(function(stage){
      var col = document.getElementById('col-' + stage.id);
      if(!col) return;
      var stageCards = cards.filter(function(c){ return (c.stage || 'applied') === stage.id; });

      /* Column count badge */
      var badge = document.getElementById('col-count-' + stage.id);
      if(badge) badge.textContent = stageCards.length;

      /* Card list */
      var list = col.querySelector('[data-card-list]');
      if(!list) return;

      if(!stageCards.length){
        list.innerHTML = '<div class="rounded-xl border-2 border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">Drop here</div>';
        return;
      }
      list.innerHTML = stageCards.map(renderCard).join('');
    });

    /* Re-wire drag events after render */
    wireDrag();
  }

  /* ── Drag & drop (desktop) ──────────────────────────────────── */
  var draggedId = null;

  function wireDrag(){
    document.querySelectorAll('[data-card-id]').forEach(function(el){
      el.addEventListener('dragstart', function(e){
        draggedId = el.getAttribute('data-card-id');
        e.dataTransfer.effectAllowed = 'move';
        setTimeout(function(){ el.classList.add('opacity-50'); }, 0);
      });
      el.addEventListener('dragend', function(){
        el.classList.remove('opacity-50');
        draggedId = null;
      });
    });
  }

  function wireColumns(){
    STAGES.forEach(function(stage){
      var col = document.getElementById('col-' + stage.id);
      if(!col) return;
      col.addEventListener('dragover', function(e){
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        col.classList.add('ring-2','ring-brand/40','bg-brand/5');
      });
      col.addEventListener('dragleave', function(e){
        if(!col.contains(e.relatedTarget)) col.classList.remove('ring-2','ring-brand/40','bg-brand/5');
      });
      col.addEventListener('drop', function(e){
        e.preventDefault();
        col.classList.remove('ring-2','ring-brand/40','bg-brand/5');
        if(draggedId){
          moveCard(draggedId, stage.id);
          renderBoard();
        }
      });
    });
  }

  /* ── CSV export ─────────────────────────────────────────────── */
  function exportCSV(){
    var cards = getCards();
    var rows  = [['Title','Company','Location','Stage','Days in Stage','Note','Link']];
    cards.forEach(function(c){
      var age = daysAgo(c.enteredStageAt || c.trackedAt) || '';
      rows.push([c.title||'', c.company||'', c.location||'', c.stage||'', age, c.note||'', c.link||'']);
    });
    var csv = rows.map(function(r){
      return r.map(function(v){ return '"' + String(v).replace(/"/g,'""') + '"'; }).join(',');
    }).join('\n');
    var blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    var url  = URL.createObjectURL(blob);
    var a    = document.createElement('a');
    a.href = url; a.download = 'job-applications.csv';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /* ── Event delegation ───────────────────────────────────────── */
  document.addEventListener('click', function(e){
    /* Move card */
    var moveBtn = e.target && e.target.closest('[data-move-card]');
    if(moveBtn){
      var id = moveBtn.getAttribute('data-id');
      var to = moveBtn.getAttribute('data-to');
      if(id && to){ moveCard(id, to); renderBoard(); }
      return;
    }
    /* Delete card */
    var delBtn = e.target && e.target.closest('[data-delete-card]');
    if(delBtn){
      var delId = delBtn.getAttribute('data-id');
      if(delId){
        deleteCard(delId);
        renderBoard();
        /* Update global badge */
        syncGlobalBadge();
      }
      return;
    }
    /* Export CSV */
    if(e.target && e.target.closest('[data-export-csv]')){ exportCSV(); }
  });

  /* Save note on blur */
  document.addEventListener('blur', function(e){
    var ta = e.target && e.target.matches('[data-note-input]') ? e.target : null;
    if(!ta) return;
    var id = ta.getAttribute('data-id');
    if(id) updateNote(id, ta.value);
  }, true);

  /* ── Global badge sync ──────────────────────────────────────── */
  function syncGlobalBadge(){
    var active = getCards().filter(function(c){ return c.stage !== 'closed'; }).length;
    var label  = active > 99 ? '99+' : String(active);
    ['tracker-badge','tracker-badge-mobile'].forEach(function(bid){
      var el = document.getElementById(bid);
      if(!el) return;
      if(active > 0){ el.textContent = label; el.classList.remove('hidden'); }
      else el.classList.add('hidden');
    });
  }

  /* ── Listen for jobs tracked from other pages ───────────────── */
  window.addEventListener('catalitium:track-job', function(e){
    var d = e.detail;
    if(!d || !d.id) return;
    var s = getState();
    s.cards = s.cards || [];
    var exists = s.cards.some(function(c){ return String(c.id) === String(d.id); });
    if(!exists){
      s.cards.unshift({
        id: String(d.id), title: d.title||'', company: d.company||'',
        location: d.location||'', link: d.link||'',
        stage: 'applied',
        trackedAt: new Date().toISOString(),
        enteredStageAt: new Date().toISOString(),
        note: ''
      });
      setState(s);
      renderBoard();
      syncGlobalBadge();
    }
  });

  /* ── Init ───────────────────────────────────────────────────── */
  wireColumns();
  renderBoard();
  syncGlobalBadge();
})();
