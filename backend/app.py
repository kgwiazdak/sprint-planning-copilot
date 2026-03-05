from __future__ import annotations

import asyncio
import contextlib
import logging

# Sprint Planning Copilot API
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure .env is loaded before any container/settings singletons are constructed.
load_dotenv(dotenv_path=".env")

from backend.container import get_meeting_queue_worker
from backend.infrastructure.telemetry.langsmith_setup import configure_langsmith
from backend.presentation.http.ui_router import public_router, router as ui_router
from backend.settings import get_settings

logger = logging.getLogger(__name__)

configure_langsmith()


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


@app.on_event("startup")
async def _start_queue_worker() -> None:
    settings = get_settings()
    ingest_backend = (settings.ingest.backend or "azure").strip().lower()
    ingest_backend = "local" if ingest_backend == "local" else "azure"
    logger.info(
        "Ingest runtime configured: backend=%s, local_storage_root=%s, azure_blob_configured=%s, azure_queue_configured=%s",
        ingest_backend,
        settings.ingest.local_storage_root,
        bool(settings.blob_storage.connection_string and settings.blob_storage.container_name),
        bool(settings.queue.connection_string and settings.queue.queue_name),
    )
    try:
        worker = get_meeting_queue_worker()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to initialize the Azure queue worker.")
        return

    if worker is None:
        logger.info("Azure queue worker is not configured; skipping start.")
        return

    task = asyncio.create_task(worker.run_forever(), name="azure-queue-worker")
    app.state.queue_worker = worker
    app.state.queue_worker_task = task
    logger.info("Azure queue worker background task started.")


@app.on_event("shutdown")
async def _shutdown_queue_worker() -> None:
    worker = getattr(app.state, "queue_worker", None)
    task: asyncio.Task[None] | None = getattr(app.state, "queue_worker_task", None)
    if worker:
        worker.stop()
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
