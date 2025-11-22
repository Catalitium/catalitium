function trackEvent(name, params){
  try {
    if (typeof window.catalitiumTrack === 'function') {
      window.catalitiumTrack(name, params || {});
    }
  } catch(_){}
}

function sendAnalyticsPayload(payload){
  try {
    var body = JSON.stringify(payload || {});
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/events/apply', new Blob([body], { type: 'application/json' }));
      return;
    }
    fetch('/events/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      keepalive: true,
      credentials: 'same-origin'
    }).catch(function(){});
  } catch(_){}
}

/* Lightweight helpers (no frameworks) */
(function(){
  // Bottom-sheet Nav: open/close + focus trap + scroll lock
  var btn = document.getElementById('hamburger');
  var sheet = document.getElementById('navsheet');
  var panel = document.getElementById('navpanel');
  var scrim = document.getElementById('navscrim');
  if (btn && sheet && panel){
    var lastActive = null;
    function getFocusables(root){
      return Array.prototype.slice.call(root.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), textarea, select, [tabindex]:not([tabindex="-1"])'
      ));
    }
    function open(){
      lastActive = document.activeElement;
      sheet.classList.remove('hidden');
      document.body.classList.add('overflow-hidden');
      btn.setAttribute('aria-expanded','true');
      trackEvent('nav_open', { surface: 'hamburger' });
      // Animate in: remove offscreen transforms + fade in scrim
      try {
        if (scrim) scrim.classList.remove('opacity-0');
        panel.classList.remove('translate-y-full');
        panel.classList.remove('md:translate-x-full');
      } catch(_){ }
      var f = getFocusables(panel);
      if (f.length) try { f[0].focus(); } catch(_){}
      document.addEventListener('keydown', trap, true);
    }
    function close(){
      // Animate out: add transforms + fade scrim, then hide after transition
      try {
        if (scrim) scrim.classList.add('opacity-0');
        panel.classList.add('translate-y-full');
        panel.classList.add('md:translate-x-full');
      } catch(_){ }
      setTimeout(function(){
        sheet.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
        btn.setAttribute('aria-expanded','false');
        document.removeEventListener('keydown', trap, true);
        try { if(lastActive) lastActive.focus(); } catch(_){ }
      }, 180);
    }
    function trap(e){
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key !== 'Tab') return;
      var f = getFocusables(panel); if(!f.length) return;
      var first = f[0], last = f[f.length-1];
      var active = document.activeElement;
      if (e.shiftKey && (active === first || !panel.contains(active))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (active === last)) { e.preventDefault(); first.focus(); }
    }
    btn.addEventListener('click', function(e){ e.preventDefault(); open(); });
    sheet.addEventListener('click', function(e){ if(e.target && e.target.matches('[data-dismiss], [data-dismiss] *')) close(); });
    // Quick actions
    document.addEventListener('click', function(e){
      var a = e.target && e.target.closest('[data-nav-action]');
      if(!a) return;
      var act = a.getAttribute('data-nav-action');
      if (act === 'search'){
        e.preventDefault(); close(); var q=document.getElementById('q'); if(q) q.focus();
        trackEvent('nav_action', { action: 'quick_search' });
      }
    });
  }

  // ------------------------------------------------------------------
  // Subscribe dialog triggers
  // ------------------------------------------------------------------
  var subscribeDialog = document.getElementById('subscribeDialog');
  if(subscribeDialog){
    document.addEventListener('click', function(e){
      var trg = e.target.closest('[data-open-subscribe]');
      if(!trg) return;
      trackEvent('modal_open', { modal: 'subscribe', source: trg.getAttribute('data-open-subscribe') || 'cta' });
      try { subscribeDialog.showModal(); } catch(_) { subscribeDialog.open = true; }
    });
  }

  // ------------------------------------------------------------------
  // Apply modal trigger & analytics
  // ------------------------------------------------------------------
  function sendApplyAnalytics(status, detail){
    try {
      var meta = detail || {};
      var payload = {
        status: status || '',
        job_id: meta.job_id || meta.jobId || '',
        job_title: meta.job_title || meta.jobTitle || '',
        job_company: meta.job_company || meta.jobCompany || '',
        job_location: meta.job_location || meta.jobLocation || '',
        job_link: meta.job_link || meta.jobLink || '',
        job_summary: meta.job_summary || meta.jobSummary || '',
        source: 'web'
      };
      payload.event_type = 'apply';
      sendAnalyticsPayload(payload);
      trackEvent('job_apply', {
        status: status || '',
        job_id: payload.job_id || '',
        job_title: payload.job_title || ''
      });
    } catch(_){}
  }
  try { window.__applyAnalytics = sendApplyAnalytics; } catch(_){}

  document.addEventListener('click', function(e){
    var el = e.target.closest('[data-apply]');
    if(!el) return;
    e.preventDefault();
    var card = el.closest('[data-job-id]');
    var link = el.getAttribute('data-link') || '';
    var title = el.getAttribute('data-title') || '';
    var payload = jobPayloadFromCard(card, el);
    if(!payload){
      payload = {
        job_id: (card && card.getAttribute('data-job-id')) || '',
        job_title: title,
        company: el.getAttribute('data-company') || '',
        location: el.getAttribute('data-location') || '',
        summary: el.getAttribute('data-description') || ''
      };
    }
    if (!payload.job_title) payload.job_title = title;
    sendApplyAnalytics('modal_open', {
      job_id: payload.job_id || payload.id || '',
      job_title: payload.job_title || title,
      job_company: payload.company || '',
      job_location: payload.location || '',
      job_link: link || payload.link || '',
      job_summary: payload.summary || ''
    });
    try {
      window.dispatchEvent(new CustomEvent('open-job-modal', {
        detail: {
          jobId: payload.job_id,
          jobTitle: payload.job_title,
          jobLink: link,
          jobLocation: payload.location,
          jobCompany: payload.company,
          jobSummary: payload.summary || ''
        }
      }));
    } catch(_) {}
  });

  // ------------------------------------------------------------------
  // Job payload extraction helpers
  // ------------------------------------------------------------------
  function jobPayloadFromCard(card, trigger){
    if(!card) return null;
    var cardDs = card.dataset || {};
    var trigDs = (trigger && trigger.dataset) || {};
    function pick(){
      for (var i = 0; i < arguments.length; i++){
        var val = arguments[i];
        if (typeof val === 'string' && val.trim()){
          return val.trim();
        }
      }
      return '';
    }
    var jobId = pick(trigDs.jobId, cardDs.jobId, card.getAttribute('data-job-id'));
    var title = pick(trigDs.title, trigDs.jobTitle, cardDs.jobTitle);
    if(!title){
      var titleEl = card.querySelector('h2');
      title = titleEl ? (titleEl.textContent || '').trim() : '';
    }
    var company = pick(trigDs.company, cardDs.jobCompany);
    var location = pick(trigDs.location, cardDs.jobLocation);
    if(!company || !location){
      var metaEl = card.querySelector('[data-job-meta]');
      var metaText = metaEl ? (metaEl.textContent || '').trim() : '';
      if(metaText){
        var parts = metaText.split('\u2022');
        var primary = parts[0] ? parts[0].trim() : metaText;
        if(!company && primary.indexOf(' - ') >= 0){
          var seg = primary.split(' - ');
          company = pick(company, seg.shift());
          location = pick(location, seg.join(' - '));
        } else {
          location = pick(location, primary);
        }
      }
    }
    var summary = pick(trigDs.description, trigDs.jobDescription, trigDs.summary, cardDs.jobSummary);
    if(!summary){
      var detailsEl = card.querySelector('details');
      if(detailsEl){
        var textEl = detailsEl.querySelector('p');
        if(textEl){
          summary = (textEl.textContent || '').trim().slice(0, 200);
        }
      }
    }
    company = company.trim ? company.trim() : company;
    location = location.trim ? location.trim() : location;
    summary = summary && summary.trim ? summary.trim() : summary;
    return {
      job_id: jobId,
      job_title: title,
      company: company || '',
      location: location || '',
      summary: summary || ''
    };
  }

  try { window.jobPayloadFromCard = jobPayloadFromCard; } catch(_) {}
})();

