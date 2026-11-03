"""REST API for the Data Hygiene Watchdog UI.

Start it from the repository root, with the virtual environment active
(the simulator imports the agent module from there):

    uvicorn api:app --reload --port 8000

Swagger documentation: http://localhost:8000/docs

The API logs in to PostgreSQL as `watchdog` (see kit.connect). This login
can approve or reject fixes and read sim_results, so it must never be
given to the agent.
"""
import os
import threading
from contextlib import contextmanager
from datetime import timedelta

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

import kit


# ======================================================================
# Settings
# ======================================================================

# Agent used by /api/simulation/step when the request does not name one.
DEFAULT_AGENT = os.getenv("WATCHDOG_AGENT", "noop_agent:run_day")

# Addresses of the frontend allowed to call the API (Vite and CRA ports).
CORS_ORIGINS = os.getenv(
    "API_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")

# A fix names its target table; the rows to restore live in staging.
STAGING_TABLE_FOR = {
    "orders": "staging_orders",
    "customers": "staging_customers",
    "products": "staging_products",
}

# Staging rows the simulator has already handled: we can no longer
# change them.
ALREADY_PROCESSED = ("promoted", "merged", "lost")

# A fix can only be undone from one of these statuses.
UNDOABLE_STATUSES = ("applied", "awaiting_approval", "approved")

# The kit may define its own "database down" error; otherwise we fall
# back to the psycopg one.
DatabaseDown = getattr(kit, "DatabaseUnavailable", psycopg.OperationalError)


# ======================================================================
# Application
# ======================================================================

