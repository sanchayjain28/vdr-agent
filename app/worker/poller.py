from __future__ import annotations

import asyncio
import logging
from typing import Set

from app.config import get_settings
from app.db.dao.processing_state_dao import ProcessingStateDAO

LOGGER = logging.getLogger(__name__)


async def run_poller() -> None:
    """Autonomous poll loop — runs for the application's lifetime.

    Each cycle (in order):
      1. Reset stale processing rows (crashed workers)
      2. Detect + register new documents from ai_rag.documents
      3. Claim pending/failed rows atomically (FOR UPDATE SKIP LOCKED)
      4. Fire asyncio.create_task per claimed document
      5. Sleep poll_interval_seconds
    """
    settings = get_settings()
    LOGGER.info(
        "Poller started: interval=%ds batch=%d stale_threshold=%dmin",
        settings.poll_interval_seconds,
        settings.poll_batch_size,
        settings.stale_lock_threshold_minutes,
    )

    # Set lives in run_poller() scope — accumulates tasks across cycles; never resets.
    # Task references prevent GC of in-flight tasks. done callback removes on completion.
    active_tasks: Set[asyncio.Task] = set()

    while True:
        try:
            await _poll_cycle(settings, active_tasks)
        except asyncio.CancelledError:
            LOGGER.info("Poller received cancellation — exiting")
            raise  # Must re-raise: CancelledError is BaseException; swallowing causes shutdown hang
        except Exception:
            LOGGER.exception("Uncaught error in poll cycle — continuing after sleep")

        try:
            await asyncio.sleep(settings.poll_interval_seconds)
        except asyncio.CancelledError:
            LOGGER.info("Poller sleep cancelled — exiting")
            raise


async def _poll_cycle(settings, active_tasks: Set[asyncio.Task]) -> None:
    """Execute one poll cycle."""
    from app.worker.processor import process_document  # local import avoids circular at module level

    # Step 1: Reset stale claims from crashed workers
    reset_count = await ProcessingStateDAO.reset_stale_claims(
        settings.stale_lock_threshold_minutes
    )
    if reset_count:
        LOGGER.warning("Reset %d stale processing row(s)", reset_count)

    # Step 2+3: Detect new documents and register them
    new_doc_ids = await ProcessingStateDAO.find_unregistered_documents(
        settings.poll_batch_size
    )
    for doc_id in new_doc_ids:
        await ProcessingStateDAO.insert(doc_id)
    if new_doc_ids:
        LOGGER.info("Registered %d new document(s)", len(new_doc_ids))

    # Step 4: Atomically claim pending/failed rows (FOR UPDATE SKIP LOCKED)
    claimed = await ProcessingStateDAO.claim_documents(settings.poll_batch_size)
    if not claimed:
        LOGGER.debug("No documents to process this cycle")
        return

    LOGGER.info("Claimed %d document(s) for processing", len(claimed))

    # Step 5: Fire-and-forget per document; store task reference to prevent GC
    for ps_id, doc_id in claimed:
        task = asyncio.create_task(process_document(ps_id, doc_id))
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)
        task.add_done_callback(
            lambda t, pid=ps_id: LOGGER.debug(
                "process_document task done ps_id=%s err=%s",
                pid,
                t.exception() if not t.cancelled() and t.exception() is not None else None,
            )
        )
