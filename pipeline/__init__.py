"""Self-hosted automation pipeline: watchlist intake, commentary, review,
paced YouTube publishing and analytics. See docs/PIPELINE.md."""
from .router import callback_router, router
from .service import on_job_finished, start

__all__ = ["router", "callback_router", "start", "on_job_finished"]