app = FastAPI(title="Data Hygiene Watchdog API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A simulation day can take several minutes: we only run one at a time.
step_lock = threading.Lock()


@app.exception_handler(DatabaseDown)
async def database_down(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ======================================================================
# Helpers
# ======================================================================

@contextmanager
def open_db():
    """Open a connection for one request.

    Everything is committed at the end, or rolled back if something
    failed along the way.
    """
    conn = kit.connect()
    conn.row_factory = dict_row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_query(query, params=None):
    """Run a SELECT and return every row as a dict.

    The simulation start date is always available as %(start)s.
    """
    all_params = {"start": kit.SIM_START}
    if params:
        all_params.update(params)
    with open_db() as conn:
        return conn.execute(query, all_params).fetchall()


def day_to_date(day):
    """Turn a simulation day (1 = Monday 2 November) into a date."""
    if day is None:
        return None
    if day < 1 or day > kit.SIM_DAYS:
        raise HTTPException(422, f"day must be between 1 and {kit.SIM_DAYS}")
    return kit.SIM_START + timedelta(days=day - 1)


def date_to_day(value):
    """Turn a date back into a simulation day number."""
    if value is None:
        return None
    return (value - kit.SIM_START).days + 1


# Most lists can be filtered on one day. When %(d)s is NULL, the filter
# lets every row through.
ONE_DAY_OR_ALL = "(%(d)s::date IS NULL OR b.batch_date = %(d)s::date)"


# ======================================================================
# Health
# ======================================================================

@app.get("/api/health")
def health():
    with open_db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "database": "up"}


# ======================================================================
# Batches
# ======================================================================

@app.get("/api/batches")
def list_batches(day: int | None = Query(None, ge=1)):
    query = f"""
        SELECT b.batch_id, b.feed_name, b.target_table, b.batch_date,
               (b.batch_date - %(start)s::date + 1) AS day,
               b.row_count, b.status, b.loaded_at
        FROM batches b
        WHERE b.batch_date >= %(start)s::date AND {ONE_DAY_OR_ALL}
        ORDER BY b.batch_date DESC, b.batch_id
    """
    return run_query(query, {"d": day_to_date(day)})


# ======================================================================
# Issues
# ======================================================================

@app.get("/api/issues")
def list_issues(
    day: int | None = Query(None, ge=1),
    status: str | None = None,
):
    # table_name is the second part of issue_key (feed:table:column:check).
    #
    # action says what was done about the issue, in this order of priority:
    #   approval    a fix waits for a person
    #   hand-off    volume problem handed to the Data Sync Monitor
    #   quarantined rows of this issue are in quarantine
    #   ticket      a ticket exists for this issue_key
    #   auto-fixed  a fix was applied
    #   approved    a person approved a fix (the simulator applies it later)
    # It is NULL when nothing was done (yet).
    query = f"""
        SELECT i.issue_id, i.batch_id, b.feed_name, b.batch_date,
               (b.batch_date - %(start)s::date + 1) AS day,
               i.issue_key, split_part(i.issue_key, ':', 2) AS table_name,
               i.check_type, i.column_name, i.affected_rows,
               i.description, i.status, i.created_at,
               (SELECT count(*) FROM fixes f WHERE f.issue_id = i.issue_id)
                   AS fix_count,
               CASE
                 WHEN EXISTS (SELECT 1 FROM fixes f
                              WHERE f.issue_id = i.issue_id
                                AND f.status = 'awaiting_approval')
                   THEN 'approval'
                 WHEN i.check_type = 'volume'
                      AND EXISTS (SELECT 1 FROM hand_offs h
                                  WHERE h.batch_id = i.batch_id)
                   THEN 'hand-off'
                 WHEN EXISTS (SELECT 1 FROM quarantine q
                              WHERE q.issue_id = i.issue_id
                                AND q.released_at IS NULL)
                   THEN 'quarantined'
                 WHEN EXISTS (SELECT 1 FROM tickets t
                              WHERE t.issue_key = i.issue_key)
                   THEN 'ticket'
                 WHEN EXISTS (SELECT 1 FROM fixes f
                              WHERE f.issue_id = i.issue_id
                                AND f.status = 'applied')
                   THEN 'auto-fixed'
                 WHEN EXISTS (SELECT 1 FROM fixes f
                              WHERE f.issue_id = i.issue_id
                                AND f.status = 'approved')
                   THEN 'approved'
               END AS action
        FROM issues i
        JOIN batches b ON b.batch_id = i.batch_id
        WHERE {ONE_DAY_OR_ALL}
          AND (%(status)s::text IS NULL OR i.status = %(status)s::text)
        ORDER BY b.batch_date DESC, i.issue_id
    """
    return run_query(query, {"d": day_to_date(day), "status": status})


# ======================================================================
# Fixes and approvals
# ======================================================================

def find_fixes(day=None, status=None, issue_id=None):
    query = f"""
        SELECT f.fix_id, f.issue_id, f.batch_id, b.feed_name, b.batch_date,
               (b.batch_date - %(start)s::date + 1) AS day,
               i.check_type, i.description AS issue_description,
               f.table_name, f.column_name, f.fix_type, f.record_id,
               f.before_value, f.after_value, f.reasoning, f.status,
               f.decided_by, f.decided_on, f.applied_on, f.rejection_reason,
               f.created_at
        FROM fixes f
        LEFT JOIN batches b ON b.batch_id = f.batch_id
        LEFT JOIN issues i ON i.issue_id = f.issue_id
        WHERE {ONE_DAY_OR_ALL}
          AND (%(status)s::text IS NULL OR f.status = %(status)s::text)
          AND (%(issue_id)s::bigint IS NULL
               OR f.issue_id = %(issue_id)s::bigint)
        ORDER BY f.fix_id DESC
    """
    params = {"d": day_to_date(day), "status": status, "issue_id": issue_id}
    return run_query(query, params)


@app.get("/api/fixes")
def list_fixes(
    day: int | None = Query(None, ge=1),
    status: str | None = None,
    issue_id: int | None = None,
):
    return find_fixes(day, status, issue_id)


@app.get("/api/approvals")
def approval_queue():
    """Fixes waiting for a person (status awaiting_approval)."""
    return find_fixes(status="awaiting_approval")


@app.get("/api/approval-groups")
def approval_groups():
    """Fixes waiting for a person, one entry per issue.

    One card in the UI = one issue, even if it holds hundreds of fixes
    (340 postcodes). Fixes that belong to no issue are not listed here:
    they stay available one by one in /api/approvals.
    """
    query = """
        SELECT g.issue_id, i.issue_key, i.check_type,
               i.description AS issue_description,
               b.feed_name, b.batch_date,
               (b.batch_date - %(start)s::date + 1) AS day,
               g.table_name, g.column_name, g.fix_types, g.fix_count,
               s.record_id AS sample_record_id,
               s.before_value AS sample_before,
               s.after_value AS sample_after,
               s.reasoning
        FROM (
            SELECT issue_id, min(fix_id) AS first_fix_id,
                   min(table_name) AS table_name,
                   min(column_name) AS column_name,
                   array_agg(DISTINCT fix_type) AS fix_types,
                   count(*) AS fix_count
            FROM fixes
            WHERE status = 'awaiting_approval' AND issue_id IS NOT NULL
            GROUP BY issue_id
        ) g
        JOIN issues i ON i.issue_id = g.issue_id
        LEFT JOIN batches b ON b.batch_id = i.batch_id
        JOIN fixes s ON s.fix_id = g.first_fix_id
        ORDER BY g.issue_id DESC
    """
    return run_query(query)


class Decision(BaseModel):
    decided_by: str = Field(min_length=1, description="Name of the person")
    rejection_reason: str | None = None


def record_decision(fix_id, new_status, decided_by, reason):
    """Approve or reject a fix that is waiting for a person."""
    with open_db() as conn:
        updated = conn.execute(
            """
            UPDATE fixes
            SET status = %s, decided_by = %s, rejection_reason = %s
            WHERE fix_id = %s AND status = 'awaiting_approval'
            RETURNING *
            """,
            (new_status, decided_by, reason, fix_id),
        ).fetchone()
        if updated is not None:
            return updated

        # Nothing changed: either the fix does not exist, or it is not
        # waiting for approval any more.
        existing = conn.execute(
            "SELECT status FROM fixes WHERE fix_id = %s", (fix_id,)
        ).fetchone()

    if existing is None:
        raise HTTPException(404, f"Fix {fix_id} not found")
    raise HTTPException(
        409,
        f"Fix {fix_id} is '{existing['status']}': only fixes that are "
        "'awaiting_approval' can be approved or rejected",
    )


@app.post("/api/fixes/{fix_id}/approve")
def approve_fix(fix_id: int, body: Decision):
    """Approve a fix. The simulator applies it the next morning."""
    return record_decision(fix_id, "approved", body.decided_by, None)


@app.post("/api/fixes/{fix_id}/reject")
def reject_fix(fix_id: int, body: Decision):
    """Reject a fix. The agent can read the reason the same day."""
    return record_decision(
        fix_id, "rejected", body.decided_by, body.rejection_reason
    )


def record_issue_decision(issue_id, new_status, decided_by, reason):
    """Approve or reject every fix of one issue that waits for a person.

    This is what an approval card does: one click, all its fixes.
    """
    with open_db() as conn:
        updated = conn.execute(
            """
            UPDATE fixes
            SET status = %s, decided_by = %s, rejection_reason = %s
            WHERE issue_id = %s AND status = 'awaiting_approval'
            RETURNING fix_id
            """,
            (new_status, decided_by, reason, issue_id),
        ).fetchall()
        if updated:
            return {
                "issue_id": issue_id,
                "status": new_status,
                "fixes_updated": len(updated),
            }

        # Nothing changed: unknown issue, or nothing left to decide.
        issue = conn.execute(
            "SELECT 1 FROM issues WHERE issue_id = %s", (issue_id,)
        ).fetchone()

    if issue is None:
        raise HTTPException(404, f"Issue {issue_id} not found")
    raise HTTPException(
        409, f"Issue {issue_id} has no fix awaiting approval"
    )


@app.post("/api/issues/{issue_id}/approve")
def approve_issue(issue_id: int, body: Decision):
    """Approve all the fixes of an issue. Applied the next morning."""
    return record_issue_decision(issue_id, "approved", body.decided_by, None)


@app.post("/api/issues/{issue_id}/reject")
def reject_issue(issue_id: int, body: Decision):
    """Reject all the fixes of an issue, with one reason for all."""
    return record_issue_decision(
        issue_id, "rejected", body.decided_by, body.rejection_reason
    )


# ======================================================================
# Undo
# ======================================================================

def undo_column_mapping(conn, table, fix):
    """Give the renamed column its delivered name back, for the whole batch.

    For a map_column fix, before_value is the name the feed sent and
    after_value is the usual name the agent mapped it to.
    Returns (rows restored, rows the simulator had already processed).
    """
    restored = conn.execute(
        sql.SQL("""
            UPDATE {table}
            SET payload = (payload - %(after)s::text)
                || jsonb_build_object(%(before)s::text,
                                      payload -> %(after)s::text)
            WHERE batch_id = %(batch)s
              AND payload ? %(after)s::text
              AND status NOT IN ('promoted', 'merged', 'lost')
        """).format(table=table),
        {
            "before": fix["before_value"],
            "after": fix["after_value"],
            "batch": fix["batch_id"],
        },
    ).rowcount

    already_processed = conn.execute(
        sql.SQL("""
            SELECT count(*) AS n FROM {table}
            WHERE batch_id = %s
              AND status IN ('promoted', 'merged', 'lost')
        """).format(table=table),
        (fix["batch_id"],),
    ).fetchone()["n"]

    return restored, already_processed


def undo_single_value(conn, table, fix):
    """Put the old value back in one staging row.

    Returns (rows restored, rows the simulator had already processed).
    """
    try:
        row_num = int(fix["record_id"])
    except (TypeError, ValueError):
        raise HTTPException(409, "record_id is not a staging row number")

    row = conn.execute(
        sql.SQL("""
            SELECT status, payload FROM {table}
            WHERE batch_id = %s AND row_num = %s
            FOR UPDATE
        """).format(table=table),
        (fix["batch_id"], row_num),
    ).fetchone()

    if row is None:
        raise HTTPException(409, "The staging row no longer exists")
    if row["status"] in ALREADY_PROCESSED:
        return 0, 1

    payload = dict(row["payload"])
    # A None before_value becomes a JSON null, as delivered.
    payload[fix["column_name"]] = fix["before_value"]
    conn.execute(
        sql.SQL("""
            UPDATE {table} SET payload = %s::jsonb
            WHERE batch_id = %s AND row_num = %s
        """).format(table=table),
        (Jsonb(payload), fix["batch_id"], row_num),
    )
    return 1, 0


def restore_staging(conn, fix):
    """Undo the change a fix made in its staging table.

    Rows already promoted, merged or lost are left alone: the core tables
    belong to the simulator.
    """
    staging_name = STAGING_TABLE_FOR.get(fix["table_name"])
    if staging_name is None:
        raise HTTPException(409, f"Unknown table '{fix['table_name']}'")
    if fix["fix_type"] == "merge":
        raise HTTPException(409, "A merge cannot be undone from the API")

    table = sql.Identifier(staging_name)
    if fix["fix_type"] == "map_column":
        return undo_column_mapping(conn, table, fix)
    return undo_single_value(conn, table, fix)


@app.post("/api/fixes/{fix_id}/undo")
def undo_fix(fix_id: int):
    """Undo a fix: restore the staging value and mark the fix 'undone'."""
    with open_db() as conn:
        fix = conn.execute(
            "SELECT * FROM fixes WHERE fix_id = %s FOR UPDATE", (fix_id,)
        ).fetchone()

        if fix is None:
            raise HTTPException(404, f"Fix {fix_id} not found")
        if fix["status"] not in UNDOABLE_STATUSES:
            raise HTTPException(
                409,
                f"Fix {fix_id} is '{fix['status']}': only "
                f"{', '.join(UNDOABLE_STATUSES)} fixes can be undone",
            )

        # A fix still waiting for approval never touched the data, so
        # there is nothing to restore: we only change its status.
        restored, already_processed = 0, 0
        if fix["status"] == "applied" or fix["applied_on"]:
            restored, already_processed = restore_staging(conn, fix)

        conn.execute(
            "UPDATE fixes SET status = 'undone' WHERE fix_id = %s", (fix_id,)
        )

    result = {
        "fix_id": fix_id,
        "status": "undone",
        "staging_rows_restored": restored,
        "rows_already_processed": already_processed,
    }
    if already_processed:
        result["warning"] = (
            "Some rows were already promoted: the core tables are not "
            "changed, only the staging payload and the fix status."
        )
    return result


# ======================================================================
# Agent log, tickets, hand-offs, quarantine
# ======================================================================

@app.get("/api/agent-log")
def agent_log(day: int | None = Query(None, ge=1)):
    query = """
        SELECT l.log_id, l.sim_day, (l.sim_day - %(start)s::date + 1) AS day,
               l.step, l.decision, l.reasoning, l.created_at
        FROM agent_log l
        WHERE (%(d)s::date IS NULL OR l.sim_day = %(d)s::date)
        ORDER BY l.log_id DESC
    """
    return run_query(query, {"d": day_to_date(day)})


@app.get("/api/tickets")
def list_tickets():
    return run_query("SELECT * FROM tickets ORDER BY ticket_id DESC")


@app.get("/api/hand-offs")
def list_hand_offs(day: int | None = Query(None, ge=1)):
    query = f"""
        SELECT h.hand_off_id, h.batch_id, b.feed_name, b.batch_date,
               h.to_agent, h.reason, h.created_at
        FROM hand_offs h
        JOIN batches b ON b.batch_id = h.batch_id
        WHERE {ONE_DAY_OR_ALL}
        ORDER BY h.hand_off_id DESC
    """
    return run_query(query, {"d": day_to_date(day)})


@app.get("/api/quarantine")
def list_quarantine(day: int | None = Query(None, ge=1)):
    query = f"""
        SELECT q.quarantine_id, q.batch_id, b.feed_name, b.batch_date,
               q.table_name, q.row_num, q.issue_id, q.reason,
               q.created_at, q.released_at
        FROM quarantine q
        JOIN batches b ON b.batch_id = q.batch_id
        WHERE {ONE_DAY_OR_ALL}
        ORDER BY q.quarantine_id DESC
    """
    return run_query(query, {"d": day_to_date(day)})


@app.get("/api/column-history")
def column_history(feed: str, column: str):
    """Null rate and format match of one column over time (UI chart)."""
    query = """
        SELECT b.batch_date, (b.batch_date - %(start)s::date + 1) AS day,
               cp.null_rate, cp.baseline_null_rate, cp.format_match,
               cp.baseline_format_match, cp.promoted_null_rate
        FROM column_profiles cp
        JOIN batches b ON b.batch_id = cp.batch_id
        WHERE b.feed_name = %(feed)s AND cp.column_name = %(column)s
        ORDER BY b.batch_date
    """
    return run_query(query, {"feed": feed, "column": column})


# ======================================================================
# KPI tiles
# ======================================================================

@app.get("/api/kpis")
def kpis(day: int | None = Query(None, ge=1)):
    """KPI tiles. Without `day`, totals over all delivered days."""
    params = {"start": kit.SIM_START, "d": day_to_date(day)}

    counts_query = f"""
        SELECT
          (SELECT count(*) FROM issues i
             JOIN batches b ON b.batch_id = i.batch_id
             WHERE {ONE_DAY_OR_ALL}) AS issues_detected,
          (SELECT count(*) FROM quarantine q
             JOIN batches b ON b.batch_id = q.batch_id
             WHERE q.released_at IS NULL AND {ONE_DAY_OR_ALL})
             AS rows_quarantined,
          (SELECT count(*) FROM hand_offs h
             JOIN batches b ON b.batch_id = h.batch_id
             WHERE {ONE_DAY_OR_ALL}) AS hand_offs,
          (SELECT count(DISTINCT f.issue_id) FROM fixes f
             JOIN batches b ON b.batch_id = f.batch_id
             WHERE f.status = 'applied' AND {ONE_DAY_OR_ALL})
             AS issues_auto_fixed,
          (SELECT count(DISTINCT f.issue_id) FROM fixes f
             JOIN batches b ON b.batch_id = f.batch_id
             WHERE f.status = 'awaiting_approval'
               AND f.issue_id IS NOT NULL AND {ONE_DAY_OR_ALL})
             AS approvals_pending,
          (SELECT avg(data_health) FROM sim_results
             WHERE (%(d)s::date IS NULL OR sim_day = %(d)s::date))
             AS data_health
    """
    fixes_by_status_query = f"""
        SELECT f.status, count(*) AS n
        FROM fixes f
        JOIN batches b ON b.batch_id = f.batch_id
        WHERE {ONE_DAY_OR_ALL}
        GROUP BY f.status
    """

    with open_db() as conn:
        tiles = conn.execute(counts_query, params).fetchone()
        rows = conn.execute(fixes_by_status_query, params).fetchall()

    fixes_by_status = {row["status"]: row["n"] for row in rows}
    tiles["fixes_auto_applied"] = fixes_by_status.get("applied", 0)
    tiles["fixes_awaiting_approval"] = fixes_by_status.get(
        "awaiting_approval", 0
    )
    tiles["fixes_approved"] = fixes_by_status.get("approved", 0)
    tiles["fixes_rejected"] = fixes_by_status.get("rejected", 0)
    tiles["fixes_undone"] = fixes_by_status.get("undone", 0)
    tiles["day"] = day
    return tiles


# ======================================================================
# Simulation
# ======================================================================

def simulation_state():
    """Where the simulation is: last day delivered, next day to run."""
    with open_db() as conn:
        last_date = conn.execute(
            "SELECT max(batch_date) AS last FROM batches "
            "WHERE batch_date >= %s",
            (kit.SIM_START,),
        ).fetchone()["last"]

        day_has_results = False
        if last_date is not None:
            found = conn.execute(
                "SELECT 1 FROM sim_results WHERE sim_day = %s", (last_date,)
            ).fetchone()
            day_has_results = found is not None

    last_day = date_to_day(last_date)

    # Three cases: nothing delivered yet, last day finished, or last day
    # delivered but stopped before its results were written.
    if last_day is None:
        next_day = 1
        unfinished_day = None
    elif day_has_results:
        next_day = last_day + 1
        unfinished_day = None
    else:
        next_day = last_day
        unfinished_day = last_day

    complete = next_day > kit.SIM_DAYS
    return {
        "total_days": kit.SIM_DAYS,
        "last_delivered_day": last_day,
        "unfinished_day": unfinished_day,
        "next_day": None if complete else next_day,
        "complete": complete,
        "running": step_lock.locked(),
        "default_agent": DEFAULT_AGENT,
    }


@app.get("/api/simulation/state")
def get_simulation_state():
    return simulation_state()


class StepRequest(BaseModel):
    agent: str | None = Field(
        None, description="module:function, e.g. watchdog_agent:run_day"
    )
    resume: bool = False
    timeout: int = Field(900, ge=10)


class StepError(Exception):
    """The simulator refused to run the day (it gives the reason)."""


def run_one_day(agent, timeout, resume):
    # Imported here so the API can start before a scenario is chosen.
    import simulator

    try:
        return simulator.step(agent, timeout=timeout, resume=resume)
    except SystemExit as exc:
        # The simulator stops with sys.exit("message") when it refuses.
        raise StepError(str(exc.code))


@app.post("/api/simulation/step")
async def simulation_step(body: StepRequest | None = None):
    """Run the next day with the agent. Blocks until the day is finished."""
    body = body or StepRequest()
    agent = body.agent or DEFAULT_AGENT

    if not step_lock.acquire(blocking=False):
        raise HTTPException(409, "A simulation step is already running")
    try:
        # The step is slow and blocking: run it outside the event loop.
        day = await run_in_threadpool(
            run_one_day, agent, body.timeout, body.resume
        )
    except StepError as exc:
        raise HTTPException(409, str(exc))
    finally:
        step_lock.release()

    # day is None when the 28 days were already done.
    day_result = None
    if day is not None:
        rows = run_query(
            """
            SELECT sim_day, caught, missed, fixed_correctly,
                   wrongly_changed, false_alarms, data_health, details
            FROM sim_results WHERE sim_day = %(d)s
            """,
            {"d": day_to_date(day)},
        )
        if rows:
            day_result = rows[0]

    return {
        "day": day,
        "complete": day is None,
        "result": day_result,
        "state": simulation_state(),
    }


@app.get("/api/simulation/report")
def simulation_report():
    """Same numbers as `python simulator.py report`, as JSON."""
    days = run_query(
        """
        SELECT sim_day, (sim_day - %(start)s::date + 1) AS day, caught,
               missed, fixed_correctly, wrongly_changed, false_alarms,
               data_health, details
        FROM sim_results ORDER BY sim_day
        """
    )

    totals = {}
    for key in ("caught", "missed", "fixed_correctly", "wrongly_changed",
                "false_alarms"):
        totals[key] = sum(day[key] or 0 for day in days)

    health_values = [
        float(day["data_health"]) for day in days
        if day["data_health"] is not None
    ]
    if health_values:
        totals["data_health_mean"] = sum(health_values) / len(health_values)
    else:
        totals["data_health_mean"] = None

    return {"days": days, "totals": totals}
