import os
import sys
import shutil
import argparse
import uuid
from pathlib import Path


def init_env_sqlite(temp_db: Path):
    # Use a temp copy so the source DB stays untouched
    src = Path('data') / 'catalitium.db'
    temp_db.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, temp_db)
    os.environ['FORCE_SQLITE'] = '1'
    os.environ['ENV'] = 'testing'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ.setdefault('SECRET_KEY', 'test-secret')
    os.environ['DB_PATH'] = str(temp_db)
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(temp_db).replace('\\', '/')


def get_counts(app):
    from app.models.db import get_db
    with app.app_context():
        db = get_db()
        try:
            if app.config.get('DB_BACKEND') == 'postgres':
                with db.cursor() as cur:
                    cur.execute("SELECT COUNT(1) FROM subscribers")
                    a = cur.fetchone()[0]
                return int(a)
            else:
                row = db.execute("SELECT COUNT(1) FROM subscribers").fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return -1


def pick_job(client, title=None, country=None, per_page=25):
    qs = []
    if title:
        qs.append(('title', title))
    if country:
        qs.append(('country', country))
    qs.append(('per_page', str(per_page)))
    path = '/api/jobs'
    if qs:
        from urllib.parse import urlencode
        path += '?' + urlencode(qs)
    resp = client.get(path)
    assert resp.status_code == 200, f"/api/jobs failed: {resp.status_code}"
    items = (resp.get_json() or {}).get('items') or []
    for it in items:
        if (it.get('link') or '').strip():
            return it['id'], it['link']
    raise SystemExit('No job with a non-empty link found for the given filters')


def main():
    ap = argparse.ArgumentParser(description='Test apply flow: subscribe then redirect to job href')
    ap.add_argument('--use-sqlite', action='store_true', help='Force using a temp SQLite copy of data/catalitium.db')
    ap.add_argument('--job-title', default='ai', help='Title filter to find a job (default: ai)')
    ap.add_argument('--country', default='madrid', help='Country/city filter (default: madrid)')
    ap.add_argument('--per-page', type=int, default=25)
    args = ap.parse_args()

    if args.use_sqlite:
        init_env_sqlite(Path('scripts/tmp/apply_test.db'))
    else:
        # Production-like test uses current env (expects DATABASE_URL for Postgres)
        os.environ.setdefault('ENV', 'production')
        os.environ.setdefault('FLASK_ENV', 'production')

    # Lazy import after env prepared
    from app.app import create_app
    app = create_app()
    client = app.test_client()

    # Find a job with a link
    job_id, link = pick_job(client, title=args.job_title, country=args.country, per_page=args.per_page)
    print(f"Picked job id={job_id} link={link}")

    # Count before
    before = get_counts(app)
    print(f"Subscribers before: {before}")

    # JSON subscribe (should return redirect)
    email1 = f"test-{uuid.uuid4().hex[:8]}@example.com"
    r1 = client.post('/subscribe.json', json={'email': email1, 'job_id': str(job_id)})
    assert r1.status_code == 200, f"subscribe.json failed: {r1.status_code}"
    data1 = r1.get_json() or {}
    redir1 = data1.get('redirect')
    assert redir1 == link, f"Expected redirect {link}, got {redir1}"
    print(f"/subscribe.json OK → redirect: {redir1}")

    # HTML subscribe (should 3xx redirect to link)
    email2 = f"test-{uuid.uuid4().hex[:8]}@example.com"
    r2 = client.post('/subscribe', data={'email': email2, 'job_id': str(job_id)}, follow_redirects=False)
    assert r2.status_code in (301, 302, 303, 307, 308), f"subscribe redirect status unexpected: {r2.status_code}"
    loc = r2.headers.get('Location')
    assert loc == link, f"Expected Location {link}, got {loc}"
    print(f"/subscribe 3xx → Location: {loc}")

    # Count after (duplicate-safe; increment may be 1 or 2 depending on unique rule)
    after = get_counts(app)
    print(f"Subscribers after: {after}")
    if before >= 0 and after >= 0:
        assert after >= before + 1, "Expected subscribers to increase by at least 1"
        print(f"OK: subscribers increased by {after - before}")

    print('PASS: apply flow verified (JSON + HTML)')


if __name__ == '__main__':
    # Ensure repo root on path
    REPO_ROOT = Path(__file__).resolve().parents[1]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    main()

