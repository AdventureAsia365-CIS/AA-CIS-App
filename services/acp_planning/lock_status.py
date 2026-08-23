"""
services.acp_planning.lock_status — AA-448 round 6: week/month lock check for T7.

Pure READ against data that already exists — no new schema (this is the answer round 5's own
open question 1 asked for: extend `acp_v2_runs` or a new table? Neither — lock status is
computed at read time, not stored). Two lock conditions, per Nghiep's round 6 decision, applied
per (year, month, week):

  (a) "produced"  — a row already exists in `acp_shared.acp_v2_runs` for that
                     (tenant_id, year, month, week) — i.e. N7's own trigger
                     (`allocate_and_persist_week()`/`admin_produce.py`'s `/run`, both UNTOUCHED
                     by this task) already ran for it. `acp_v2_runs` already carries real
                     `tenant_id, year, month, week` columns (migration 096/103) — reused as-is.
  (b) "past"       — the real calendar has moved past that MONTH. Deliberately MONTH-grain, not
                     week-grain: there is no existing mapping anywhere in this codebase from a
                     `week` value (1-4, `compute_slot_grid()`'s own round-robin numbering, NOT
                     tied to real calendar days — confirmed by reading that function) to an
                     actual date range. Inventing one would be exactly the "phát minh cách tính
                     tuần mới" this task was told not to do; the "produced" check above already
                     gives week-level precision for whichever weeks genuinely had N7 run against
                     them, which is the more meaningful signal anyway.

Scope boundary (see docs/implementation-notes/AA-448-t7-content-planning.md round 6 for the
full reasoning): this module only ever READS `acp_v2_runs` — it never writes to it, and T7 does
not itself trigger `acp_v2_slots` persistence. `is_quarter_fully_locked()` is the only thing
that BLOCKS an action (refusing to finalize a quarter plan whose every week is already
locked); partial lock status is exposed for display only, never enforced beyond that.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID


@dataclass(frozen=True)
class WeekLockStatus:
    year: int
    month: int
    week: int  # 1-4, matches compute_slot_grid()'s own numbering
    locked: bool
    reason: str | None  # "produced" | "past" | None (unlocked)


def _quarter_months(quarter: int) -> list[int]:
    return [(quarter - 1) * 3 + i for i in (1, 2, 3)]


async def fetch_quarter_lock_status(
    tenant_id: UUID, year: int, quarter: int, pool, today: date | None = None,
) -> list[WeekLockStatus]:
    """Returns lock status for all 12 (month, week) slots of the quarter (3 months x weeks
    1-4). `today` is injectable for tests; defaults to the real current date."""
    today = today or date.today()
    months = _quarter_months(quarter)

    async with pool.acquire() as conn:
        produced_rows = await conn.fetch(
            """
            SELECT month, week FROM acp_shared.acp_v2_runs
            WHERE tenant_id = $1 AND year = $2 AND month = ANY($3::smallint[])
            """,
            str(tenant_id), year, months,
        )
    produced: set[tuple[int, int]] = {(r["month"], r["week"]) for r in produced_rows}

    statuses: list[WeekLockStatus] = []
    for month in months:
        month_has_passed = (year, month) < (today.year, today.month)
        for week in (1, 2, 3, 4):
            if (month, week) in produced:
                statuses.append(WeekLockStatus(year, month, week, True, "produced"))
            elif month_has_passed:
                statuses.append(WeekLockStatus(year, month, week, True, "past"))
            else:
                statuses.append(WeekLockStatus(year, month, week, False, None))
    return statuses


def is_quarter_fully_locked(statuses: list[WeekLockStatus]) -> bool:
    """Blocks T7's finalize endpoint only when EVERY week of the quarter is already locked
    (produced or past) — per Nghiep's round 6 clarification, an in-progress quarter (some weeks
    locked, some not) must stay editable; only a quarter with nothing left to plan is refused."""
    return bool(statuses) and all(s.locked for s in statuses)


__all__ = ["WeekLockStatus", "fetch_quarter_lock_status", "is_quarter_fully_locked"]
