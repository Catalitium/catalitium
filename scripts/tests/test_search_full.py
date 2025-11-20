import os
import sys
from pathlib import Path
import uuid

# Ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _setup_sqlite_app(tmpname: str):
    from app.app import create_app  # import after path injected
    tmp_db = Path(__file__).parent / tmpname
    os.environ["FORCE_SQLITE"] = "1"
    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_db).replace('\\','/')
    os.environ["ENV"] = "testing"
    os.environ["FLASK_ENV"] = "testing"
    os.environ.setdefault("SECRET_KEY", "test-secret")
    if tmp_db.exists():
        tmp_db.unlink()
    tmp_db.parent.mkdir(parents=True, exist_ok=True)
    app = create_app()
    # Seed jobs
    from app.models.db import Job  # import after env set/app created
    Job.insert_many([
        {"job_title": "AI Engineer", "job_description": "LLMs, Python", "link": "https://example.com/ai-1", "location": "Madrid, ES", "job_date": "2025.10.01", "date": "2025-10-01"},
        {"job_title": "Senior Data Engineer", "job_description": "ETL", "link": "https://example.com/de-1", "location": "Berlin, DE", "job_date": "2025.10.02", "date": "2025-10-02"},
        {"job_title": "Frontend Developer", "job_description": "React", "link": "https://example.com/fe-1", "location": "Madrid, ES", "job_date": "2025.09.26", "date": "2025-09-26"},
        {"job_title": "Product Manager", "job_description": "Roadmaps", "link": "https://example.com/pm-1", "location": "Zurich, CH", "job_date": "2025.09.28", "date": "2025-09-28"},
        {"job_title": "ML Engineer", "job_description": "Models", "link": "https://example.com/ml-1", "location": "Remote", "job_date": "2025.09.24", "date": "2025-09-24"},
        {"job_title": "Backend Developer", "job_description": "APIs", "link": "https://example.com/be-1", "location": "Madrid, ES", "job_date": "2025.09.20", "date": "2025-09-20"},
    ])
    return app


def test_title_filter_sqlite():
    app = _setup_sqlite_app("search_full_1.db")
    with app.test_client() as c:
        r = c.get("/api/jobs?title=engineer&per_page=50")
        assert r.status_code == 200
        items = (r.get_json() or {}).get("items") or []
        assert any("engineer" in (i.get("title") or "").lower() for i in items)


def test_country_filter_sqlite():
    app = _setup_sqlite_app("search_full_2.db")
    with app.test_client() as c:
        r = c.get("/api/jobs?country=madrid&per_page=50")
        assert r.status_code == 200
        items = (r.get_json() or {}).get("items") or []
        assert items and all("madrid" in (i.get("location") or "").lower() for i in items)


def test_pagination_sqlite():
    app = _setup_sqlite_app("search_full_3.db")
    with app.test_client() as c:
        r1 = c.get("/api/jobs?per_page=2&page=1")
        r2 = c.get("/api/jobs?per_page=2&page=2")
        d1, d2 = r1.get_json(), r2.get_json()
        assert r1.status_code == 200 and r2.status_code == 200
        assert len(d1.get("items") or []) == 2
        assert len(d2.get("items") or []) == 2
        assert (d1.get("meta") or {}).get("pages") >= 3


def test_index_renders_anchor_hrefs_for_top_cards_sqlite():
    app = _setup_sqlite_app("search_full_4.db")
    with app.test_client() as c:
        r = c.get("/")
        html = r.get_data(as_text=True)
        # First two cards should include anchors to their links
        assert "href=\"https://example.com/ai-1\"" in html or "href=\"https://example.com/de-1\"" in html


def test_subscribe_json_redirect_by_job_id_sqlite():
    app = _setup_sqlite_app("search_full_5.db")
    with app.test_client() as c:
        # Find a job id and link
        jr = c.get("/api/jobs?title=ai&country=madrid&per_page=5")
        items = (jr.get_json() or {}).get("items") or []
        target = next((i for i in items if (i.get("link") or "").strip()), None)
        assert target, "Expected at least one job with link"
        job_id, link = target["id"], target["link"]
        r = c.post("/subscribe.json", json={"email": f"ut-{uuid.uuid4().hex[:8]}@example.com", "job_id": str(job_id)})
        assert r.status_code == 200
        data = r.get_json() or {}
        assert (data.get("status") == "ok") or (data.get("error") == "duplicate")
        assert data.get("redirect") == link

