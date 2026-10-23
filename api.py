"""REST API for the Data Hygiene Watchdog UI.

Run it from the repository root (the simulator imports the agent module
from there), with the virtual environment active:

    uvicorn api:app --reload --port 8000

Interactive documentation: http://localhost:8000/docs

This API connects as `watchdog` (see kit.connect), the login that may
approve or reject fixes and read sim_results. Never give that login to
the agent.
"""
import os
import threading
from contextlib import contextmanager
from datetime import date, timedelta

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

DEFAULT_AGENT = os.getenv("WATCHDOG_AGENT", "noop_agent:run_day")
CORS_ORIGINS = os.getenv(
    "API_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")

# Target table of a fix (fixes.table_name) -> staging table.
STAGING_TABLES = {
    "orders": "staging_orders",
    "customers": "staging_customers",
    "products": "staging_products",
}
# Staging rows the simulator has already converted: nothing to restore.
PROCESSED = ("promoted", "merged", "lost")
# Fix statuses from which a person may still undo.
UNDOABLE = ("applied", "awaiting_approval", "approved")

DAY_FILTER = "(%(d)s::date IS NULL OR b.batch_date = %(d)s::date)"

app = FastAPI(title="Data Hygiene Watchdog API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only one simulation step at a time: a step can take minutes.
_step_lock = threading.Lock()


DB_DOWN = getattr(kit, "DatabaseUnavailable", psycopg.OperationalError)


@app.exception_handler(DB_DOWN)
async def database_down_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ---------------------------------------------------------------- helpers
@contextmanager
def db():
    """One connection per request: commit on success, roll back on error."""
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


def fetch_all(query, params=None):
    params = {"start": kit.SIM_START, **(params or {})}
    with db() as conn:
        return conn.execute(query, params).fetchall()


def day_to_date(day):
    """Simulation day number (1 = Monday 2 November) -> calendar date."""
    if day is None:
        return None
    if not 1 <= day <= kit.SIM_DAYS:
        raise HTTPException(422, f"day must be between 1 and {kit.SIM_DAYS}")
    return kit.SIM_START + timedelta(days=day - 1)


def date_to_day(value):
    return None if value is None else (value - kit.SIM_START).days + 1


# ---------------------------------------------------------------- health
@app.get("/api/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "database": "up"}


# ---------------------------------------------------------------- batches
BATCHES_SQL = """
SELECT b.batch_id, b.feed_name, b.target_table, b.batch_date,
       (b.batch_date - %(start)s::date + 1) AS day,
       b.row_count, b.status, b.loaded_at
FROM batches b
WHERE b.batch_date >= %(start)s::date AND """ + DAY_FILTER + """
ORDER BY b.batch_date DESC, b.batch_id
"""


@app.get("/api/batches")
def list_batches(day: int | None = Query(None, ge=1)):
    return fetch_all(BATCHES_SQL, {"d": day_to_date(day)})


# ---------------------------------------------------------------- issues
ISSUES_SQL = """
SELECT i.issue_id, i.batch_id, b.feed_name, b.batch_date,
       (b.batch_date - %(start)s::date + 1) AS day,
       i.issue_key, i.check_type, i.column_name, i.affected_rows,
       i.description, i.status, i.created_at,
       (SELECT count(*) FROM fixes f WHERE f.issue_id = i.issue_id)
           AS fix_count
FROM issues i
JOIN batches b ON b.batch_id = i.batch_id
WHERE """ + DAY_FILTER + """
  AND (%(status)s::text IS NULL OR i.status = %(status)s::text)
ORDER BY b.batch_date DESC, i.issue_id
"""


@app.get("/api/issues")
def list_issues(
    day: int | None = Query(None, ge=1),
    status: str | None = None,
):
    return fetch_all(ISSUES_SQL, {"d": day_to_date(day), "status": status})


# ---------------------------------------------------------------- fixes
FIXES_SQL = """
SELECT f.fix_id, f.issue_id, f.batch_id, b.feed_name, b.batch_date,
       (b.batch_date - %(start)s::date + 1) AS day,
       f.table_name, f.column_name, f.fix_type, f.record_id,
       f.before_value, f.after_value, f.reasoning, f.status,
       f.decided_by, f.decided_on, f.applied_on, f.rejection_reason,
       f.created_at
FROM fixes f
LEFT JOIN batches b ON b.batch_id = f.batch_id
WHERE """ + DAY_FILTER + """
  AND (%(status)s::text IS NULL OR f.status = %(status)s::text)
  AND (%(issue_id)s::bigint IS NULL OR f.issue_id = %(issue_id)s::bigint)
ORDER BY f.fix_id DESC
"""


def list_fixes_query(day, status, issue_id):
    params = {"d": day_to_date(day), "status": status, "issue_id": issue_id}
    return fetch_all(FIXES_SQL, params)


@app.get("/api/fixes")
def list_fixes(
    day: int | None = Query(None, ge=1),
    status: str | None = None,
    issue_id: int | None = None,
):
    return list_fixes_query(day, status, issue_id)


@app.get("/api/approvals")
def approval_queue():
    """Fixes waiting for a person (status awaiting_approval)."""
    return list_fixes_query(None, "awaiting_approval", None)


class Decision(BaseModel):
    decided_by: str = Field(min_length=1, description="Name of the person")
    rejection_reason: str | None = None


def decide(fix_id, new_status, decided_by, reason):
    query = (
        "UPDATE fixes SET status = %s, decided_by = %s, "
        "rejection_reason = %s "
        "WHERE fix_id = %s AND status = 'awaiting_approval' RETURNING *"
    )
    with db() as conn:
        row = conn.execute(
            query, (new_status, decided_by, reason, fix_id)
        ).fetchone()
        if row is not None:
            return row
        current = conn.execute(
            "SELECT status FROM fixes WHERE fix_id = %s", (fix_id,)
        ).fetchone()
    if current is None:
        raise HTTPException(404, f"Fix {fix_id} not found")
    raise HTTPException(
        409,
        f"Fix {fix_id} is '{current['status']}': only fixes that are "
        "'awaiting_approval' can be approved or rejected",
    )


@app.post("/api/fixes/{fix_id}/approve")
def approve_fix(fix_id: int, body: Decision):
    """Approve a fix. The simulator applies it the next morning."""
    return decide(fix_id, "approved", body.decided_by, None)


@app.post("/api/fixes/{fix_id}/reject")
def reject_fix(fix_id: int, body: Decision):
    """Reject a fix. The agent can read the reason the same day."""
    return decide(fix_id, "rejected", body.decided_by, body.rejection_reason)


def restore_staging(conn, fix):
    """Put the value from before the fix back into the staging payload.

    Returns (rows restored, rows already processed by the simulator).
    Rows already promoted, merged or lost cannot be restored: the core
    tables are owned by the simulator.
    """
    staging = STAGING_TABLES.get(fix["table_name"])
    if staging is None:
        raise HTTPException(409, f"Unknown table '{fix['table_name']}'")
    if fix["fix_type"] == "merge":
        raise HTTPException(409, "A merge cannot be undone from the API")
    table = sql.Identifier(staging)

    if fix["fix_type"] == "map_column":
        # before_value = delivered name, after_value = usual name.
        update = sql.SQL(
            "UPDATE {} SET payload = (payload - %(after)s::text) || "
            "jsonb_build_object(%(before)s::text, payload -> %(after)s::text)"
            " WHERE batch_id = %(batch)s AND payload ? %(after)s::text "
            "AND status NOT IN ('promoted', 'merged', 'lost')"
        ).format(table)
        params = {
            "before": fix["before_value"],
            "after": fix["after_value"],
            "batch": fix["batch_id"],
        }
        restored = conn.execute(update, params).rowcount
        total = conn.execute(
            sql.SQL("SELECT count(*) AS n FROM {} WHERE batch_id = %s "
                    "AND status IN ('promoted', 'merged', 'lost')")
            .format(table),
            (fix["batch_id"],),
        ).fetchone()["n"]
        return restored, total

    try:
        row_num = int(fix["record_id"])
    except (TypeError, ValueError):
        raise HTTPException(409, "record_id is not a staging row number")
    row = conn.execute(
        sql.SQL("SELECT status, payload FROM {} "
                "WHERE batch_id = %s AND row_num = %s FOR UPDATE")
        .format(table),
        (fix["batch_id"], row_num),
    ).fetchone()
    if row is None:
        raise HTTPException(409, "The staging row no longer exists")
    if row["status"] in PROCESSED:
        return 0, 1
    payload = dict(row["payload"])
    payload[fix["column_name"]] = fix["before_value"]  # None -> JSON null
    conn.execute(
        sql.SQL("UPDATE {} SET payload = %s::jsonb "
                "WHERE batch_id = %s AND row_num = %s").format(table),
        (Jsonb(payload), fix["batch_id"], row_num),
    )
    return 1, 0


@app.post("/api/fixes/{fix_id}/undo")
def undo_fix(fix_id: int):
    """Undo a fix: restore the staging value and mark the fix 'undone'."""
    with db() as conn:
        fix = conn.execute(
            "SELECT * FROM fixes WHERE fix_id = %s FOR UPDATE", (fix_id,)
        ).fetchone()
        if fix is None:
            raise HTTPException(404, f"Fix {fix_id} not found")
        if fix["status"] not in UNDOABLE:
            raise HTTPException(
                409,
                f"Fix {fix_id} is '{fix['status']}': only "
                f"{', '.join(UNDOABLE)} fixes can be undone",
            )
        restored, processed = 0, 0
        was_applied = fix["status"] == "applied" or fix["applied_on"]
        if was_applied:
            restored, processed = restore_staging(conn, fix)
        conn.execute(
            "UPDATE fixes SET status = 'undone' WHERE fix_id = %s", (fix_id,)
        )
    result = {
        "fix_id": fix_id,
        "status": "undone",
        "staging_rows_restored": restored,
        "rows_already_processed": processed,
    }
    if processed:
        result["warning"] = (
            "Some rows were already promoted: the core tables are not "
            "changed, only the staging payload and the fix status."
        )
    return result


# ---------------------------------------------------------------- others
@app.get("/api/agent-log")
def agent_log(day: int | None = Query(None, ge=1)):
    query = """
        SELECT l.log_id, l.sim_day, (l.sim_day - %(start)s::date + 1) AS day,
               l.step, l.decision, l.reasoning, l.created_at
        FROM agent_log l
        WHERE (%(d)s::date IS NULL OR l.sim_day = %(d)s::date)
        ORDER BY l.log_id DESC
    """
    return fetch_all(query, {"d": day_to_date(day)})


@app.get("/api/tickets")
def list_tickets():
    return fetch_all("SELECT * FROM tickets ORDER BY ticket_id DESC")


@app.get("/api/hand-offs")
def list_hand_offs(day: int | None = Query(None, ge=1)):
    query = """
        SELECT h.hand_off_id, h.batch_id, b.feed_name, b.batch_date,
               h.to_agent, h.reason, h.created_at
        FROM hand_offs h
        JOIN batches b ON b.batch_id = h.batch_id
        WHERE """ + DAY_FILTER + """
        ORDER BY h.hand_off_id DESC
    """
    return fetch_all(query, {"d": day_to_date(day)})


@app.get("/api/quarantine")
def list_quarantine(day: int | None = Query(None, ge=1)):
    query = """
        SELECT q.quarantine_id, q.batch_id, b.feed_name, b.batch_date,
               q.table_name, q.row_num, q.issue_id, q.reason,
               q.created_at, q.released_at
        FROM quarantine q
        JOIN batches b ON b.batch_id = q.batch_id
        WHERE """ + DAY_FILTER + """
        ORDER BY q.quarantine_id DESC
    """
    return fetch_all(query, {"d": day_to_date(day)})


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
    return fetch_all(query, {"feed": feed, "column": column})


# ---------------------------------------------------------------- KPIs
@app.get("/api/kpis")
def kpis(day: int | None = Query(None, ge=1)):
    """KPI tiles. Without `day`, totals over all delivered days."""
    params = {"start": kit.SIM_START, "d": day_to_date(day)}
    counts_sql = """
        SELECT
          (SELECT count(*) FROM issues i
             JOIN batches b ON b.batch_id = i.batch_id
             WHERE """ + DAY_FILTER + """) AS issues_detected,
          (SELECT count(*) FROM quarantine q
             JOIN batches b ON b.batch_id = q.batch_id
             WHERE q.released_at IS NULL AND """ + DAY_FILTER + """)
             AS rows_quarantined,
          (SELECT count(*) FROM hand_offs h
             JOIN batches b ON b.batch_id = h.batch_id
             WHERE """ + DAY_FILTER + """) AS hand_offs,
          (SELECT avg(data_health) FROM sim_results
             WHERE (%(d)s::date IS NULL OR sim_day = %(d)s::date))
             AS data_health
    """
    fixes_sql = """
        SELECT f.status, count(*) AS n
        FROM fixes f
        JOIN batches b ON b.batch_id = f.batch_id
        WHERE """ + DAY_FILTER + """
        GROUP BY f.status
    """
    with db() as conn:
        result = conn.execute(counts_sql, params).fetchone()
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(fixes_sql, params).fetchall()
        }
    result["fixes_auto_applied"] = by_status.get("applied", 0)
    result["fixes_awaiting_approval"] = by_status.get("awaiting_approval", 0)
    result["fixes_approved"] = by_status.get("approved", 0)
    result["fixes_rejected"] = by_status.get("rejected", 0)
    result["fixes_undone"] = by_status.get("undone", 0)
    result["day"] = day
    return result


# ---------------------------------------------------------------- simulation
def simulation_state():
    with db() as conn:
        last = conn.execute(
            "SELECT max(batch_date) AS last FROM batches "
            "WHERE batch_date >= %s",
            (kit.SIM_START,),
        ).fetchone()["last"]
        finished = False
        if last is not None:
            finished = conn.execute(
                "SELECT 1 FROM sim_results WHERE sim_day = %s", (last,)
            ).fetchone() is not None
    delivered = date_to_day(last)
    if delivered is None:
        next_day, unfinished = 1, False
    elif finished:
        next_day, unfinished = delivered + 1, False
    else:
        next_day, unfinished = delivered, True
    return {
        "total_days": kit.SIM_DAYS,
        "last_delivered_day": delivered,
        "unfinished_day": delivered if unfinished else None,
        "next_day": None if next_day > kit.SIM_DAYS else next_day,
        "complete": next_day > kit.SIM_DAYS,
        "running": _step_lock.locked(),
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
    pass


def run_step(agent, timeout, resume):
    import simulator  # imported here so the API starts without a scenario

    try:
        return simulator.step(agent, timeout=timeout, resume=resume)
    except SystemExit as exc:  # the simulator exits with a message
        raise StepError(str(exc.code))


@app.post("/api/simulation/step")
async def simulation_step(body: StepRequest | None = None):
    """Run the next day with the agent. Blocks until the day is finished."""
    body = body or StepRequest()
    agent = body.agent or DEFAULT_AGENT
    if not _step_lock.acquire(blocking=False):
        raise HTTPException(409, "A simulation step is already running")
    try:
        day = await run_in_threadpool(
            run_step, agent, body.timeout, body.resume
        )
    except StepError as exc:
        raise HTTPException(409, str(exc))
    finally:
        _step_lock.release()
    result = None
    if day is not None:
        rows = fetch_all(
            "SELECT sim_day, caught, missed, fixed_correctly, "
            "wrongly_changed, false_alarms, data_health, details "
            "FROM sim_results WHERE sim_day = %(d)s",
            {"d": day_to_date(day)},
        )
        result = rows[0] if rows else None
    return {"day": day, "complete": day is None, "result": result,
            "state": simulation_state()}


@app.get("/api/simulation/report")
def simulation_report():
    """Same numbers as `python simulator.py report`, as JSON."""
    rows = fetch_all(
        "SELECT sim_day, (sim_day - %(start)s::date + 1) AS day, caught, "
        "missed, fixed_correctly, wrongly_changed, false_alarms, "
        "data_health, details FROM sim_results ORDER BY sim_day"
    )
    keys = ("caught", "missed", "fixed_correctly", "wrongly_changed",
            "false_alarms")
    totals = {key: sum(r[key] or 0 for r in rows) for key in keys}
    health = [float(r["data_health"]) for r in rows
              if r["data_health"] is not None]
    totals["data_health_mean"] = sum(health) / len(health) if health else None
    return {"days": rows, "totals": totals}
