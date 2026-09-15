"""Centralized configuration.

All paths/constants live here so they're set once and overridable via
environment variables — not scattered as string literals across modules.
"""
from __future__ import annotations

import os
from pathlib import Path

# Root for all generated/downloaded data. Override with JOBENGINE_HOME for
# multi-user or CI environments.
HOME = Path(os.environ.get("JOBENGINE_HOME", ".")).resolve()

DATA_DIR = HOME / "data"
DB_PATH = HOME / os.environ.get("JOBENGINE_DB", "jobengine.db")
OUT_DIR = HOME / "tailored"
RESUME_PATH = HOME / os.environ.get("JOBENGINE_RESUME", "resume.json")

INTERN_RAW = DATA_DIR / "intern_raw.json"
NEWGRAD_RAW = DATA_DIR / "newgrad_raw.json"

SOURCES = {
    INTERN_RAW:
        "https://raw.githubusercontent.com/SimplifyJobs/"
        "Summer2026-Internships/dev/.github/scripts/listings.json",
    NEWGRAD_RAW:
        "https://raw.githubusercontent.com/SimplifyJobs/"
        "New-Grad-Positions/dev/.github/scripts/listings.json",
}

LOG_LEVEL = os.environ.get("JOBENGINE_LOG_LEVEL", "INFO")