// --------------------------------------------------------------------
// Job modal (vanilla JS controller)
// --------------------------------------------------------------------
(function(){
  var wrap = document.getElementById('jobModal');
  var dialog = document.getElementById('jobDialog');
  var form = document.getElementById('jobModalForm');
  var emailInput = document.getElementById('jobModalEmail');
  var jobIdField = document.getElementById('jobModalJobId');
  var titleSpan = document.getElementById('jobModalTitle');
  var cancelBtn = document.querySelector('[data-close-job-modal]');
  if (!wrap || !dialog || !form || !emailInput || !jobIdField || !titleSpan) {
    return;
  }

  var emitApply = window.__applyAnalytics || function(){};
  var summarySpan = document.getElementById('jobModalSummary');
  var errorBox = document.getElementById('jobModalError');
  var submitBtn = document.getElementById('jobModalSubmit');

  var jobDetail = {
    jobLink: '',
    jobId: '',
    jobTitle: '',
    jobCompany: '',
    jobLocation: '',
    jobSummary: ''
  };

  function setError(message){
    if (!errorBox) {
      if (message) alert(message);
      return;
    }
    if (message) {
      errorBox.textContent = message;
      errorBox.classList.remove('hidden');
    } else {
      errorBox.textContent = '';
      errorBox.classList.add('hidden');
    }
  }

  function setLoading(state){
    if (!submitBtn) return;
    submitBtn.disabled = !!state;
    if (state) {
      submitBtn.classList.add('opacity-70');
    } else {
      submitBtn.classList.remove('opacity-70');
    }
  }

  function openJobLink(target){
    if (!target) {
      setError('This job does not have an external apply link yet. Please try another listing.');
      return false;
    }
    try {
      var opened = window.open(target, '_blank');
      if (opened) {
        opened.opener = null;
        return true;
      }
    } catch(_){}
    try {
      window.location.assign(target);
      return true;
    } catch(_){
      window.location.href = target;
      return true;
    }
  }

  function hideModal() {
    try { dialog.close(); } catch(_) { dialog.removeAttribute('open'); }
    wrap.classList.add('hidden');
  }

  function showModal() {
    wrap.classList.remove('hidden');
    try { dialog.showModal(); } catch(_) { dialog.setAttribute('open', 'true'); }
    setError('');
    setTimeout(function(){
      try { emailInput.focus(); } catch(_){}
    }, 0);
  }

  window.addEventListener('open-job-modal', function(evt){
    var detail = evt && evt.detail ? evt.detail : {};
    jobDetail.jobLink = detail.jobLink || '';
    jobDetail.jobId = detail.jobId || '';
    jobDetail.jobTitle = detail.jobTitle || '';
    jobDetail.jobCompany = detail.jobCompany || '';
    jobDetail.jobLocation = detail.jobLocation || '';
      jobDetail.jobSummary = detail.jobSummary || '';
    jobIdField.value = jobDetail.jobId;
    titleSpan.textContent = jobDetail.jobTitle || 'this role';
    if (summarySpan) {
      if (jobDetail.jobSummary) {
        summarySpan.textContent = jobDetail.jobSummary;
        summarySpan.classList.remove('hidden');
      } else {
        summarySpan.textContent = '';
        summarySpan.classList.add('hidden');
      }
    }
    emailInput.value = '';
    showModal();
  });

  wrap.addEventListener('click', function(e){
    if (e.target === wrap) {
      emitApply('modal_dismiss', jobDetail);
      hideModal();
    }
  });

  dialog.addEventListener('cancel', function(e){
    e.preventDefault();
    emitApply('modal_cancel', jobDetail);
    hideModal();
  });

  dialog.addEventListener('close', function(){
    wrap.classList.add('hidden');
  });

  if (cancelBtn) {
    cancelBtn.addEventListener('click', function(){
      emitApply('modal_cancel', jobDetail);
      hideModal();
    });
  }

  form.addEventListener('submit', function(e){
    e.preventDefault();
    setError('');
    var email = (emailInput.value || '').trim();
    if (!/.+@.+\..+/.test(email)) {
      setError('Please enter a valid email address.');
      emailInput.focus();
      return;
    }
    emitApply('submit', jobDetail);
    setLoading(true);
    var payload = {
      email: email,
      job_id: jobDetail.jobId || ''
    };
    if (jobDetail.jobLink) {
      payload.job_link = jobDetail.jobLink;
    }
    fetch('/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    })
      .then(function(resp){
        return resp.json().catch(function(){ return {}; }).then(function(data){
          return { ok: resp.ok, data: data || {} };
        });
      })
      .then(function(result){
        var data = result.data || {};
        if (!result.ok) {
          throw new Error(data.error || 'subscribe_failed');
        }
        if (data.error && data.error !== 'duplicate') {
          throw new Error(data.error);
        }
        emitApply('submit_success', jobDetail);
        var target = data.redirect || jobDetail.jobLink || '';
        if (!target) {
          setLoading(false);
          setError('We could not find an external apply link yet. Please try again later.');
          emitApply('redirect_missing', jobDetail);
          return;
        }
        hideModal();
        setLoading(false);
        emitApply('redirect', jobDetail);
        openJobLink(target);
      })
      .catch(function(err){
        setLoading(false);
        emitApply('submit_error', jobDetail);
        var message = 'We could not complete your request. Please try again.';
        if (err && err.message === 'invalid_email') {
          message = 'Please enter a valid email address.';
        } else if (err && err.message === 'duplicate') {
          message = 'You are already on the list. Try again shortly.';
        } else if (err && err.message === 'subscribe_failed') {
          message = 'We could not subscribe you. Please try again.';
        }
        setError(message);
      });
  });
})();


// --------------------------------------------------------------------
// Search normalization and weekly subscribe toggle
// --------------------------------------------------------------------
(function(){
  var form = document.getElementById('search');
  var q = document.getElementById('q');
  var loc = document.getElementById('loc');
  var toggle = document.getElementById('weekly-toggle');
  var subDlg = document.getElementById('subscribeDialog');
  var COUNTRY_MAP = { de:'DE', deu:'DE', germany:'DE', deutschland:'DE', ch:'CH', schweiz:'CH', suisse:'CH', svizzera:'CH', switzerland:'CH', at:'AT', 'sterreich':'AT', austria:'AT', eu:'EU', europe:'EU', eur:'EU', 'european union':'EU', uk:'UK', gb:'UK', england:'UK', 'united kingdom':'UK', us:'US', usa:'US', 'united states':'US', america:'US', es:'ES', spain:'ES', fr:'FR', france:'FR', it:'IT', italy:'IT', nl:'NL', netherlands:'NL', be:'BE', belgium:'BE', se:'SE', sweden:'SE', pl:'PL', poland:'PL', pt:'PT', portugal:'PT', ie:'IE', ireland:'IE', dk:'DK', denmark:'DK', fi:'FI', finland:'FI', gr:'GR', greece:'GR', hu:'HU', hungary:'HU', ro:'RO', romania:'RO', sk:'SK', slovakia:'SK', si:'SI', slovenia:'SI', bg:'BG', bulgaria:'BG', hr:'HR', croatia:'HR', cy:'CY', cyprus:'CY', cz:'CZ', 'czech republic':'CZ', czech:'CZ', ee:'EE', estonia:'EE', lv:'LV', latvia:'LV', lt:'LT', lithuania:'LT', lu:'LU', luxembourg:'LU', mt:'MT', malta:'MT', co:'CO', colombia:'CO', mx:'MX', mexico:'MX' };
  var TITLE_MAP = { swe:'software engineer', 'software eng':'software engineer', 'sw eng':'software engineer', frontend:'front end', 'front-end':'front end', backend:'back end', 'back-end':'back end', fullstack:'full stack', 'full-stack':'full stack', pm:'product manager', 'prod mgr':'product manager', 'product owner':'product manager', ds:'data scientist', ml:'machine learning', mle:'machine learning engineer', sre:'site reliability engineer', devops:'devops', 'sec eng':'security engineer', infosec:'security', programmer:'developer', coder:'developer' };
  function normCountry(v){ if(!v) return ''; var t=(v.trim().toLowerCase()); if(COUNTRY_MAP[t]) return COUNTRY_MAP[t]; if(/^[a-z]{2}$/.test(t)) return t.toUpperCase(); return v.trim(); }
  function normTitle(v){ if(!v) return ''; var s=v.toLowerCase(); Object.keys(TITLE_MAP).forEach(function(k){ if(s.indexOf(k)>=0) s=s.replace(new RegExp(k,'g'), TITLE_MAP[k]); }); return s.replace(/\s+/g,' ').trim(); }
  if(form){ form.addEventListener('submit', function(){
    var titleVal = q ? normTitle(q.value) : '';
    var countryVal = loc ? normCountry(loc.value) : '';
    trackEvent('search_submit', { title: titleVal || '(empty)', country: countryVal || '(empty)' });
    if(q) q.value = titleVal;
    if(loc) loc.value = countryVal;
  }); }
  if(toggle && subDlg){ toggle.addEventListener('change', function(){ if(toggle.checked){ try{subDlg.showModal();}catch(_) {subDlg.open=true;} var em=document.getElementById('subscribe-email'); if(em) em.focus(); }}); subDlg.addEventListener('close', function(){ toggle.checked=false; }); }
  // Log subscribe dialog native form submission (newsletter)
})();

// Inline script from index.html externalized (kept order and behavior)
(function(){
  try {
    var form = document.getElementById('search');
    var q = document.getElementById('q');
    var loc = document.getElementById('loc');
   if (form) {
      form.addEventListener('submit', function(){
        // Show skeletons during navigation
        try {
          var sk = document.getElementById('results-skeletons');
          if (sk) sk.classList.remove('hidden');
        } catch(_) {}
      });
    }

    // Weekly toggle: support click-outside close for dialog (existing UI)
    var toggle = document.getElementById('weekly-toggle');
    var dlg = document.getElementById('subscribeDialog');
    if (toggle && dlg && dlg.showModal) {
      dlg.addEventListener('click', function(e){
        var r = dlg.getBoundingClientRect();
        if (e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom) {
          try { dlg.close(); } catch(_) {}
        }
      });
    }

    // Mobile: advanced search toggle (reveals country input)
    var advBtn = document.getElementById('advanced-toggle');
    var advWrap = document.getElementById('loc-wrap');
    if (advBtn && advWrap) {
      advBtn.addEventListener('click', function(){
        var hidden = advWrap.classList.toggle('hidden');
        advBtn.setAttribute('aria-expanded', (!hidden).toString());
      });
    }

    // Optional details toggle (no-op unless elements exist)
   document.querySelectorAll('[data-toggle="details"]').forEach(function(btn){
      var opened = false;
      btn.addEventListener('click', function(){
        var art = btn.closest('article[data-job-id]');
        var container = art && art.querySelector('[data-details]');
        if (!container) return;
        container.classList.toggle('hidden');
        var expanded = !container.classList.contains('hidden');
        btn.setAttribute('aria-expanded', expanded);
        if (expanded && !opened) {
          opened = true;
          trackEvent('details_toggle', { action: 'open', job_id: art && art.getAttribute('data-job-id') });
        }
      });
    });
  } catch(e) {}
})();


// --------------------------------------------------------------------
// Filter chip analytics
// --------------------------------------------------------------------
(function(){
  document.addEventListener('click', function(e){
    var chip = e.target && e.target.closest('[data-filter-chip]');
    if (!chip) return;
    var filterType = chip.getAttribute('data-filter-chip') || '';
    var filterValue = chip.getAttribute('data-filter-value') || '';
    trackEvent('filter_chip', {
      type: filterType,
      value: filterValue
    });
    sendAnalyticsPayload({
      event_type: 'filter',
      filter_type: filterType,
      filter_value: filterValue,
      source: 'web',
      status: 'selected'
    });
  });
})();
