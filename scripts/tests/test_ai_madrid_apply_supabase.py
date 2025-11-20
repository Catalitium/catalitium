import os
import sys
import uuid
from pathlib import Path
import pytest

# Ensure repository root on path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))



def _prod_env():
    os.environ["ENV"] = "production"
    os.environ["FLASK_ENV"] = "production"
    os.environ["FORCE_SQLITE"] = "0"
    os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.mark.integration
def test_search_ai_madrid_supabase_if_configured():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; skipping Supabase search test")
    _prod_env()
    from app.app import create_app
    app = create_app()
    with app.test_client() as c:
        r = c.get("/api/jobs?title=ai&country=madrid&per_page=10")
        assert r.status_code == 200
        data = r.get_json() or {}
        items = data.get("items") or []
        assert isinstance(items, list)
        # Allow zero if dataset doesn’t contain Madrid AI jobs; test just validates path


@pytest.mark.integration
def test_apply_redirect_by_job_id_supabase_if_configured():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; skipping Supabase apply redirect test")
    _prod_env()
    from app.app import create_app
    app = create_app()
    with app.test_client() as c:
        # Find a job with a non-empty link
        r = c.get("/api/jobs?title=ai&country=madrid&per_page=10")
        assert r.status_code == 200
        items = (r.get_json() or {}).get("items") or []
        target = next((i for i in items if (i.get("link") or "").strip()), None)
        if not target:
            pytest.skip("No AI jobs with links found for Madrid in current dataset")

        job_id = target.get("id")
        link = target.get("link")
        assert job_id is not None and link

        # HTML form: rely on server job_id resolution
        resp = c.post("/subscribe", data={"email": f"it-{uuid.uuid4().hex[:8]}@example.com", "job_id": str(job_id)}, follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert resp.headers.get("Location") == link

        # JSON: server returns redirect
        r2 = c.post("/subscribe.json", json={"email": f"it-{uuid.uuid4().hex[:8]}@example.com", "job_id": str(job_id)})
        assert r2.status_code == 200
        data2 = r2.get_json() or {}
        assert (data2.get("status") == "ok") or (data2.get("error") == "duplicate")
        assert data2.get("redirect") == link
