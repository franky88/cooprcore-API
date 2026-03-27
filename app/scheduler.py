# backend/app/scheduler.py
"""
APScheduler setup for CoopCore.

Jobs run inside the Flask app context so they have full access to
mongo, config, and all services.

Schedule:
  - past_due_check   : daily at 01:00 AM server time
  - dormancy_check   : 1st of every month at 02:00 AM

To disable the scheduler in testing, set SCHEDULER_ENABLED=false in .env.
"""
import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Module-level scheduler instance — created once, shared across the app
_scheduler: BackgroundScheduler | None = None


def init_scheduler(app) -> None:
    """
    Initialise and start the background scheduler.
    Call this once from create_app() after all extensions are ready.
    """
    global _scheduler

    # Allow disabling the scheduler in test/CI environments
    if os.getenv("SCHEDULER_ENABLED", "true").lower() == "false":
        app.logger.info("Scheduler is disabled (SCHEDULER_ENABLED=false)")
        return

    # Prevent double-initialisation (e.g. Flask debug reloader spawns 2 processes)
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(
        timezone="Asia/Manila",   # Philippine Standard Time
        job_defaults={
            "coalesce": True,      # merge missed runs into one
            "max_instances": 1,    # never run the same job twice concurrently
            "misfire_grace_time": 3600,  # allow up to 1 hour late start
        },
    )

    # ------------------------------------------------------------------ #
    # Job 1 — Past-due check (daily at 01:00 AM PST)
    # ------------------------------------------------------------------ #
    _scheduler.add_job(
        func=_run_past_due_check,
        args=[app],
        trigger=CronTrigger(hour=1, minute=0),
        id="past_due_check",
        name="Auto mark overdue loans as Past Due",
        replace_existing=True,
    )

    # ------------------------------------------------------------------ #
    # Job 2 — Dormancy check (1st of every month at 02:00 AM PST)
    # ------------------------------------------------------------------ #
    _scheduler.add_job(
        func=_run_dormancy_check,
        args=[app],
        trigger=CronTrigger(day=1, hour=2, minute=0),
        id="dormancy_check",
        name="Auto mark inactive savings accounts as Dormant",
        replace_existing=True,
    )

    _scheduler.start()
    app.logger.info("Scheduler started. Jobs: past_due_check (daily 01:00), "
                    "dormancy_check (monthly 1st 02:00)")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ------------------------------------------------------------------ #
# Job functions — each runs inside the Flask app context
# ------------------------------------------------------------------ #

def _run_past_due_check(app) -> None:
    with app.app_context():
        try:
            from .services.loan_service import LoanService
            result = LoanService().mark_past_due()
            logger.info(
                "past_due_check completed: %d loan(s) marked Past Due",
                result["marked_past_due"],
            )
        except Exception as exc:
            logger.exception("past_due_check failed: %s", exc)


def _run_dormancy_check(app) -> None:
    with app.app_context():
        try:
            from .services.savings_service import SavingsService
            result = SavingsService().mark_dormant_accounts()
            logger.info(
                "dormancy_check completed: %d account(s) marked Dormant",
                result["accounts_marked_dormant"],
            )
        except Exception as exc:
            logger.exception("dormancy_check failed: %s", exc)