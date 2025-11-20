import os
import sys
from pathlib import Path
import uuid
import pytest

# Ensure repository root on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.app import create_app


@pytest.mark.integration
def test_subscribe_json_prod_supabase_if_configured():
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        pytest.skip("DATABASE_URL not set; skipping Supabase subscribe integration test")

    # Production-like env
    os.environ["ENV"] = "production"
    os.environ["FLASK_ENV"] = "production"
    os.environ["FORCE_SQLITE"] = "0"
    os.environ.setdefault("SECRET_KEY", "test-secret")

    app = create_app()
    with app.test_client() as c:
        unique_email = f"it-{uuid.uuid4().hex[:10]}@example.com"
        resp = c.post("/subscribe.json", json={"email": unique_email})
        assert resp.status_code == 200
        data = resp.get_json() or {}
        assert (data.get("status") == "ok") or (data.get("error") == "duplicate")

