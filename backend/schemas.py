from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field, conint, field_validator
from typing import List, Optional


class IssueType(str, Enum):
    STORY = "Story"
    TASK = "Task"
    BUG = "Bug"
    SPIKE = "Spike"


class Priority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class Task(BaseModel):
    summary: str = Field(..., min_length=3, max_length=300)
    description: str = Field(..., min_length=1)
    issue_type: IssueType
    assignee_name: Optional[str] = None
    priority: Priority = Priority.MEDIUM
    story_points: Optional[conint(ge=0, le=100)] = None
    labels: list[str] = Field(default_factory=list, max_length=20)
    links: list[str] = Field(default_factory=list, max_length=20)
    quotes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("summary", "description", "assignee_name", mode="before")
    @classmethod
    def _strip_and_validate(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must not be empty or whitespace")
        return trimmed

    @field_validator("labels", "links", "quotes", mode="before")
    @classmethod
    def _ensure_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return value
        raise TypeError("must be a list of strings")

    @field_validator("labels", "links", "quotes")
    @classmethod
    def _normalize_list_entries(cls, value: list[str]) -> list[str]:
        normalized = []
        for entry in value:
            if not isinstance(entry, str):
                raise TypeError("list entries must be strings")
            cleaned = entry.strip()
            if cleaned:
                normalized.append(cleaned)
        return normalized


class ExtractionResult(BaseModel):
    tasks: List[Task] = Field(..., min_length=1)
