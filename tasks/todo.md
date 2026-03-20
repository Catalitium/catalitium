# Catalitium — User Registration via Supabase Auth

## Cursor One-Shot Prompt

> Paste the block below directly into Cursor Composer (Cmd/Ctrl+I).
> Attach these files as context before pasting:
>   - app/app.py
>   - app/models/db.py
>   - app/views/templates/base.html
>   - requirements.txt
>   - .env.example

---

```
You are a senior Flask developer. Add Supabase email+password user registration
and login to the Catalitium job board. The app is a single-file Flask app
(app/app.py, ~2350 lines) using Supabase PostgreSQL as its database.
Supabase Auth keys already exist in .env. DO NOT break any existing routes.

## Tech context
- Flask 3.1.3, Python 3.11, Jinja2 templates at app/views/templates/
- Tailwind CSS via CDN (brand color classes: text-brand, bg-brand, border-brand)
- SUPABASE_PUBLISHABLE_KEY and SUPABASE_SECRET_KEY exist in .env and .env.example
  Use SUPABASE_SECRET_KEY (service_role key) for all server-side auth calls
- SESSION_COOKIE_SECURE, SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE already set
- Flask session stores a dict; use session["user"] = {"id": ..., "email": ...} post-login
- Rate limiting helper _limit(rule) exists in app.py -- reuse it on auth routes
- validate_email() from email_validator is already imported in app.py -- reuse it
- Flash messages pattern already in base.html -- reuse it for auth errors

## What to build (minimal, no over-engineering)

### 1. requirements.txt
Add one line after existing deps:
  supabase==2.10.0

### 2. app/app.py -- module-level Supabase client (add BEFORE create_app())

  try:
      from supabase import create_client as _sb_create_client
  except ImportError:
      _sb_create_client = None

  _supabase_client = None

  def _get_supabase():
      global _supabase_client
      if _supabase_client is None and _sb_create_client:
          url = os.getenv("SUPABASE_URL", "").replace("postgresql://", "https://", 1).split("@")[-1]
          # Use the Supabase project URL format: https://<ref>.supabase.co
          project_url = os.getenv("SUPABASE_PROJECT_URL", "").strip()
          key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
          if project_url and key:
              _supabase_client = _sb_create_client(project_url, key)
      return _supabase_client

  NOTE: also add SUPABASE_PROJECT_URL to .env.example as:
    # Supabase project URL (format: https://<ref>.supabase.co)
    SUPABASE_PROJECT_URL=https://your-project-ref.supabase.co

### 3. app/app.py -- 4 new routes inside create_app()

Follow the exact pattern of the existing /subscribe route (around line 1276).
Add these 4 routes after the /subscribe route block:

  @app.route("/register", methods=["GET", "POST"])
  @_limit("10 per minute")
  def register():
      if session.get("user"):
          return redirect(url_for("studio"))
      if request.method == "GET":
          return render_template("register.html", tab="signup")

      action = request.form.get("action", "signup")  # "signup" or "login"
      email = (request.form.get("email") or "").strip()
      password = (request.form.get("password") or "").strip()

      try:
          email = validate_email(email, check_deliverability=False).normalized
      except Exception:
          flash("Please enter a valid email.", "error")
          return render_template("register.html", tab=action), 400

      sb = _get_supabase()
      if not sb:
          flash("Auth service unavailable.", "error")
          return render_template("register.html", tab=action), 503

      try:
          if action == "signup":
              res = sb.auth.sign_up({"email": email, "password": password})
          else:
              res = sb.auth.sign_in_with_password({"email": email, "password": password})
          user = res.user
          if not user:
              flash("Invalid credentials. Please try again.", "error")
              return render_template("register.html", tab=action), 401
          session["user"] = {"id": str(user.id), "email": user.email}
          return redirect(url_for("studio"))
      except Exception as exc:
          logger.warning("auth error (%s): %s", action, exc)
          flash(str(exc)[:120], "error")
          return render_template("register.html", tab=action), 400

  @app.get("/logout")
  def logout():
      session.pop("user", None)
      return redirect(url_for("index"))

  @app.get("/studio")
  def studio():
      user = session.get("user")
      if not user:
          return redirect(url_for("register"))
      return render_template("studio.html", user=user)

### 4. app/views/templates/register.html (NEW FILE)

{% extends "base.html" %}
{% block title %}Sign in | Catalitium{% endblock %}
{% block content %}
<div class="mx-auto max-w-md mt-12 px-4">
  <!-- Tab switcher -->
  <div class="flex rounded-xl border border-slate-200 overflow-hidden mb-6">
    <button type="button" id="tab-signup"
      class="flex-1 py-3 text-sm font-semibold transition-colors {{ 'bg-brand text-white' if tab == 'signup' else 'bg-white text-slate-600 hover:bg-slate-50' }}"
      onclick="switchTab('signup')">Create account</button>
    <button type="button" id="tab-login"
      class="flex-1 py-3 text-sm font-semibold transition-colors {{ 'bg-brand text-white' if tab == 'login' else 'bg-white text-slate-600 hover:bg-slate-50' }}"
      onclick="switchTab('login')">Sign in</button>
  </div>

  <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
    <form method="post" action="{{ url_for('register') }}" class="space-y-4">
      <input type="hidden" name="action" id="action-input" value="{{ tab }}">
      <div>
        <label for="email" class="block text-sm font-medium text-slate-700 mb-1">Email</label>
        <input id="email" name="email" type="email" required autocomplete="email"
          class="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-base focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
          placeholder="you@example.com">
      </div>
      <div>
        <label for="password" class="block text-sm font-medium text-slate-700 mb-1">Password</label>
        <input id="password" name="password" type="password" required minlength="8"
          autocomplete="current-password"
          class="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-base focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
          placeholder="Min 8 characters">
      </div>
      <button type="submit"
        class="w-full rounded-xl bg-brand px-4 py-3 text-base font-semibold text-white hover:bg-brand/90 transition-colors">
        <span id="btn-label">{{ 'Create account' if tab == 'signup' else 'Sign in' }}</span>
      </button>
    </form>
  </div>
</div>
<script>
function switchTab(t) {
  document.getElementById('action-input').value = t;
  document.getElementById('btn-label').textContent = t === 'signup' ? 'Create account' : 'Sign in';
  ['signup','login'].forEach(function(id) {
    var btn = document.getElementById('tab-' + id);
    if (id === t) { btn.classList.add('bg-brand','text-white'); btn.classList.remove('bg-white','text-slate-600'); }
    else { btn.classList.remove('bg-brand','text-white'); btn.classList.add('bg-white','text-slate-600'); }
  });
}
</script>
{% endblock %}

### 5. app/views/templates/studio.html (NEW FILE)

{% extends "base.html" %}
{% block title %}My Studio | Catalitium{% endblock %}
{% block content %}
<div class="mx-auto max-w-4xl px-4 py-10">
  <div class="flex items-center justify-between mb-8">
    <div>
      <p class="text-xs font-semibold uppercase tracking-widest text-slate-400">Your dashboard</p>
      <h1 class="mt-1 text-2xl font-semibold text-slate-900">Welcome back</h1>
      <p class="mt-1 text-sm text-slate-500">{{ user.email }}</p>
    </div>
    <a href="{{ url_for('logout') }}"
       class="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:border-slate-300 hover:text-slate-900 transition-colors">
      Sign out
    </a>
  </div>

  <div class="rounded-2xl border border-slate-200 bg-slate-50 px-6 py-8 text-center">
    <p class="text-base font-medium text-slate-700">Saved searches</p>
    <p class="mt-2 text-sm text-slate-400">No saved searches yet. Search for jobs and save your filters.</p>
    <a href="{{ url_for('index') }}"
       class="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand/90 transition-colors">
      Browse jobs
    </a>
  </div>
</div>
{% endblock %}

### 6. app/views/templates/base.html -- navbar update

In the desktop nav ml-auto div (after the "Submit job" link, around line 124),
INSERT before the closing </div>:

  <div class="border-l border-slate-200 h-5"></div>
  {% if session.get("user") %}
    <a href="{{ url_for('studio') }}"
       class="px-3 py-2 rounded-lg text-sm font-medium text-brand hover:bg-brand/5 transition-colors">
      My Account
    </a>
  {% else %}
    <a href="{{ url_for('register') }}"
       class="px-3 py-2 rounded-lg text-sm font-medium text-brand hover:bg-brand/5 transition-colors">
      Sign in
    </a>
  {% endif %}

In the mobile navsheet primary nav ul (around line 189), add as last list item:

  {% if session.get("user") %}
    <li><a class="block rounded-lg px-3 py-3 hover:bg-slate-50 hover:text-brand" href="{{ url_for('studio') }}">My Account</a></li>
  {% else %}
    <li><a class="block rounded-lg px-3 py-3 hover:bg-slate-50 hover:text-brand font-semibold text-brand" href="{{ url_for('register') }}">Sign in</a></li>
  {% endif %}

## Constraints
- Do NOT use Flask-Login, Flask-WTF, or any new auth library beyond supabase-py
- Do NOT modify subscribers table or insert_subscriber()
- Do NOT add password hashing -- Supabase Auth handles it server-side
- Keep each new route under 35 lines
- Do NOT redirect to external OAuth flows -- email+password only

## Acceptance criteria
1. python -c "from app.app import create_app; app = create_app(); print('OK')" passes
2. GET /register returns 200
3. POST /register with valid email+password creates Supabase auth user, sets session["user"]
4. GET /studio with no session redirects to /register
5. GET /studio with active session returns 200 and shows user.email
6. GET /logout clears session and redirects to /
7. Desktop navbar shows "Sign in" when logged out, "My Account" when logged in
```

---

## Pre-flight checklist (do BEFORE pasting into Cursor)

- [ ] Install dep: `pip install supabase==2.10.0`
- [ ] In Supabase Dashboard > Auth > Providers: confirm Email provider is enabled
- [ ] In Supabase Dashboard > Auth > URL Configuration: add `http://localhost:5000` to Site URL
- [ ] Add to `.env`:
      ```
      SUPABASE_PROJECT_URL=https://your-project-ref.supabase.co
      ```
      (Find the ref in Supabase Dashboard > Project Settings > General)
- [ ] Verify `SUPABASE_SECRET_KEY` in .env is the service_role key (NOT the anon key)

---

## Manual smoke test (after Cursor finishes)

```bash
pip install supabase==2.10.0
python run.py
# In browser:
# 1. http://localhost:5000/register  -> form appears
# 2. Sign up with test@example.com  -> redirects to /studio
# 3. Click Sign out                 -> redirects to /
# 4. http://localhost:5000/studio   -> redirects to /register
# 5. Sign in                        -> back at /studio
# 6. Navbar shows "My Account" when in, "Sign in" when out
```
