"""
StayWise — Allocation Scheduler & Deadline Processor

Provides automatic post-deadline allocation execution and idempotent run management.
"""

from datetime import datetime, timezone
from models import db, ApplicationSettings, AllocationRun
from allocation_engine import run_allocation

def get_or_create_settings(cycle_year=2026):
    """Fetches or initializes the application cycle window settings."""
    settings = ApplicationSettings.query.filter_by(cycle_year=cycle_year).first()
    if not settings:
        settings = ApplicationSettings(
            cycle_year=cycle_year,
            is_open=True,
            opening_time=datetime.now(timezone.utc),
            closing_time=datetime(cycle_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.session.add(settings)
        db.session.commit()
    return settings

def is_application_period_open(cycle_year=2026):
    """Returns True if current time is within the active application period."""
    settings = get_or_create_settings(cycle_year)
    now = datetime.now(timezone.utc)
    if not settings.is_open:
        return False
    if settings.opening_time and now < settings.opening_time.replace(tzinfo=timezone.utc):
        return False
    if settings.closing_time and now > settings.closing_time.replace(tzinfo=timezone.utc):
        return False
    return True

def trigger_deadline_allocation(cycle_year=2026, admin_id=None, force=False):
    """
    Checks if application deadline has passed, and executes final allocation idempotently.
    If force=True, allows authorized admin manual test execution.
    """
    settings = get_or_create_settings(cycle_year)
    now = datetime.now(timezone.utc)

    if not force:
        if settings.closing_time and now < settings.closing_time.replace(tzinfo=timezone.utc):
            return {
                'executed': False,
                'message': f"Application deadline has not passed yet. Deadline: {settings.closing_time.isoformat()}."
            }

    # Execute allocation
    result = run_allocation(admin_id=admin_id, cycle_year=cycle_year, commit=True)
    return {
        'executed': True,
        'message': f"Allocation successfully executed for cycle {cycle_year}.",
        'result': result
    }
