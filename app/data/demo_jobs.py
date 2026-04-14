"""Fallback demo job list shown when the DB returns no results."""

from __future__ import annotations

DEMO_JOBS: list[dict] = [
    {
        "id": "demo-1", "title": "Senior Software Engineer (AI)", "company": "Catalitium",
        "location": "Remote / EU",
        "description": "Own end-to-end features across ingestion and ranking and AI-assisted matching.",
        "date_posted": "2025.10.01", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-2", "title": "Data Engineer", "company": "Catalitium",
        "location": "London UK",
        "description": "Build reliable pipelines and optimize warehouse performance.",
        "date_posted": "2025.09.28", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-3", "title": "Product Manager", "company": "Stealth",
        "location": "Zurich CH",
        "description": "Partner with design and engineering to deliver user value quickly.",
        "date_posted": "2025.09.27", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-4", "title": "Frontend Developer", "company": "Acme Corp",
        "location": "Barcelona ES",
        "description": "Ship delightful UI with Tailwind and strong accessibility.",
        "date_posted": "2025.09.26", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-5", "title": "Cloud DevOps Engineer", "company": "Nimbus",
        "location": "Remote / Europe",
        "description": "Automate infrastructure and observability and release workflows.",
        "date_posted": "2025.09.25", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
    {
        "id": "demo-6", "title": "ML Engineer", "company": "Quantix",
        "location": "Remote",
        "description": "Deploy ranking and semantic matching at scale.",
        "date_posted": "2025.09.24", "date_raw": "", "link": "", "is_new": False, "is_ghost": False,
        "match_score": None, "match_reasons": [], "median_salary": None, "median_salary_currency": None,
        "median_salary_compact": None, "estimated_salary_range_compact": None,
        "estimated_salary_range_numeric": None, "salary_delta_pct": None, "salary_uplift_factor": None,
    },
]

__all__ = ["DEMO_JOBS"]
