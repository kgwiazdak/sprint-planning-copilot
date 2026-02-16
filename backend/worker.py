from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv

# Load environment before importing container to avoid caching empty settings.
load_dotenv(dotenv_path=".env")

from backend.container import get_meeting_queue_worker
from backend.infrastructure.telemetry.langsmith_setup import configure_langsmith

logger = logging.getLogger(__name__)

configure_langsmith()


async def main() -> None:
    try:
        worker = get_meeting_queue_worker()
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "Failed to initialize queue worker (likely missing/invalid Azure Storage queue config). "
            "Worker will stay idle instead of exiting."
        )
        worker = None

    if worker is None:
        logger.warning(
            "Azure queue worker is not configured. "
            "Set AZURE_STORAGE_QUEUE_NAME and the matching connection string to enable the worker. "
            "Worker will stay idle instead of exiting."
        )
        # Keep the container alive to avoid crash-loop when queue is intentionally absent.
        while True:
            await asyncio.sleep(60)
    logger.info("Starting Azure queue worker")
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
