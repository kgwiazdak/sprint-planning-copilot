from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv

from backend.container import get_meeting_queue_worker

load_dotenv()

logger = logging.getLogger(__name__)


async def main() -> None:
    worker = get_meeting_queue_worker()
    if worker is None:
        raise RuntimeError(
            "Azure queue worker is not configured. "
            "Set AZURE_STORAGE_QUEUE_NAME and the matching connection string before starting the worker."
        )
    logger.info("Starting Azure queue worker")
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
