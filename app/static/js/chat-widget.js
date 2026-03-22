(function () {
  'use strict';

  // ── CSS ──────────────────────────────────────────────────────────────────
  var css = [
    '#cat-chat-btn{position:fixed;bottom:20px;right:20px;z-index:9999;width:52px;height:52px;border-radius:50%;background:#0f172a;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(0,0,0,.3);transition:transform .15s}',
    '#cat-chat-btn:hover{transform:scale(1.07)}',
    '#cat-chat-badge{position:absolute;top:4px;right:4px;background:#ef4444;color:#fff;font-size:10px;font-weight:700;border-radius:99px;min-width:16px;height:16px;line-height:16px;text-align:center;padding:0 4px}',
    '#cat-chat-panel{position:fixed;bottom:82px;right:20px;z-index:9999;width:320px;background:#fff;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,.18);display:flex;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px}',
    '#cat-chat-header{background:#0f172a;color:#fff;padding:14px 16px;display:flex;align-items:flex-start;justify-content:space-between;gap:8px}',
    '#cat-chat-header-text{display:flex;flex-direction:column;gap:2px}',
    '#cat-chat-header strong{font-size:14px;font-weight:700}',
    '#cat-chat-header span{font-size:11px;color:#94a3b8}',
    '#cat-chat-close{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:18px;line-height:1;padding:0;margin-top:-2px}',
    '#cat-chat-close:hover{color:#fff}',
    '#cat-chat-messages{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;max-height:320px;min-height:120px}',
    '.cat-msg{max-width:85%;padding:8px 12px;border-radius:12px;line-height:1.45;word-wrap:break-word}',
    '.cat-msg-bot{align-self:flex-start;background:#f1f5f9;color:#1e293b;border-bottom-left-radius:3px}',
    '.cat-msg-user{align-self:flex-end;background:#0f172a;color:#fff;border-bottom-right-radius:3px}',
    '.cat-cta-btn{display:inline-block;margin-top:7px;background:#2563eb;color:#fff !important;text-decoration:none;font-size:11px;font-weight:600;padding:5px 10px;border-radius:99px;white-space:nowrap}',
    '.cat-cta-btn:hover{background:#1d4ed8}',
    '#cat-chat-input-row{display:flex;border-top:1px solid #e2e8f0;padding:8px}',
    '#cat-chat-input{flex:1;border:1px solid #e2e8f0;border-radius:8px;padding:7px 10px;font-size:13px;outline:none;background:#f8fafc}',
    '#cat-chat-input:focus{border-color:#2563eb}',
    '#cat-chat-send{margin-left:6px;background:#0f172a;color:#fff;border:none;border-radius:8px;padding:7px 12px;cursor:pointer;font-size:15px;line-height:1}',
    '#cat-chat-send:hover{background:#1e293b}',
    '@media(max-width:400px){#cat-chat-panel{width:calc(100vw - 40px);right:20px}}'
  ].join('');

  var style = document.createElement('style');
  style.id = 'cat-chat-css';
  style.textContent = css;
  document.head.appendChild(style);

  // ── HTML ─────────────────────────────────────────────────────────────────
  var btn = document.createElement('button');
  btn.id = 'cat-chat-btn';
  btn.setAttribute('aria-label', 'Open career advisor chat');
  btn.innerHTML =
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg>' +
    '<span id="cat-chat-badge">1</span>';

  var panel = document.createElement('div');
  panel.id = 'cat-chat-panel';
  panel.hidden = true;
  panel.innerHTML =
    '<div id="cat-chat-header">' +
      '<div id="cat-chat-header-text">' +
        '<strong>Catalitium Career Advisor</strong>' +
        '<span>Ask me anything about salaries &amp; jobs in DACH</span>' +
      '</div>' +
      '<button id="cat-chat-close" aria-label="Close chat">&times;</button>' +
    '</div>' +
    '<div id="cat-chat-messages"></div>' +
    '<div id="cat-chat-input-row">' +
      '<input id="cat-chat-input" type="text" placeholder="Ask about salaries, jobs, visa..." autocomplete="off" maxlength="200">' +
      '<button id="cat-chat-send" aria-label="Send">&#10148;</button>' +
    '</div>';

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  // ── State ────────────────────────────────────────────────────────────────
  var exchangeCount = 0;
  var openedOnce = false;
  var escalationSent = false;

  var ESCALATION = {
    text: 'By the way — if you want a real expert to review your situation, our coaches are available this week.',
    cta: { label: 'Book a Free 15-min Call →', href: '/negotiate' }
  };

  var OPENING =
    '👋 Hi! I\'m your Catalitium Career Advisor. I can help you benchmark your salary, find jobs in DACH, or prep for a negotiation. What\'s on your mind?';

  // ── Response engine ───────────────────────────────────────────────────────
  function getResponse(input) {
    var s = input.toLowerCase();
    function has(words) { return words.some(function (w) { return s.indexOf(w) !== -1; }); }

    if (has(['salary','pay','worth','earning','compensation','make'])) {
      return {
        text: 'Based on our DACH data, Senior SWEs in Zurich earn CHF 110k–155k. What\'s your role and level?',
        cta: { label: 'Check Salary Calculator →', href: '/salary-tool' }
      };
    }
    if (has(['negotiate','offer','counter','raise','promotion'])) {
      return {
        text: 'Negotiating? Most offers have 15–25% flex in DACH. Our coaches have unlocked CHF 2.1M+ for clients.',
        cta: { label: 'Book a Negotiation Coach →', href: '/negotiate' }
      };
    }
    if (has(['job','jobs','hiring','opening','apply','find','looking'])) {
      return {
        text: 'We have live tech roles across Zurich, Geneva, Basel and Berlin. What role are you targeting?',
        cta: { label: 'Browse Open Jobs →', href: '/jobs' }
      };
    }
    if (has(['visa','permit','swiss','b permit','work permit','relocate','expat'])) {
      return {
        text: 'Switzerland requires a minimum salary for work permits — varies by canton and role. Want me to check if an offer qualifies?',
        cta: { label: 'Check Permit Eligibility →', href: '/salary/work-permit' }
      };
    }
    if (has(['intern','internship','junior','graduate','entry','first job','student'])) {
      return {
        text: 'Internships in Zurich at top companies pay CHF 2,500–5,000/month. FAANG internships can hit CHF 8,000+.',
        cta: { label: 'See Internship Salaries →', href: '/salary/by-title' }
      };
    }
    if (has(['hi','hello','hey','start','help'])) {
      return {
        text: 'Hey! I can help you with: 💰 Salary benchmarks | 💼 Open jobs | 🤝 Offer negotiation | 🇨🇭 Work permits. What are you looking for?'
      };
    }
    return {
      text: 'Good question — that one\'s better answered by a human. Our career coaches specialise in DACH tech compensation.',
      cta: { label: 'Talk to a Coach →', href: '/negotiate' }
    };
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────
  var messagesEl = document.getElementById('cat-chat-messages');

  function addMessage(role, text, cta) {
    var wrap = document.createElement('div');
    wrap.className = 'cat-msg ' + (role === 'user' ? 'cat-msg-user' : 'cat-msg-bot');

    var p = document.createElement('span');
    p.textContent = text;
    wrap.appendChild(p);

    if (cta) {
      var a = document.createElement('a');
      a.className = 'cat-cta-btn';
      a.href = cta.href;
      a.textContent = cta.label;
      a.target = '_self';
      var br = document.createElement('br');
      wrap.appendChild(br);
      wrap.appendChild(a);
    }

    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function send(text) {
    text = text.trim();
    if (!text) return;

    addMessage('user', text);
    exchangeCount++;

    // Escalation after 3 exchanges (once only)
    if (exchangeCount === 3 && !escalationSent) {
      escalationSent = true;
      addMessage('bot', ESCALATION.text, ESCALATION.cta);
    }

    var resp = getResponse(text);
    addMessage('bot', resp.text, resp.cta || null);
  }

  // ── Event listeners ───────────────────────────────────────────────────────
  var inputEl = document.getElementById('cat-chat-input');
  var badge   = document.getElementById('cat-chat-badge');

  btn.addEventListener('click', function () {
    var isOpen = !panel.hidden;
    panel.hidden = isOpen;
    btn.setAttribute('aria-expanded', String(!isOpen));
    if (!isOpen) {
      badge.style.display = 'none';
      inputEl.focus();
      if (!openedOnce) {
        openedOnce = true;
        setTimeout(function () { addMessage('bot', OPENING); }, 600);
      }
    }
  });

  document.getElementById('cat-chat-close').addEventListener('click', function () {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  });

  document.getElementById('cat-chat-send').addEventListener('click', function () {
    send(inputEl.value);
    inputEl.value = '';
    inputEl.focus();
  });

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      send(inputEl.value);
      inputEl.value = '';
    }
  });

}());
