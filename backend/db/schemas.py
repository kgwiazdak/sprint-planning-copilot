from typing import List, Optional

from pydantic import BaseModel, Field, conint


class Task(BaseModel):
    summary: str = Field(..., min_length=3, max_length=300)
    description: str = Field(..., min_length=1)
    issue_type: str = Field(..., pattern=r"^(Story|Task|Bug|Spike)$")
    assignee_name: Optional[str] = None
    priority: str = Field(..., pattern=r"^(Low|Medium|High)$")
    story_points: Optional[conint(ge=0, le=100)] = None
    labels: Optional[list[str]] = Field(default_factory=list)
    links: Optional[list[str]] = Field(default_factory=list)
    quotes: Optional[list[str]] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    tasks: List[Task]
