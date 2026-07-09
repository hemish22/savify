"""
Pydantic models for Blog Summarizer.
"""

from pydantic import BaseModel
from typing import List, Optional


class SummarizeRequest(BaseModel):
    """Request body for the /summarize endpoint."""
    url: str


class SummaryData(BaseModel):
    """Structured summary returned by Gemini."""
    title: str
    summary: str
    key_points: List[str]
    difficulty: str  # Beginner / Intermediate / Advanced
    takeaway: str


class SummaryResponse(BaseModel):
    """Full summary response including metadata."""
    id: Optional[int] = None
    title: str
    domain: str
    difficulty: str
    summary: str
    key_points: List[str]
    takeaway: str
    original_url: str
    source_type: str = "blog"
    tools_mentioned: List[str] = []
    created_at: Optional[str] = None

