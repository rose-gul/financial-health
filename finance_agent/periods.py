"""Calendar periods shared by ingestion and forecasting."""

import calendar
from datetime import date


def period_bounds(as_of: date, period: str) -> tuple[date, date]:
    if period == "yearly":
        return date(as_of.year, 1, 1), date(as_of.year, 12, 31)
    return as_of.replace(day=1), as_of.replace(
        day=calendar.monthrange(as_of.year, as_of.month)[1]
    )
