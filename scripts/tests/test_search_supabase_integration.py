import os
import sys
from pathlib import Path
import pytest

# Ensure repository root on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.app import create_app


@pytest.mark.integration
def test_api_jobs_with_supabase_if_configured():
    # Skip unless DATABASE_URL is provided (prod Supabase)
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        pytest.skip("DATABASE_URL not set; skipping Supabase integration test")

    # Configure app to prefer Postgres in production
    os.environ["ENV"] = "production"
    os.environ["FLASK_ENV"] = "production"
    os.environ["FORCE_SQLITE"] = "0"
    os.environ.setdefault("SECRET_KEY", "test-secret")

    app = create_app()
    with app.test_client() as c:
        resp = c.get("/api/jobs?per_page=5")
        assert resp.status_code == 200
        data = resp.get_json() or {}
        assert isinstance(data.get("items"), list)
        meta = data.get("meta") or {}
        assert "page" in meta and "per_page" in meta and "total" in meta

