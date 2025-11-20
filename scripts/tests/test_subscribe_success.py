import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path so `import app` works
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.app import create_app
import uuid


def setup_test_app(tmp_db: Path):
    # Force SQLite for tests and point to temp DB path
    os.environ["FORCE_SQLITE"] = "1"
    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "test-secret"
    os.environ["ENV"] = "testing"
    os.environ["FLASK_ENV"] = "testing"
    # Ensure clean DB file
    if tmp_db.exists():
        tmp_db.unlink()
    tmp_db.parent.mkdir(parents=True, exist_ok=True)
    return create_app()


def test_subscribe_form_success():
    tmp_db = Path(__file__).parent / "test_subscribe.db"
    app = setup_test_app(tmp_db)
    with app.test_client() as c:
        resp = c.post("/subscribe", data={"email": "user@example.com", "next": "https://example.com/job"}, follow_redirects=False)
        # Expects redirect to provided next URL
        assert resp.status_code in (301, 302, 303, 307, 308)
        loc = resp.headers.get("Location", "")
        assert loc == "https://example.com/job"


def test_subscribe_json_success():
    tmp_db = Path(__file__).parent / "test_subscribe_json.db"
    app = setup_test_app(tmp_db)
    with app.test_client() as c:
        unique_email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        resp = c.post("/subscribe.json", json={"email": unique_email, "next": "https://example.com/job2"})
        assert resp.status_code == 200
        data = resp.get_json() or {}
        assert (data.get("status") == "ok") or (data.get("error") == "duplicate")
        # Should include redirect echo
        assert data.get("redirect") == "https://example.com/job2"
