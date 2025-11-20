import os
import sys
from pathlib import Path

# Ensure repository root on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.app import create_app
from app.models.db import Job


def setup_app_with_seed(rows):
    tmp_db = Path(__file__).parent / "search_api.db"
    os.environ["FORCE_SQLITE"] = "1"
    os.environ["DB_PATH"] = str(tmp_db)
    os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "test-secret"
    os.environ["ENV"] = "testing"
    os.environ["FLASK_ENV"] = "testing"
    if tmp_db.exists():
        tmp_db.unlink()
    tmp_db.parent.mkdir(parents=True, exist_ok=True)

    app = create_app()
    # Seed sample jobs
    with app.app_context():
        inserted = Job.insert_many(rows)
        assert inserted == len(rows)
    return app


def test_search_title_filters_results():
    rows = [
        {"job_title": "Senior Data Engineer", "job_description": "Python, ETL", "link": "l1", "location": "Berlin, DE", "job_date": "2025.10.01", "date": "2025-10-01"},
        {"job_title": "Product Manager", "job_description": "Roadmaps", "link": "l2", "location": "Zurich, CH", "job_date": "2025.09.28", "date": "2025-09-28"},
        {"job_title": "Frontend Developer", "job_description": "React", "link": "l3", "location": "Remote", "job_date": "2025.09.26", "date": "2025-09-26"},
    ]
    app = setup_app_with_seed(rows)
    with app.test_client() as c:
        r = c.get("/api/jobs?title=engineer&per_page=10")
        assert r.status_code == 200
        data = r.get_json() or {}
        items = data.get("items") or []
        titles = {i.get("title", "").lower() for i in items}
        assert any("engineer" in t for t in titles)
        assert not any("product manager" == t for t in titles)


def test_search_country_filters_results():
    rows = [
        {"job_title": "Senior Data Engineer", "job_description": "Python, ETL", "link": "l1", "location": "Berlin, DE", "job_date": "2025.10.01", "date": "2025-10-01"},
        {"job_title": "Product Manager", "job_description": "Roadmaps", "link": "l2", "location": "Zurich, CH", "job_date": "2025.09.28", "date": "2025-09-28"},
    ]
    app = setup_app_with_seed(rows)
    with app.test_client() as c:
        r = c.get("/api/jobs?country=berlin&per_page=10")
        assert r.status_code == 200
        data = r.get_json() or {}
        items = data.get("items") or []
        assert len(items) == 1
        assert items[0].get("location","berlin").lower().find("berlin") != -1


def test_search_pagination_meta_present():
    rows = []
    for i in range(15):
        rows.append({
            "job_title": f"Role {i}", "job_description": "desc", "link": f"lnk{i}",
            "location": "Remote", "job_date": "2025.09.26", "date": "2025-09-26"
        })
    app = setup_app_with_seed(rows)
    with app.test_client() as c:
        r = c.get("/api/jobs?per_page=5&page=2")
        assert r.status_code == 200
        data = r.get_json() or {}
        meta = data.get("meta") or {}
        assert meta.get("page") == 2
        assert meta.get("per_page") == 10
        expected_pages = (len(rows) + meta.get("per_page") - 1) // meta.get("per_page")
        assert meta.get("pages") == expected_pages
        assert isinstance(data.get("items"), list) and len(data["items"]) == 5

