from __future__ import annotations

# Sprint Planning Copilot API
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.presentation.http.ui_router import router as ui_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Scrum Co-Pilot — Extract API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "https://jira-frontend.gentleflower-2695c362.eastus.azurecontainerapps.io",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ui_router)
    return app


app = create_app()
