from __future__ import annotations

import os

DEFAULT_DB_URL = os.getenv("DB_URL", "sqlite:///./app.db")

TASK_STATUSES = ("draft", "approved", "rejected")
ISSUE_TYPES = ("Story", "Task", "Bug", "Spike")
PRIORITIES = ("Low", "Medium", "High")
