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

  // Shared modal helpers for form modals
  function createFormModal(opts){
    var dialog = opts.dialog;
    var form = opts.form;
    var successEl = opts.successEl;
    var errorEl = opts.errorEl;
    var submitBtn = opts.submitBtn;
    var focusEl = opts.focusEl;
    var onOpen = opts.onOpen || function(){};
    var onReset = opts.onReset || function(){};
    var onSubmit = opts.onSubmit || function(){ return Promise.resolve(); };

    var source = 'cta';

    function setError(msg){
      if (!errorEl) return;
      if (msg){
        errorEl.textContent = msg;
        errorEl.classList.remove('hidden');
      } else {
        errorEl.textContent = '';
        errorEl.classList.add('hidden');
      }
    }
    function toggleLoading(isLoading){
      if (!submitBtn) return;
      submitBtn.disabled = !!isLoading;
      submitBtn.textContent = isLoading ? (opts.loadingText || submitBtn.textContent) : (opts.idleText || submitBtn.textContent);
    }
    function reset(){
      setError('');
      if (successEl) successEl.classList.add('hidden');
      if (form) try { form.reset(); } catch(_){}
      toggleLoading(false);
      onReset();
    }
    function open(src){
      if (!dialog) return;
      source = src || 'cta';
      reset();
      onOpen(source);
      try { dialog.showModal(); } catch(_) { dialog.open = true; }
      try { if (focusEl) focusEl.focus(); } catch(_){}
    }
    function close(){
      if (!dialog) return;
      try { dialog.close(); } catch(_) { dialog.open = false; }
    }
    function attach(openAttr, closeAttr){
      if (openAttr){
        document.addEventListener('click', function(e){
          var trg = e.target && e.target.closest('[' + openAttr + ']');
          if(!trg) return;
          e.preventDefault();
          open(trg.getAttribute(openAttr) || 'cta');
        });
      }
      if (closeAttr){
        document.addEventListener('click', function(e){
          var closeBtn = e.target && e.target.closest('[' + closeAttr + ']');
          if(!closeBtn) return;
          e.preventDefault();
          close();
        });
      }
      if (dialog){
        dialog.addEventListener('click', function(e){
          var rect = dialog.getBoundingClientRect();
          if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom){
            close();
          }
        });
      }
      if (form){
        form.addEventListener('submit', function(e){
          e.preventDefault();
          setError('');
          if (successEl) successEl.classList.add('hidden');
          toggleLoading(true);
          onSubmit({ source: source, setError: setError, toggleLoading: toggleLoading, showSuccess: function(){
            if (successEl) successEl.classList.remove('hidden');
          }, reset: reset }).finally(function(){
            toggleLoading(false);
          });
        });
      }
    }
    return { open: open, close: close, attach: attach, setError: setError, toggleLoading: toggleLoading, reset: reset, getSource: function(){ return source; } };
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
      sendAnalyticsPayload({
        event_type: 'modal_open',
        status: 'ok',
        source: 'web',
        meta: { modal: 'subscribe', surface: trg.getAttribute('data-open-subscribe') || 'cta' }
      });
      try { subscribeDialog.showModal(); } catch(_) { subscribeDialog.open = true; }
    });
  }

  // ------------------------------------------------------------------
  // Contact dialog triggers + submission
  // ------------------------------------------------------------------
  var contactDialog = document.getElementById('contactDialog');
  var contactForm = document.getElementById('contactForm');
  var contactEmail = document.getElementById('contact-email');
  var contactName = document.getElementById('contact-name');
  var contactMsg = document.getElementById('contact-message');
  var contactError = document.getElementById('contactError');
  var contactSuccess = document.getElementById('contactSuccess');
  var contactSubmit = document.getElementById('contactSubmit');
  var contactModal = createFormModal({
    dialog: contactDialog,
    form: contactForm,
    successEl: contactSuccess,
    errorEl: contactError,
    submitBtn: contactSubmit,
    focusEl: contactEmail,
    idleText: 'Send message',
    loadingText: 'Sending…',
    onOpen: function(source){
      trackEvent('modal_open', { modal: 'contact', source: source || 'cta' });
      sendAnalyticsPayload({
        event_type: 'modal_open',
        status: 'ok',
        source: 'web',
        meta: { modal: 'contact', surface: source || 'cta' }
      });
    },
    onSubmit: function(ctx){
      var email = (contactEmail && contactEmail.value || '').trim();
      var name = (contactName && contactName.value || '').trim();
      var message = (contactMsg && contactMsg.value || '').trim();
      if (!/.+@.+\..+/.test(email)){
        ctx.setError('Please enter a valid email.');
        if (contactEmail) contactEmail.focus();
        return Promise.resolve();
      }
      if (!name || name.length < 2){
        ctx.setError('Please add your name or company.');
        if (contactName) contactName.focus();
        return Promise.resolve();
      }
      if (!message || message.length < 5){
        ctx.setError('Please add a short message.');
        if (contactMsg) contactMsg.focus();
        return Promise.resolve();
      }
      return fetch('/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ email: email, name: name, message: message })
      })
        .then(function(resp){
          return resp.json().catch(function(){ return {}; }).then(function(data){
            return { ok: resp.ok, data: data || {} };
          });
        })
        .then(function(result){
          if (!result.ok || (result.data && result.data.error)){
            throw new Error(result.data && result.data.error || 'contact_failed');
          }
          ctx.showSuccess();
          trackEvent('contact_submit', { status: 'ok' });
          sendAnalyticsPayload({
            event_type: 'contact',
            status: 'ok',
            source: 'web',
            meta: { surface: contactModal.getSource() || 'cta' }
          });
          if (contactForm) contactForm.reset();
        })
        .catch(function(err){
          var msg = 'We could not send your message. Please try again.';
          if (err && err.message === 'invalid_email') msg = 'Please enter a valid email.';
          if (err && err.message === 'invalid_name') msg = 'Please add your name or company.';
          if (err && err.message === 'invalid_message') msg = 'Please add a short message.';
          ctx.setError(msg);
          trackEvent('contact_submit', { status: 'error', error: (err && err.message) || 'unknown' });
        });
    }
  });
  contactModal.attach('data-open-contact', 'data-close-contact');

  // ------------------------------------------------------------------
  // Job posting dialog triggers + submission
  // ------------------------------------------------------------------
  var jobPostDialog = document.getElementById('jobPostDialog');
  var jobPostForm = document.getElementById('jobPostForm');
  var jobPostEmail = document.getElementById('jobpost-email');
  var jobPostTitle = document.getElementById('jobpost-title-input');
  var jobPostCompany = document.getElementById('jobpost-company');
  var jobPostSalary = document.getElementById('jobpost-salary');
  var jobPostDesc = document.getElementById('jobpost-description');
  var jobPostCount = document.getElementById('jobpost-count');
  var jobPostError = document.getElementById('jobPostError');
  var jobPostSuccess = document.getElementById('jobPostSuccess');
  var jobPostSubmit = document.getElementById('jobPostSubmit');

  function wordCount(str){
    if (!str) return 0;
    var matches = str.match(/\b\w+\b/g);
    return matches ? matches.length : 0;
  }
  function updateJobPostCount(){
    if (!jobPostDesc || !jobPostCount) return;
    var count = wordCount(jobPostDesc.value || '');
    jobPostCount.textContent = count + " / ~5000 words max";
    if (count > 5000){
      jobPostCount.classList.add('text-rose-600');
    } else {
      jobPostCount.classList.remove('text-rose-600');
    }
  }
  var jobPostModal = createFormModal({
    dialog: jobPostDialog,
    form: jobPostForm,
    successEl: jobPostSuccess,
    errorEl: jobPostError,
    submitBtn: jobPostSubmit,
    focusEl: jobPostTitle,
    idleText: 'Submit job',
    loadingText: 'Sending…',
    onReset: function(){ updateJobPostCount(); },
    onOpen: function(source){
      trackEvent('modal_open', { modal: 'job_posting', source: source || 'cta' });
      sendAnalyticsPayload({
        event_type: 'modal_open',
        status: 'ok',
        source: 'web',
        meta: { modal: 'job_posting', surface: source || 'cta' }
      });
    },
    onSubmit: function(ctx){
      var email = (jobPostEmail && jobPostEmail.value || '').trim();
      var title = (jobPostTitle && jobPostTitle.value || '').trim();
      var company = (jobPostCompany && jobPostCompany.value || '').trim();
      var salary = (jobPostSalary && jobPostSalary.value || '').trim();
      var desc = (jobPostDesc && jobPostDesc.value || '').trim();

      if (!/.+@.+\..+/.test(email)){
        ctx.setError('Please enter a valid contact email.');
        if (jobPostEmail) jobPostEmail.focus();
        return Promise.resolve();
      }
      if (!title || title.length < 2){
        ctx.setError('Please add a job title.');
        if (jobPostTitle) jobPostTitle.focus();
        return Promise.resolve();
      }
      if (!company || company.length < 2){
        ctx.setError('Please add a company name.');
        if (jobPostCompany) jobPostCompany.focus();
        return Promise.resolve();
      }
      if (!desc || desc.length < 10){
        ctx.setError('Please add a short description.');
        if (jobPostDesc) jobPostDesc.focus();
        return Promise.resolve();
      }
      if (wordCount(desc) > 5000){
        ctx.setError('Description is too long (max ~5000 words).');
        if (jobPostDesc) jobPostDesc.focus();
        return Promise.resolve();
      }

      return fetch('/job-posting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          contact_email: email,
          job_title: title,
          company: company,
          salary_range: salary,
          description: desc
        })
      })
        .then(function(resp){
          return resp.json().catch(function(){ return {}; }).then(function(data){
            return { ok: resp.ok, data: data || {} };
          });
        })
        .then(function(result){
          if (!result.ok || (result.data && result.data.error)){
            throw new Error(result.data && result.data.error || 'job_posting_failed');
          }
          ctx.showSuccess();
          trackEvent('job_posting_submit', { status: 'ok' });
          sendAnalyticsPayload({
            event_type: 'job_posting',
            status: 'ok',
            source: 'web',
            meta: { surface: jobPostModal.getSource() || 'cta' },
            job_title: title,
            job_company: company,
            job_location: '',
            job_link: '',
            job_summary: ''
          });
          if (jobPostForm) jobPostForm.reset();
          updateJobPostCount();
        })
        .catch(function(err){
          var msg = 'We could not submit the job. Please try again.';
          if (err && err.message === 'invalid_email') msg = 'Please enter a valid contact email.';
          if (err && err.message === 'invalid_title') msg = 'Please add a job title.';
          if (err && err.message === 'invalid_company') msg = 'Please add a company name.';
          if (err && err.message === 'invalid_description') msg = 'Please add a short description.';
          if (err && err.message === 'description_too_long') msg = 'Description is too long (max ~5000 words).';
          ctx.setError(msg);
          trackEvent('job_posting_submit', { status: 'error', error: (err && err.message) || 'unknown' });
        });
    }
  });
  jobPostModal.attach('data-open-job-posting', 'data-close-job-posting');
  if (jobPostDesc){
    jobPostDesc.addEventListener('input', updateJobPostCount);
    updateJobPostCount();
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

// ====================================================================
// VIBE FEATURES — shared util
// ====================================================================
function escHtml(s){
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ====================================================================
// FEATURE 1: INSTANT SEARCH (debounced, no page reload)
// ====================================================================
(function(){
  var titleInput  = document.getElementById('q');
  var countryInput= document.getElementById('loc');
  var resultsEl   = document.getElementById('results');
  var skeletons   = document.getElementById('results-skeletons');
  if (!titleInput || !resultsEl) return;

  var abortCtrl  = null;
  var debounceT  = null;

  function buildCard(job, index){
    var id        = escHtml(String(job.id||''));
    var title     = escHtml(job.title||job.job_title||'');
    var company   = escHtml(job.company||job.job_company_name||'');
    var location  = escHtml(job.location||'Remote / Anywhere');
    var link      = String(job.link||'');
    var date      = escHtml(job.job_date||'');
    var dateRaw   = String(job.date_raw||'');
    var isGhost   = !!job.is_ghost;
    var salary    = escHtml(job.job_salary_range||'');
    var rawDesc   = String(job.description||job.job_description||'');
    var desc      = escHtml(rawDesc);
    var descShort = escHtml(rawDesc.slice(0,200));
    var safeLink  = escHtml(link);

    var newBadge   = job.is_new ? '<span class="inline-flex items-center text-[11px] font-semibold uppercase tracking-wide text-emerald-700 bg-emerald-100 border border-emerald-200 rounded-full px-2 py-0.5">New</span>' : '';
    var ghostBadge = isGhost ? '<span class="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 bg-slate-100 border border-slate-200 rounded-full px-2 py-0.5" title="Posted over 30 days ago — may already be filled"><svg class="w-3 h-3" viewBox="0 0 24 24" fill="none"><path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>May be filled</span>' : '';
    var companyBadge = company ? '<span class="inline-flex items-center gap-1 rounded-full bg-slate-50 border border-slate-200 px-2 py-1">'+company+'</span>' : '';
    var locBadge     = '<span class="inline-flex items-center gap-1 rounded-full bg-sky-50 border border-sky-200 px-2 py-1 text-sky-800">'+location+'</span>';
    var dateBadge    = date ? '<span class="inline-flex items-center gap-1 rounded-full bg-indigo-50 border border-indigo-200 px-2 py-1 text-indigo-800">'+date+'</span>' : '';
    var salaryBadge  = salary ? '<span class="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-1 text-amber-800 font-semibold">'+salary+'</span>' : '';

    var applyBtn;
    if (index <= 2 && link){
      applyBtn = '<a href="'+safeLink+'" target="_blank" rel="noopener" class="inline-flex items-center gap-2 rounded-md bg-gradient-to-b from-blue-600 to-blue-600/95 text-white px-4 py-2 text-sm font-semibold shadow-md hover:from-blue-700 transition-transform active:translate-y-px w-full sm:w-auto justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300"><svg class="w-4 h-4" viewBox="0 0 24 24" fill="none"><path d="M12 2v20M2 12h20" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>Easy Apply</a>';
    } else {
      applyBtn = '<button type="button" class="inline-flex items-center gap-2 rounded-md bg-brand text-white px-4 py-2 text-sm font-semibold shadow-md hover:bg-brand/90 transition-transform active:translate-y-px w-full sm:w-auto min-h-[44px] justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50" data-apply data-title="'+title+'" data-link="'+safeLink+'" data-company="'+company+'" data-location="'+location+'" data-description="'+descShort+'"><svg class="w-4 h-4" viewBox="0 0 24 24" fill="none"><path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>Apply</button>';
    }

    var bmBtn = '<button type="button" class="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:text-amber-600 hover:border-amber-300 transition w-full sm:w-auto min-h-[44px] justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50" data-bookmark-btn data-job-id="'+id+'" data-job-title="'+title+'" data-job-company="'+company+'" data-job-location="'+location+'" data-job-link="'+safeLink+'" data-job-date="'+date+'" aria-pressed="false" aria-label="Save '+title+'"><svg class="w-4 h-4" viewBox="0 0 24 24" fill="none"><path d="M5 3h14a1 1 0 011 1v18l-7-4-7 4V4a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg><span class="bookmark-label">Save</span></button>';

    return '<article class="rounded-xl border border-slate-200 bg-white p-3 sm:p-4 hover:border-slate-300 transition-colors hover:shadow-md hover:-translate-y-[1px]" data-job-id="'+id+'" data-job-title="'+title+'" data-job-company="'+company+'" data-job-location="'+location+'" data-job-summary="'+descShort+'" data-job-date="'+escHtml(dateRaw)+'">'
      +'<header class="flex flex-col sm:flex-row items-start gap-2 sm:gap-3"><div class="min-w-0">'
      +'<div class="flex items-center gap-2 flex-wrap"><h2 class="text-lg sm:text-xl font-semibold leading-snug break-words"><a href="/jobs/'+id+'" class="hover:text-brand transition-colors">'+title+'</a></h2>'+newBadge+ghostBadge+'</div>'
      +'<div class="mt-1 flex flex-wrap items-center gap-2 text-xs sm:text-[13px] text-slate-700">'+companyBadge+locBadge+dateBadge+salaryBadge+'</div>'
      +'</div></header>'
      +'<details id="details-dyn-'+id+'" class="mt-2 group"><summary class="list-none inline-flex items-center gap-1 text-[13px] underline cursor-pointer text-slate-600 hover:text-blue-600 focus:outline-none px-2 py-1 rounded-lg select-none"><span>More details</span><svg class="w-3 h-3 transition-transform group-open:rotate-180" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 10.94l3.71-3.71a.75.75 0 111.06 1.06l-4.24 4.24a.75.75 0 01-1.06 0L5.21 8.29a.75.75 0 01.02-1.08z" clip-rule="evenodd"/></svg></summary>'
      +'<div class="mt-2"><p class="text-sm text-slate-700 whitespace-pre-line">'+desc+'</p></div></details>'
      +'<div class="mt-4 flex flex-col sm:flex-row gap-2">'+applyBtn+bmBtn+'</div>'
      +'</article>';
  }

  function showEmpty(){
    resultsEl.innerHTML='<div class="rounded-xl border border-slate-200 p-6 text-slate-600 text-center"><p class="font-medium">No jobs matched these filters yet.</p><p class="text-xs mt-1">Try a broader keyword or remove the region filter.</p></div>';
  }

  function setSkeleton(on){
    if(skeletons) skeletons.classList.toggle('hidden',!on);
    resultsEl.classList.toggle('opacity-50',on);
  }

  function updateCount(n){
    var el=document.getElementById('js-results-count');
    if(el) el.textContent = n+' curated results';
  }

  function doFetch(title, country){
    if(abortCtrl){ try{ abortCtrl.abort(); }catch(_){} }
    if(typeof AbortController!=='undefined') abortCtrl=new AbortController();
    var params=new URLSearchParams();
    if(title) params.set('title',title);
    if(country) params.set('country',country);
    var qs=params.toString();
    try{ history.replaceState(null,'',qs?'?'+qs:window.location.pathname); }catch(_){}
    setSkeleton(true);
    var opts={ credentials:'same-origin' };
    if(abortCtrl) opts.signal=abortCtrl.signal;
    fetch('/api/jobs'+(qs?'?'+qs:''),opts)
      .then(function(r){ return r.json(); })
      .then(function(data){
        setSkeleton(false);
        var items=data.items||[];
        updateCount((data.meta&&data.meta.total)||items.length);
        if(!items.length){ showEmpty(); return; }
        var html='';
        items.forEach(function(job,i){ html+=buildCard(job,i+1); });
        resultsEl.innerHTML=html;
        try{ if(typeof window.__initBookmarks==='function') window.__initBookmarks(); }catch(_){}
        try{ document.dispatchEvent(new CustomEvent('catalitium:results-updated')); }catch(_){}
      })
      .catch(function(e){ if(e&&e.name==='AbortError') return; setSkeleton(false); });
  }

  function onInput(){
    clearTimeout(debounceT);
    debounceT=setTimeout(function(){
      doFetch((titleInput.value||'').trim(),(countryInput?countryInput.value:'').trim());
    },380);
  }

  titleInput.addEventListener('input',onInput);
  if(countryInput) countryInput.addEventListener('input',onInput);
})();

// ====================================================================
// FEATURE 2: BOOKMARKS (localStorage)
// ====================================================================
(function(){
  var KEY='catalitium_bookmarks';

  function get(){ try{ return JSON.parse(localStorage.getItem(KEY)||'[]'); }catch(_){ return []; } }
  function save(arr){ try{ localStorage.setItem(KEY,JSON.stringify(arr)); }catch(_){} }
  function has(id){ return get().some(function(b){ return String(b.id)===String(id); }); }

  function add(job){
    var arr=get();
    if(!arr.some(function(b){ return String(b.id)===String(job.id); })){ arr.unshift(job); save(arr); }
  }
  function remove(id){ save(get().filter(function(b){ return String(b.id)!==String(id); })); }

  function styleBtn(btn,saved){
    btn.setAttribute('aria-pressed',saved?'true':'false');
    var path=btn.querySelector('svg path');
    var label=btn.querySelector('.bookmark-label');
    if(saved){
      btn.classList.add('text-amber-600','border-amber-300','bg-amber-50');
      btn.classList.remove('text-slate-600');
      if(path) path.setAttribute('fill','currentColor');
      if(label) label.textContent='Saved';
    } else {
      btn.classList.remove('text-amber-600','border-amber-300','bg-amber-50');
      btn.classList.add('text-slate-600');
      if(path) path.removeAttribute('fill');
      if(label) label.textContent='Save';
    }
  }

  function initBtns(){
    document.querySelectorAll('[data-bookmark-btn]').forEach(function(btn){
      styleBtn(btn,has(btn.getAttribute('data-job-id')));
    });
  }

  function syncUI(){
    var count=get().length;
    var badge=document.getElementById('saved-jobs-count');
    if(badge) badge.textContent=count;
    var sbtn=document.getElementById('saved-jobs-btn');
    if(sbtn){ sbtn.style.display=count>0?'inline-flex':'none'; }
    var panel=document.getElementById('saved-jobs-panel');
    if(panel&&!panel.classList.contains('hidden')) renderPanel();
  }

  function renderPanel(){
    var list=document.getElementById('saved-jobs-list');
    if(!list) return;
    var bookmarks=get();
    if(!bookmarks.length){
      list.innerHTML='<p class="text-sm text-amber-800 text-center py-2">No saved jobs yet. Click Save on any card.</p>';
      return;
    }
    var html='<div class="space-y-2">';
    bookmarks.forEach(function(job){
      var jid=escHtml(String(job.id||''));
      html+='<div class="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm">'
        +'<div class="min-w-0"><p class="font-semibold text-slate-800 truncate">'+escHtml(job.title||'')+'</p>'
        +'<p class="text-slate-500 text-xs">'+escHtml(job.company||'')+(job.location?' · '+escHtml(job.location):'')+'</p></div>'
        +'<div class="flex items-center gap-2 flex-shrink-0">'
        +(job.link?'<a href="'+escHtml(job.link)+'" target="_blank" rel="noopener" class="text-brand text-xs font-medium hover:underline">Apply</a>':'')
        +'<button type="button" class="text-slate-400 hover:text-rose-500 transition" data-remove-bookmark="'+jid+'" aria-label="Remove saved job"><svg class="w-4 h-4" viewBox="0 0 24 24" fill="none"><path d="M6 18L18 6M6 6l12 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>'
        +'</div></div>';
    });
    html+='</div>';
    list.innerHTML=html;
  }

  document.addEventListener('click',function(e){
    // Bookmark toggle on card
    var bmBtn=e.target&&e.target.closest('[data-bookmark-btn]');
    if(bmBtn){
      e.preventDefault();
      var id=bmBtn.getAttribute('data-job-id');
      if(has(id)){
        remove(id); styleBtn(bmBtn,false);
        trackEvent('bookmark_remove',{job_id:id});
      } else {
        add({ id:id, title:bmBtn.getAttribute('data-job-title')||'',
              company:bmBtn.getAttribute('data-job-company')||'',
              location:bmBtn.getAttribute('data-job-location')||'',
              link:bmBtn.getAttribute('data-job-link')||'',
              date:bmBtn.getAttribute('data-job-date')||'' });
        styleBtn(bmBtn,true);
        trackEvent('bookmark_add',{job_id:id});
      }
      syncUI(); return;
    }
    // Remove from saved panel
    var rmBtn=e.target&&e.target.closest('[data-remove-bookmark]');
    if(rmBtn){
      var rmId=rmBtn.getAttribute('data-remove-bookmark');
      remove(rmId);
      var cardBtn=document.querySelector('[data-bookmark-btn][data-job-id="'+rmId+'"]');
      if(cardBtn) styleBtn(cardBtn,false);
      syncUI(); return;
    }
    // Toggle saved panel
    var savedToggle=e.target&&e.target.closest('#saved-jobs-btn');
    if(savedToggle){
      e.preventDefault();
      var panel=document.getElementById('saved-jobs-panel');
      if(!panel) return;
      var isOpen=!panel.classList.contains('hidden');
      panel.classList.toggle('hidden',isOpen);
      savedToggle.setAttribute('aria-expanded',String(!isOpen));
      if(!isOpen) renderPanel();
    }
  });

  window.__initBookmarks=function(){ initBtns(); syncUI(); };
  initBtns();
  syncUI();
})();

// ====================================================================
// FEATURE 3: PERSONALIZED SUBSCRIBE (search-aware dialog)
// ====================================================================
(function(){
  var subDialog =document.getElementById('subscribeDialog');
  if(!subDialog) return;
  var subTitle  =document.getElementById('subscribe-title');
  var subSub    =subDialog.querySelector('p.mt-2');
  var hidTitle  =document.getElementById('subscribe-search-title');
  var hidCountry=document.getElementById('subscribe-search-country');

  function getCtx(){
    try{
      var p=new URLSearchParams(window.location.search);
      return { title:p.get('title')||'', country:p.get('country')||'' };
    }catch(_){ return {title:'',country:''}; }
  }

  function personalize(){
    var ctx=getCtx();
    var t=ctx.title, c=ctx.country;
    if(hidTitle)   hidTitle.value=t;
    if(hidCountry) hidCountry.value=c;
    if(!subTitle)  return;
    if(t&&c){
      subTitle.textContent=(t.charAt(0).toUpperCase()+t.slice(1))+' jobs in '+c;
      if(subSub) subSub.textContent='Get fresh '+t+' roles in '+c+' — one email a week. Unsubscribe anytime.';
    } else if(t){
      subTitle.textContent=(t.charAt(0).toUpperCase()+t.slice(1))+' job alerts';
      if(subSub) subSub.textContent='Get the best '+t+' roles delivered weekly. Unsubscribe anytime.';
    } else if(c){
      subTitle.textContent='Top jobs in '+c;
      if(subSub) subSub.textContent='Weekly digest of high-signal roles in '+c+'. Unsubscribe anytime.';
    } else {
      subTitle.textContent='Weekly job reminders';
      if(subSub) subSub.textContent='One tidy email with new high-signal roles. Unsubscribe anytime.';
    }
  }

  document.addEventListener('click',function(e){
    if(e.target&&e.target.closest('[data-open-subscribe]')) setTimeout(personalize,0);
  });
  var toggle=document.getElementById('weekly-toggle');
  if(toggle) toggle.addEventListener('change',function(){ if(toggle.checked) setTimeout(personalize,0); });
})();

// ====================================================================
// FEATURE 4: SALARY EXPLORER WIDGET
// ====================================================================
(function(){
  var titleEl  =document.getElementById('salary-explorer-title');
  var countryEl=document.getElementById('salary-explorer-country');
  var btn      =document.getElementById('salary-explorer-btn');
  var resultEl =document.getElementById('salary-explorer-result');
  if(!titleEl||!resultEl) return;

  function fmt(val,cur){
    if(!val) return 'N/A';
    var sym=cur==='EUR'?'€':cur==='GBP'?'£':cur==='CHF'?'CHF ':'$';
    return val>=1000 ? sym+Math.round(val/1000)+'k' : sym+Math.round(val);
  }

  function explore(){
    var t=(titleEl.value||'').trim();
    var c=(countryEl?countryEl.value:'').trim();
    if(!t&&!c){
      resultEl.innerHTML='<p class="text-sm text-slate-500">Enter a role or country to see salary data.</p>';
      resultEl.classList.remove('hidden'); return;
    }
    resultEl.innerHTML='<p class="text-sm text-slate-400 animate-pulse">Loading salary data…</p>';
    resultEl.classList.remove('hidden');
    var params=new URLSearchParams();
    if(t) params.set('title',t);
    if(c) params.set('country',c);
    fetch('/api/jobs/summary?'+params.toString(),{credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(data){
        var count=data.count||0;
        var sal=data.salary||{};
        var med=sal.median, cur=sal.currency||'USD';
        var remote=Math.round((data.remote_share||0)*100);
        var lo=med?Math.round(med*0.8):null, hi=med?Math.round(med*1.2):null;

        var bar='';
        if(med){
          bar='<div class="mt-3">'
            +'<div class="flex justify-between text-[11px] text-slate-500 mb-1">'
            +'<span>'+fmt(lo,cur)+'</span>'
            +'<span class="font-semibold text-slate-800">~'+fmt(med,cur)+' median</span>'
            +'<span>'+fmt(hi,cur)+'</span></div>'
            +'<div class="relative h-2 rounded-full bg-slate-200">'
            +'<div class="absolute inset-0 rounded-full bg-gradient-to-r from-brand/40 to-brand"></div>'
            +'<div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 border-brand shadow"></div>'
            +'</div></div>';
        }

        resultEl.innerHTML='<div class="grid grid-cols-3 gap-3 text-center">'
          +'<div><p class="text-2xl font-bold text-slate-900">'+count+'</p><p class="text-xs text-slate-500">jobs found</p></div>'
          +'<div><p class="text-xl font-bold text-brand">'+(med?fmt(med,cur)+'/yr':'No data')+'</p><p class="text-xs text-slate-500">median salary</p></div>'
          +'<div><p class="text-2xl font-bold text-emerald-600">'+remote+'%</p><p class="text-xs text-slate-500">remote</p></div>'
          +'</div>'+bar;
        trackEvent('salary_explore',{title:t,country:c,median:med||0});
      })
      .catch(function(){
        resultEl.innerHTML='<p class="text-sm text-rose-600">Could not load salary data. Try again.</p>';
      });
  }

  if(btn) btn.addEventListener('click',explore);

  // Auto-explore if we landed with search params
  try{
    var p=new URLSearchParams(window.location.search);
    if(p.get('title')||p.get('country')){
      var det=document.getElementById('salary-explorer-details');
      if(det){ det.open=true; explore(); }
    }
  }catch(_){}
})();

// ====================================================================
// FEATURE 5: TITLE AUTOCOMPLETE (custom dropdown)
// ====================================================================
(function(){
  var titleInput=document.getElementById('q');
  if(!titleInput) return;
  var wrap=document.getElementById('q-wrap');
  if(!wrap) return;

  var drop=document.createElement('div');
  drop.id='autocomplete-drop';
  drop.setAttribute('role','listbox');
  drop.className='absolute left-0 right-0 top-full z-50 mt-1 rounded-xl border border-slate-200 bg-white shadow-lg overflow-hidden hidden';
  wrap.appendChild(drop);

  var debT=null, selIdx=-1, suggestions=[];

  function hide(){ drop.classList.add('hidden'); selIdx=-1; }

  function render(items){
    if(!items||!items.length){ hide(); return; }
    suggestions=items; selIdx=-1;
    drop.innerHTML='';
    items.forEach(function(s,i){
      var d=document.createElement('div');
      d.className='px-4 py-2.5 text-sm cursor-pointer hover:bg-slate-50 text-slate-800';
      d.setAttribute('role','option');
      d.setAttribute('data-idx',String(i));
      d.textContent=s;
      d.addEventListener('mousedown',function(e){
        e.preventDefault();
        titleInput.value=s;
        hide();
        titleInput.dispatchEvent(new Event('input',{bubbles:true}));
      });
      drop.appendChild(d);
    });
    drop.classList.remove('hidden');
  }

  function fetchAC(q){
    if(!q||q.length<2){ hide(); return; }
    fetch('/api/autocomplete?q='+encodeURIComponent(q),{credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){ render(d.suggestions||[]); })
      .catch(function(){});
  }

  titleInput.addEventListener('input',function(){
    clearTimeout(debT);
    debT=setTimeout(function(){ fetchAC((titleInput.value||'').trim()); },200);
  });

  titleInput.addEventListener('keydown',function(e){
    var opts=drop.querySelectorAll('[role="option"]');
    if(!opts.length||drop.classList.contains('hidden')) return;
    if(e.key==='ArrowDown'){ e.preventDefault(); selIdx=Math.min(selIdx+1,opts.length-1); }
    else if(e.key==='ArrowUp'){ e.preventDefault(); selIdx=Math.max(selIdx-1,-1); }
    else if(e.key==='Enter'&&selIdx>=0){
      e.preventDefault();
      titleInput.value=suggestions[selIdx];
      hide();
      titleInput.dispatchEvent(new Event('input',{bubbles:true}));
      return;
    } else if(e.key==='Escape'){ hide(); return; }
    else { return; }
    opts.forEach(function(el,i){
      el.classList.toggle('bg-slate-100',i===selIdx);
    });
  });

  titleInput.addEventListener('blur',function(){ setTimeout(hide,150); });
  document.addEventListener('click',function(e){
    if(!drop.contains(e.target)&&e.target!==titleInput) hide();
  });
})();

/* ── New-since-last-visit banner ─────────────────────────────── */
(function(){
  var LS_KEY = 'catalitium_last_visit';
  var banner  = document.getElementById('new-since-banner');
  var countEl = document.getElementById('new-since-text');
  if(!banner || !countEl) return;

  var lastVisit = localStorage.getItem(LS_KEY);
  /* Update timestamp for next visit */
  localStorage.setItem(LS_KEY, new Date().toISOString());
  if(!lastVisit) return; /* First visit — nothing to compare */

  var lastTs = new Date(lastVisit).getTime();
  if(!lastTs) return;

  function countNew(){
    var articles = document.querySelectorAll('[data-job-date]');
    var n = 0;
    articles.forEach(function(el){
      var d = el.getAttribute('data-job-date');
      if(d && new Date(d).getTime() > lastTs) n++;
    });
    return n;
  }

  function showBanner(){
    var n = countNew();
    if(n < 1) return;
    countEl.textContent = n + ' new listing' + (n === 1 ? '' : 's') + ' since your last visit';
    banner.classList.remove('hidden');
  }

  /* Run once on load, then again after instant-search fetches replace the DOM */
  showBanner();
  document.addEventListener('catalitium:results-updated', showBanner);
})();

/* ── Market Trends chart ─────────────────────────────────────── */
(function(){
  var details = document.getElementById('trends-details');
  if(!details) return;

  var chartEl = document.getElementById('trends-chart');
  var radios  = document.querySelectorAll('input[name="trend-cat"]');
  if(!chartEl) return;

  var cache = null;

  function renderChart(data, cat){
    if(!data || !data.weeks || !data.weeks.length){
      chartEl.innerHTML = '<p class="text-xs text-slate-400 text-center py-4">No trend data yet.</p>';
      return;
    }
    var weeks = data.weeks;
    var vals  = weeks.map(function(w){ return w[cat] || 0; });
    var max   = Math.max.apply(null, vals) || 1;
    var barW  = Math.floor(560 / weeks.length) - 4;
    barW = Math.max(barW, 8);

    var bars = weeks.map(function(w, i){
      var v   = w[cat] || 0;
      var h   = Math.round((v / max) * 80);
      var x   = i * (barW + 4) + 2;
      var y   = 90 - h;
      var lbl = (w.week||'').slice(5,10); /* MM-DD */
      return '<rect x="'+x+'" y="'+y+'" width="'+barW+'" height="'+h+'" rx="2" fill="#1a73e8" opacity="0.8"/>'
           + '<text x="'+(x+barW/2)+'" y="106" text-anchor="middle" font-size="8" fill="#94a3b8">'+lbl+'</text>'
           + (v ? '<text x="'+(x+barW/2)+'" y="'+(y-3)+'" text-anchor="middle" font-size="8" fill="#475569">'+v+'</text>' : '');
    }).join('');

    var svgW = weeks.length * (barW + 4) + 4;
    chartEl.innerHTML = '<svg viewBox="0 0 '+svgW+' 114" width="100%" style="max-height:130px">'
      +'<line x1="0" y1="90" x2="'+svgW+'" y2="90" stroke="#e2e8f0" stroke-width="1"/>'
      + bars
      +'</svg>';
  }

  function load(){
    if(cache){ renderChart(cache, getActiveCat()); return; }
    chartEl.innerHTML = '<p class="text-xs text-slate-400 text-center py-4">Loading…</p>';
    fetch('/api/trends', { credentials:'same-origin' })
      .then(function(r){ return r.json(); })
      .then(function(d){ cache=d; renderChart(d, getActiveCat()); })
      .catch(function(){ chartEl.innerHTML='<p class="text-xs text-red-400 text-center py-4">Could not load trends.</p>'; });
  }

  function getActiveCat(){
    var checked = document.querySelector('input[name="trend-cat"]:checked');
    return checked ? checked.value : 'total';
  }

  radios.forEach(function(r){
    r.addEventListener('change', function(){
      if(cache) renderChart(cache, getActiveCat());
    });
  });

  details.addEventListener('toggle', function(){
    if(details.open) load();
  });

  /* Auto-load if already open on page load */
  if(details.open) load();
})();
