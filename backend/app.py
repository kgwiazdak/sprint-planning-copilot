from __future__ import annotations

# Sprint Planning Copilot API
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure .env is loaded before any container/settings singletons are constructed.
load_dotenv(dotenv_path=".env")

from backend.presentation.http.ui_router import public_router, router as ui_router


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
            "https://jiracopilot.com"
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(public_router)
    app.include_router(ui_router)
    return app


app = create_app()
