from __future__ import annotations

from fastapi import FastAPI

from backend.api.router import router as extraction_router

app = FastAPI(title="AI Scrum Co-Pilot — MVP Extract API")
app.include_router(extraction_router)
