"""Market research report catalog.

Each entry maps to a route under /market-research/<slug> and is
rendered by app/controllers/carl.py using the template key.
"""

from __future__ import annotations

REPORTS: list[dict] = [
    {
        "slug": "global-tech-ai-careers-report-2026",
        "title": "Catalitium Global Tech & AI Careers Report - 2026 Edition",
        "short_title": "Global Tech & AI Careers Report 2026",
        "description": (
            "Data-driven analysis of AI's impact on tech jobs, skills in demand, "
            "salaries by region (US, Europe, India), and the fastest growing roles for 2025-2026."
        ),
        "published": "2025-11-01",
        "updated": "2025-11-01",
        "published_display": "November 2025",
        "pdf_path": "reports/R01- Catalitium Global Tech & AI Careers Report  November 2025 Edition.pdf",
        "read_time": "12 min read",
        "keywords": [
            "global tech and AI jobs report 2026",
            "AI careers report 2026",
            "tech skills in demand 2025",
            "AI job market trends",
            "2025 tech salaries US Europe India",
            "remote and hybrid work trends in tech",
            "fastest growing AI jobs 2025 2026",
        ],
    },
    {
        "slug": "aaas-tipping-point-saas-economics-2026",
        "title": "The AaaS Tipping Point: Why AI Agents Are Killing SaaS Economics in 2026",
        "short_title": "The AaaS Tipping Point Report 2026",
        "description": (
            "Whether Agents as a Service can capture 30%+ of enterprise software spend by 2028: "
            "Gartner, IDC, McKinsey, and workflow-level TCO evidence on agentic AI vs. seat-based SaaS. "
            "37 sources, April 2026."
        ),
        "published": "2026-03-01",
        "updated": "2026-03-01",
        "published_display": "March 2026",
        "pdf_path": "",
        "read_time": "22 min read",
        "gated": True,
        "template": "reports/aaas_tipping_point.html",
        "keywords": [
            "AaaS agents as a service 2026",
            "AI agents vs SaaS economics",
            "enterprise software spend agentic AI",
            "Gartner agentic AI enterprise applications",
            "SaaS TCO vs AI agents",
            "Automation Anywhere AI service agents",
            "LangGraph pricing per action",
            "Fortune 500 AI agents production 2026",
        ],
    },
    {
        "slug": "ai-skill-premium-index-2026",
        "title": "The AI Skill Premium Index 2026: Which AI Skills Command the Highest Salary Premiums",
        "short_title": "AI Skill Premium Index 2026",
        "description": (
            "Lightcast, Levels.fyi, Pave, and SignalFire data on AI vs SWE pay: ~28% posting premium, "
            "43% with 2+ AI skills, LLM and safety specializations, myths vs reality. February 2026."
        ),
        "published": "2026-02-15",
        "updated": "2026-02-15",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/ai_skill_premium_index_2026.html",
        "keywords": [
            "AI skill salary premium 2026",
            "LLM engineer compensation vs ML engineer",
            "Lightcast AI job postings premium",
            "Levels.fyi AI engineer salary 2025",
            "MLOps salary premium",
            "AI safety alignment salary growth",
            "tech compensation Big Tech AI vs SWE",
        ],
    },
    {
        "slug": "european-llm-build-vs-buy-2026",
        "title": "From Build to Buy: How the LLM Platform Era Is Rewriting Software Economics (Europe)",
        "short_title": "European LLM Build vs Buy Report 2026",
        "description": (
            "Europe enterprise LLM market ~$1.09B, 76% of AI now purchased vs built, EU AI Act compliance costs, "
            "API pricing tiers, and talent benchmarks. 20+ sources, February 2026."
        ),
        "published": "2026-02-01",
        "updated": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "24 min read",
        "gated": True,
        "template": "reports/european_llm_build_buy_2026.html",
        "keywords": [
            "Europe LLM market 2026",
            "build vs buy enterprise AI Europe",
            "EU AI Act compliance cost SME",
            "Menlo Ventures AI purchased vs built",
            "European SaaS LLM API economics",
            "AI engineer salary Europe Switzerland Spain",
            "LLM API pricing comparison 2025",
        ],
    },
    {
        "slug": "200k-engineer-ai-reshaping-software-salaries-2026",
        "title": "The $200K Engineer: How AI Productivity Is Reshaping Software Salaries",
        "short_title": "The $200K Engineer Report 2026",
        "description": (
            "Staff engineers saw 7.52% comp growth while junior hiring collapsed 73%. "
            "A data-driven investigation into who wins, who loses, and what drives the split "
            "in software engineering compensation in 2025\u20132026. 69 sources."
        ),
        "published": "2026-02-01",
        "updated": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/200k_engineer.html",
        "keywords": [
            "software engineer salary 2026",
            "AI skills salary premium",
            "staff engineer compensation growth",
            "junior developer hiring collapse 2025",
            "AI productivity compensation bifurcation",
            "Anthropic OpenAI engineer salary",
            "revenue per employee software companies",
            "software engineering salary trends 2026",
        ],
    },
    {
        "slug": "from-saas-to-agents-ai-native-workforce-2026",
        "title": "From SaaS to Agents: How AI Native Software Is Reshaping the Tech Workforce",
        "short_title": "From SaaS to Agents Report 2026",
        "description": (
            "A data-driven investigation into team economics, revenue per employee, AI-agent adoption, "
            "and the structural transformation of software work. 74 sources, February 2026."
        ),
        "published": "2026-02-01",
        "updated": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "",
        "read_time": "20 min read",
        "gated": True,
        "template": "reports/saas_to_agents.html",
        "keywords": [
            "AI native software workforce 2026",
            "revenue per employee AI companies",
            "SaaS to agents transition",
            "AI engineer hiring demand 2026",
            "software developer job market decline",
            "GitHub Copilot productivity study",
            "enterprise AI adoption transformation gap",
            "Klarna AI workforce case study",
        ],
    },
    {
        "slug": "ai-productivity-paradox-junior-roles-2026",
        "title": "AI Didn\u2019t Kill Jobs \u2014 It Killed Junior Roles",
        "short_title": "AI Productivity Paradox Report 2026",
        "description": (
            "Entry-level tech job postings dropped 35% since 2023 while AI engineers earn $206K on average. "
            "Data-driven analysis of how AI productivity tools are reshaping the tech labor market, "
            "collapsing junior demand, and creating an unprecedented senior skill premium."
        ),
        "published": "2025-12-01",
        "updated": "2025-12-01",
        "published_display": "December 2025",
        "pdf_path": "reports/R02- AI Didn\u2019t Kill Jobs \u2014 It Killed Junior Roles.pdf",
        "read_time": "15 min read",
        "gated": True,
        "template": "reports/junior_roles.html",
        "keywords": [
            "entry level tech jobs 2026",
            "AI productivity paradox",
            "junior developer jobs decline",
            "AI skill salary premium 2025",
            "tech hiring trends 2026",
            "github copilot adoption stats",
            "series A team size decline",
            "CS degree unemployment 2025",
        ],
    },
    {
        "slug": "death-of-saas-vibecoding-2026",
        "title": "The Death of SaaS: How Vibecoding Is Killing a $315 Billion Industry",
        "short_title": "The Death of SaaS Report 2026",
        "description": (
            "A data-driven market report analyzing how AI-assisted development is structurally "
            "disrupting the $315 billion SaaS industry, with sourced data from a16z, Gartner, "
            "YC, Retool, Deloitte, and Emergence Capital."
        ),
        "published": "2026-02-01",
        "updated": "2026-02-01",
        "published_display": "February 2026",
        "pdf_path": "reports/R03- The Death of SaaS How Vibecoding Is Killing a 315 Billion Industry.pdf",
        "read_time": "18 min read",
        "gated": True,
        "template": "reports/saas_vibecoding.html",
        "keywords": [
            "death of saas 2026",
            "vibecoding saas disruption",
            "ai coding tools market report",
            "build vs buy saas 2026",
            "saas market size 2026",
            "cursor ai growth",
            "ai native saas vs traditional saas",
            "software as labor business model",
        ],
    },
]

__all__ = ["REPORTS"]
