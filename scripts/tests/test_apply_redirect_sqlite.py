import os
import sys
from pathlib import Path
import uuid

# Ensure repository root on path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))



def setup_sqlite_app_with_job():
    tmp_db = Path(__file__).parent / "apply_redirect.db"
    os.environ["FORCE_SQLITE"] = "1"
    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_db).replace('\\','/')
    os.environ["ENV"] = "testing"
    os.environ["FLASK_ENV"] = "testing"
    os.environ.setdefault("SECRET_KEY", "test-secret")
    if tmp_db.exists():
        tmp_db.unlink()
    tmp_db.parent.mkdir(parents=True, exist_ok=True)
    # Import after env is set to ensure modules read FORCE_SQLITE correctly
    from app.app import create_app
    app = create_app()
    # seed one job
    # Import Job after env is set and app created so IS_SQLITE resolves correctly
    from app.models.db import Job
    with app.app_context():
        Job.insert_many([
            {
                "job_title": "AI Engineer",
                "job_description": "LLMs",
                "link": "https://example.com/job-123",
                "location": "Madrid, ES",
                "job_date": "2025.10.01",
                "date": "2025-10-01",
            }
        ])
    return app


def test_apply_redirect_via_job_id_sqlite():
    app = setup_sqlite_app_with_job()
    with app.test_client() as c:
        # Find the job via API to get its id
        r = c.get("/api/jobs?title=ai&country=madrid&per_page=5")
        assert r.status_code == 200
        items = (r.get_json() or {}).get("items") or []
        assert items, "Seeded job not returned by search"
        job = items[0]
        job_id = job.get("id")
        link = job.get("link")
        assert link

        # HTML flow resolves redirect by job_id
        resp = c.post("/subscribe", data={"email": f"ut-{uuid.uuid4().hex[:8]}@example.com", "job_id": str(job_id)}, follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert resp.headers.get("Location") == link

        # JSON flow returns redirect
        r2 = c.post("/subscribe.json", json={"email": f"ut-{uuid.uuid4().hex[:8]}@example.com", "job_id": str(job_id)})
        assert r2.status_code == 200
        data2 = r2.get_json() or {}
        assert (data2.get("status") == "ok") or (data2.get("error") == "duplicate")
        assert data2.get("redirect") == link
