(function () {
  'use strict';

  // ── Helpers ───────────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }

  // ── CSS ───────────────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.id = 'cat-chat-css';
  style.textContent = `
    #cat-chat-btn{position:fixed;bottom:calc(20px + env(safe-area-inset-bottom, 0px));right:20px;z-index:9999;width:52px;height:52px;border-radius:50%;background:#0f172a;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(0,0,0,.3);transition:transform .15s}
    #cat-chat-btn:hover{transform:scale(1.07)}
    #cat-chat-badge{position:absolute;top:4px;right:4px;background:#ef4444;color:#fff;font-size:10px;font-weight:700;border-radius:99px;min-width:16px;height:16px;line-height:16px;text-align:center;padding:0 4px}
    #cat-chat-panel{position:fixed;bottom:calc(82px + env(safe-area-inset-bottom, 0px));right:20px;z-index:9999;width:320px;max-height:calc(100vh - 110px);background:#fff;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,.18);display:flex;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;opacity:0;transform:translateY(12px);pointer-events:none;transition:opacity .2s ease,transform .2s ease}
    #cat-chat-panel.cat-open{opacity:1;transform:translateY(0);pointer-events:auto}
    #cat-chat-header{background:#0f172a;color:#fff;padding:14px 16px;display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
    #cat-chat-header-text{display:flex;flex-direction:column;gap:2px}
    #cat-chat-header strong{font-size:14px;font-weight:700}
    #cat-chat-header span{font-size:11px;color:#94a3b8}
    #cat-chat-close{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:18px;line-height:1;padding:0;margin-top:-2px}
    #cat-chat-close:hover{color:#fff}
    #cat-chat-messages{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;max-height:320px;min-height:120px}
    .cat-msg{max-width:85%;padding:8px 12px;border-radius:12px;line-height:1.45;word-wrap:break-word}
    .cat-msg-bot{align-self:flex-start;background:#f1f5f9;color:#1e293b;border-bottom-left-radius:3px}
    .cat-msg-user{align-self:flex-end;background:#0f172a;color:#fff;border-bottom-right-radius:3px}
    .cat-cta-btn{display:inline-block;margin-top:7px;background:#2563eb;color:#fff !important;text-decoration:none;font-size:11px;font-weight:600;padding:5px 10px;border-radius:99px;white-space:nowrap}
    .cat-cta-btn:hover{background:#1d4ed8}
    .cat-chips{display:flex;flex-wrap:wrap;gap:6px;padding:4px 0 2px}
    .cat-chip{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:99px;padding:5px 10px;font-size:12px;cursor:pointer;color:#1e293b;line-height:1}
    .cat-chip:hover{background:#e2e8f0}
    .cat-thumbs{display:inline-flex;gap:6px;margin-top:6px}
    .cat-thumb{background:none;border:none;cursor:pointer;font-size:14px;opacity:.6;padding:0}
    .cat-thumb:hover{opacity:1}
    .cat-typing{align-self:flex-start;background:#f1f5f9;border-radius:12px;border-bottom-left-radius:3px;padding:10px 14px;display:flex;gap:4px}
    .cat-dot{width:6px;height:6px;background:#94a3b8;border-radius:50%;animation:cat-bounce .9s infinite}
    .cat-dot:nth-child(2){animation-delay:.15s}
    .cat-dot:nth-child(3){animation-delay:.3s}
    @keyframes cat-bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-5px)}}
    #cat-chat-footer{display:flex;flex-direction:column;border-top:1px solid #e2e8f0}
    #cat-chat-input-row{display:flex;padding:8px;gap:6px}
    #cat-chat-input{flex:1;border:1px solid #e2e8f0;border-radius:8px;padding:7px 10px;font-size:13px;outline:none;background:#f8fafc}
    #cat-chat-input:focus{border-color:#2563eb}
    #cat-chat-send{background:#0f172a;color:#fff;border:none;border-radius:8px;padding:7px 12px;cursor:pointer;font-size:15px;line-height:1;transition:opacity .15s}
    #cat-chat-send:disabled{opacity:.35;cursor:default}
    #cat-chat-send:not(:disabled):hover{background:#1e293b}
    #cat-char-count{font-size:10px;color:#94a3b8;text-align:right;padding:0 10px 6px;display:none}
    @media(max-width:480px){#cat-chat-panel{width:calc(100vw - 40px);right:20px;border-radius:12px}}
  `;
  document.head.appendChild(style);

  // ── HTML ──────────────────────────────────────────────────────────────────
  var btn = document.createElement('button');
  btn.id = 'cat-chat-btn';
  btn.setAttribute('aria-label', 'Open career advisor chat');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML =
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg><span id="cat-chat-badge">1</span>';

  var panel = document.createElement('div');
  panel.id = 'cat-chat-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Career Advisor Chat');
  panel.innerHTML =
    '<div id="cat-chat-header">' +
      '<div id="cat-chat-header-text">' +
        '<strong>Catalitium Career Advisor</strong>' +
        '<span>Ask me anything about salaries &amp; jobs in DACH</span>' +
      '</div>' +
      '<button id="cat-chat-close" aria-label="Close chat">&times;</button>' +
    '</div>' +
    '<div id="cat-chat-messages" role="log" aria-live="polite"></div>' +
    '<div id="cat-chat-footer">' +
      '<div id="cat-chat-input-row">' +
        '<input id="cat-chat-input" type="text" placeholder="Ask about salaries, jobs, visa..." autocomplete="off" maxlength="200">' +
        '<button id="cat-chat-send" aria-label="Send" disabled>&#10148;</button>' +
      '</div>' +
      '<div id="cat-char-count"></div>' +
    '</div>';

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  // ── State ─────────────────────────────────────────────────────────────────
  var exchangeCount = 0;
  var escalationSent = false;
  var messagesEl = $('cat-chat-messages');
  var inputEl    = $('cat-chat-input');
  var sendBtn    = $('cat-chat-send');
  var badge      = $('cat-chat-badge');
  var charCount  = $('cat-char-count');

  // ── Page context ──────────────────────────────────────────────────────────
  var path = window.location.pathname;
  var pageCtx = path.indexOf('/salary') === 0 ? 'salary'
              : (path === '/jobs' || path.indexOf('/jobs') === 0) ? 'jobs'
              : 'default';

  // data-salary-median/data-salary-role injected by salary templates
  var ctxEl = document.querySelector('[data-salary-median]');
  var ctxSalary = ctxEl ? { median: ctxEl.dataset.salaryMedian, role: ctxEl.dataset.salaryRole } : null;

  function openingMessage() {
    if (pageCtx === 'salary' && ctxSalary) {
      return '👋 You\'re looking at salaries for ' + ctxSalary.role + '. The DACH median is ' + ctxSalary.median + '. Want a personalised benchmark for your level?';
    }
    if (pageCtx === 'salary') {
      return '👋 Looks like you\'re exploring salaries. Want a personalised DACH benchmark for your role?';
    }
    if (pageCtx === 'jobs') {
      return '👋 Browsing jobs? I can help you filter by role, city, or salary range. What are you targeting?';
    }
    return '👋 Hi! I\'m your Catalitium Career Advisor. I can help you benchmark your salary, find jobs, or prep for a negotiation. What\'s on your mind?';
  }

  var CHIPS = [
    { label: '💰 Salary', key: 'salary' },
    { label: '💼 Jobs',   key: 'jobs' },
    { label: '🤝 Negotiate', key: 'negotiate' },
    { label: '🇨🇭 Visa',   key: 'visa' }
  ];

  var ESCALATION = {
    text: 'By the way, if you want a real expert to review your situation, our coaches are available this week.',
    cta: { label: 'Book a Free 15-min Call →', href: '/negotiate' }
  };

  // ── Response engine (score-based) ─────────────────────────────────────────
  var RULES = [
    {
      topic: 'salary',
      keywords: ['salary','pay','worth','earning','compensation','make','paid','underpaid','overpaid','income'],
      text: ctxSalary
        ? 'For ' + (ctxSalary.role||'this role') + ' our data shows a DACH median of ' + ctxSalary.median + '. Use the calculator to adjust for your level and city.'
        : 'Based on our DACH data, Senior SWEs in Zurich earn CHF 110k–155k. What\'s your role and level?',
      cta: { label: 'Check Salary Calculator →', href: '/salary-tool' }
    },
    {
      topic: 'negotiate',
      keywords: ['negotiate','negotiat','offer','counter','raise','promotion','lowball','leverage','package','stock','equity','bonus'],
      text: 'Negotiating? Most offers have 15–25% flex in DACH. Our coaches have unlocked CHF 2.1M+ for clients.',
      cta: { label: 'Book a Negotiation Coach →', href: '/negotiate' }
    },
    {
      topic: 'jobs',
      keywords: ['job','jobs','hiring','opening','apply','find','looking','role','position','vacancy','work','career'],
      text: 'We have live tech roles across Zurich, Geneva, Basel and Berlin. What role are you targeting?',
      cta: { label: 'Browse Open Jobs →', href: '/jobs' }
    },
    {
      topic: 'visa',
      keywords: ['visa','permit','swiss','b permit','work permit','relocate','expat','canton','immigration','residency'],
      text: 'Switzerland requires a minimum salary for work permits, varies by canton and role. Want me to check if an offer qualifies?',
      cta: { label: 'Check Permit Eligibility →', href: '/salary/work-permit' }
    },
    {
      topic: 'internship',
      keywords: ['intern','internship','junior','graduate','entry','first job','student','apprentice','trainee'],
      text: 'Internships in Zurich at top companies pay CHF 2,500–5,000/month. FAANG internships can hit CHF 8,000+.',
      cta: { label: 'See Internship Salaries →', href: '/salary/by-title' }
    },
    {
      topic: 'greeting',
      keywords: ['hi','hello','hey','start','help','sup','yo','greet'],
      text: 'Hey! I can help you with: 💰 Salary benchmarks | 💼 Open jobs | 🤝 Offer negotiation | 🇨🇭 Work permits. What are you looking for?'
    }
  ];

  var FALLBACK = {
    topic: 'fallback',
    text: 'Good question, that one\'s better answered by a human. Our career coaches specialise in DACH tech compensation.',
    cta: { label: 'Talk to a Coach →', href: '/negotiate' }
  };

  function getResponse(input) {
    var s = input.toLowerCase();
    var best = null, bestScore = 0;
    for (var i = 0; i < RULES.length; i++) {
      var score = 0;
      for (var j = 0; j < RULES[i].keywords.length; j++) {
        if (s.indexOf(RULES[i].keywords[j]) !== -1) score++;
      }
      if (score > bestScore) { bestScore = score; best = RULES[i]; }
    }
    return best || FALLBACK;
  }

  // ── DOM builders ──────────────────────────────────────────────────────────
  function botReply(text, cta, topic) {
    hideTyping();
    var wrap = document.createElement('div');
    wrap.className = 'cat-msg cat-msg-bot';

    var txt = document.createElement('span');
    txt.textContent = text;
    wrap.appendChild(txt);

    if (cta) {
      var a = document.createElement('a');
      a.className = 'cat-cta-btn';
      a.href = cta.href;
      a.textContent = cta.label;
      a.addEventListener('click', function () { gtmPush('chat_cta_click', topic || '', cta.href); });
      wrap.appendChild(a);
    }

    // 👍👎 feedback
    var thumbs = document.createElement('div');
    thumbs.className = 'cat-thumbs';
    ['👍','👎'].forEach(function (emoji, idx) {
      var b = document.createElement('button');
      b.className = 'cat-thumb';
      b.textContent = emoji;
      b.setAttribute('aria-label', idx === 0 ? 'Helpful' : 'Not helpful');
      b.addEventListener('click', function () {
        thumbs.innerHTML = '<span style="font-size:11px;color:#64748b">Thanks!</span>';
        saveFeedback(text, topic || '', idx === 0);
      });
      thumbs.appendChild(b);
    });
    wrap.appendChild(thumbs);

    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addUserMsg(text) {
    var wrap = document.createElement('div');
    wrap.className = 'cat-msg cat-msg-user';
    wrap.textContent = text;
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addChips() {
    var row = document.createElement('div');
    row.className = 'cat-chips';
    row.id = 'cat-chips-row';
    CHIPS.forEach(function (c) {
      var b = document.createElement('button');
      b.className = 'cat-chip';
      b.textContent = c.label;
      b.addEventListener('click', function () {
        row.remove();
        send(c.key);
      });
      row.appendChild(b);
    });
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  var typingEl = null;
  function showTyping() {
    typingEl = document.createElement('div');
    typingEl.className = 'cat-typing';
    typingEl.innerHTML = '<div class="cat-dot"></div><div class="cat-dot"></div><div class="cat-dot"></div>';
    messagesEl.appendChild(typingEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  function hideTyping() { if (typingEl) { typingEl.remove(); typingEl = null; } }

  // ── Integrations ──────────────────────────────────────────────────────────
  function gtmPush(event, topic, href) {
    if (window.dataLayer) {
      var payload = { event: event, chat_topic: topic };
      if (href) payload.cta_href = href;
      window.dataLayer.push(payload);
    }
  }

  function saveFeedback(text, topic, helpful) {
    try {
      var key = 'cat_chat_feedback';
      var arr = JSON.parse(localStorage.getItem(key) || '[]');
      arr.push({ ts: Date.now(), text: text, topic: topic, helpful: helpful });
      if (arr.length > 50) arr.shift();
      localStorage.setItem(key, JSON.stringify(arr));
    } catch (e) {}
  }

  // ── Core send ─────────────────────────────────────────────────────────────
  function send(text) {
    text = (text || '').trim();
    if (!text) return;
    var chipsRow = $('cat-chips-row');
    if (chipsRow) chipsRow.remove();

    addUserMsg(text);
    exchangeCount++;

    if (exchangeCount === 3 && !escalationSent) {
      escalationSent = true;
      botReply(ESCALATION.text, ESCALATION.cta, 'escalation');
    }

    var resp = getResponse(text);
    gtmPush('chat_send', resp.topic, '');
    showTyping();
    setTimeout(function () { botReply(resp.text, resp.cta || null, resp.topic); }, 220);
  }

  // ── Open / close ──────────────────────────────────────────────────────────
  function openPanel() {
    panel.classList.add('cat-open');
    btn.setAttribute('aria-expanded', 'true');
    badge.style.display = 'none';
    if (window.innerWidth > 600) inputEl.focus();
    if (messagesEl.children.length === 0) {
      setTimeout(function () {
        botReply(openingMessage(), null, 'greeting');
        addChips();
      }, 600);
    }
  }

  function closePanel() {
    panel.classList.remove('cat-open');
    btn.setAttribute('aria-expanded', 'false');
  }

  btn.addEventListener('click', function () {
    panel.classList.contains('cat-open') ? closePanel() : openPanel();
  });
  $('cat-chat-close').addEventListener('click', closePanel);

  // ── Input events ──────────────────────────────────────────────────────────
  inputEl.addEventListener('input', function () {
    var len = inputEl.value.length;
    sendBtn.disabled = len === 0;
    if (len > 150) {
      charCount.style.display = 'block';
      charCount.textContent = len + '/200';
    } else {
      charCount.style.display = 'none';
    }
  });

  sendBtn.addEventListener('click', function () {
    send(inputEl.value);
    inputEl.value = '';
    sendBtn.disabled = true;
    charCount.style.display = 'none';
    inputEl.focus();
  });

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && inputEl.value.trim()) {
      send(inputEl.value);
      inputEl.value = '';
      sendBtn.disabled = true;
      charCount.style.display = 'none';
    }
  });

}());
