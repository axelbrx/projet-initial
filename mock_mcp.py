"""Faux serveur MCP pour développer l'agent SANS attendre Joumana ni la base de données.

Il imite les tools du contrat (v2.1 + ajouts v2.2) sur de petits scénarios en mémoire et note
chaque appel d'écriture dans un fichier JSONL, que prompt_test.py relit pour vérifier les décisions.
Ce n'est pas le vrai serveur : il ne prouve rien sur la base, seulement sur le comportement de l'agent.

  MOCK_SCENARIO=dup_orders MOCK_LOG=calls.jsonl python mock_mcp.py     (lancé par l'agent, en stdio)
"""
import json
import os
import re

from mcp.server import MCPServer

mcp = MCPServer("watchdog-mock")
SCENARIO = os.environ.get("MOCK_SCENARIO", "dup_orders")
LOG = os.environ.get("MOCK_LOG", "mock_calls.jsonl")
SAFE = {"standardise_format", "quarantine_duplicate", "map_column", "fill_from_source"}


def err(code, message):
    """Convention du contrat : un tool qui échoue renvoie {status: error, code, message} (une exception serait
    masquée par le serveur : le LLM ne verrait que « Error executing tool »)."""
    return {"status": "error", "code": code, "message": message}


def _order(i, **kw):
    r = {"order_id": f"W2026110300{i:03d}", "customer_id": f"C0001{i:02d}", "customer_email": f"c{i}@example.com",
         "sku_id": "SKU-00001", "quantity": "1", "unit_price": "19.99", "order_ts": "2026-11-03 10:00:00"}
    r.update(kw)
    return r


def _crm(i, **kw):
    r = {"customer_id": f"C0002{i:02d}", "name": f"Anna Smith{i}", "email": f"anna{i}@example.com",
         "phone": f"07700 9001{i:02d}", "postcode": "LS1 4AB", "created_at": "2026-11-03"}
    r.update(kw)
    return r


def _profile(cols, **extra):
    return {"profiles": [{"column_name": c, "null_rate": 0.0, "baseline_null_rate": 0.0, "format_match": 1.0,
                          "baseline_format_match": 1.0, "distinct_count": 10} for c in cols], **extra}


ORDER_COLS = ["order_id", "customer_id", "customer_email", "sku_id", "quantity", "unit_price", "order_ts"]
CRM_COLS = ["customer_id", "name", "email", "phone", "postcode", "created_at"]


def build():
    """Un scénario = un dict. 'expect' est lu par prompt_test.py, pas par le serveur."""
    s = {"batches": [], "missing": [], "profile": {}, "volume": {}, "rows": {}, "customers_on_file": {},
         "web_emails": {}, "catalogue": {"SKU-00001": 19.99}, "feedback": []}
    if SCENARIO == "dup_orders":  # doublons exacts de commandes POS : quarantaine auto, pas de ticket
        rows = [_order(i) for i in range(1, 21)] + [dict(_order(i)) for i in range(1, 7)]
        s["batches"] = [{"batch_id": 1, "feed_name": "pos", "target_table": "orders", "row_count": len(rows)}]
        s["rows"] = {1: rows}
        s["profile"] = {1: _profile(ORDER_COLS)}
        s["volume"] = {"pos": (len(rows), 26.0)}
    elif SCENARIO == "renamed_column":  # quantity livrée sous le nom qty : map_column
        rows = [{**{k: v for k, v in _order(i).items() if k != "quantity"}, "qty": "1"} for i in range(1, 31)]
        s["batches"] = [{"batch_id": 1, "feed_name": "web", "target_table": "orders", "row_count": 30}]
        s["rows"] = {1: rows}
        p = _profile([c for c in ORDER_COLS if c != "quantity"])
        p["profiles"].append({"column_name": "qty", "null_rate": 0.0, "baseline_null_rate": None, "format_match": None,
                              "baseline_format_match": None, "distinct_count": 1})
        p.update(missing_columns=["quantity"], new_columns=["qty"])
        s["profile"] = {1: p}
        s["volume"] = {"web": (30, 30.0)}
    elif SCENARIO == "crm_email_empty":  # email vide sur des clients connus : on garde la valeur au dossier
        rows = [_crm(i, email=None) for i in range(1, 13)]
        s["batches"] = [{"batch_id": 1, "feed_name": "crm", "target_table": "customers", "row_count": 12}]
        s["rows"] = {1: rows}
        p = _profile(CRM_COLS)
        for c in p["profiles"]:
            if c["column_name"] == "email":
                c.update(null_rate=1.0, format_match=None)
        s["profile"] = {1: p}
        s["customers_on_file"] = {r["customer_id"]: {**r, "email": f"anna{i}@example.com"} for i, r in enumerate(rows, 1)}
    elif SCENARIO == "calendar_spike":  # gros volume attendu (événement au calendrier) : ne rien corriger
        rows = [_order(i) for i in range(1, 61)]
        s["batches"] = [{"batch_id": 1, "feed_name": "web", "target_table": "orders", "row_count": 60}]
        s["rows"] = {1: rows}
        s["profile"] = {1: _profile(ORDER_COLS)}
        s["volume"] = {"web": (60, 25.0)}
        s["calendar"] = [{"name": "Black Friday", "date": "2026-11-03", "type": "sale"}]
    elif SCENARIO == "household":  # même téléphone, personnes différentes : PAS un doublon
        rows = [_crm(1, name="Anna Smith", email="anna.smith@example.com", phone="07700 900111"),
                _crm(2, name="Tom Smith", email="tom.smith@example.com", phone="07700 900111")]
        s["batches"] = [{"batch_id": 1, "feed_name": "crm", "target_table": "customers", "row_count": 2}]
        s["rows"] = {1: rows}
        s["profile"] = {1: _profile(CRM_COLS)}
    elif SCENARIO == "missing_pos":  # lot POS absent : hand-off décidé par le code, sans LLM
        s["batches"] = []
        s["missing"] = [{"feed_name": "pos", "batch_id": 7}]
    return s


S = build()


def rec(tool, **args):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": tool, "args": args}, default=str) + "\n")


def _batch(bid):
    for b in S["batches"]:
        if b["batch_id"] == bid:
            return {**b, "batch_date": "2026-11-03", "status": "landed"}
    raise ValueError(f"batch {bid} not found")


# ---------------------------------------------------------------- lecture
@mcp.tool()
def list_batches(sim_day: str) -> dict:
    """List the batches of a day and the feeds that did not deliver."""
    return {"sim_day": sim_day, "batches": [_batch(b["batch_id"]) for b in S["batches"]], "missing_feeds": S["missing"]}


@mcp.tool()
def get_batch_profile(batch_id: int) -> dict:
    """Quality profile of a batch next to its baseline; also missing_columns and new_columns."""
    b = _batch(batch_id)
    return {**b, "schema_hash": "x", "missing_columns": [], "new_columns": [], **S["profile"][batch_id]}


@mcp.tool()
def get_volume_context(feed_name: str, sim_day: str) -> dict:
    """Row count today against the same-weekday 30-day average, with trading calendar events."""
    n, avg = S["volume"].get(feed_name, (0, None))
    return {"feed_name": feed_name, "sim_day": sim_day, "row_count_today": n, "avg_same_weekday_30d": avg,
            "ratio": None if not avg else n / avg, "calendar_events": S.get("calendar", [])}


@mcp.tool()
def get_sample_rows(batch_id: int, limit: int = 10, offset: int = 0, row_nums: list[int] | None = None) -> dict:
    """A few rows of a batch (row_num, payload, status)."""
    rows = S["rows"][batch_id]
    idx = [n - 1 for n in row_nums] if row_nums else range(offset, min(offset + limit, len(rows)))
    return {"batch_id": batch_id, "rows": [{"row_num": i + 1, "payload": rows[i], "status": "pending"}
                                           for i in idx if 0 <= i < len(rows)][:100]}


@mcp.tool()
def find_affected_rows(batch_id: int, check_type: str, column_name: str | None = None, params: dict | None = None,
                       limit: int = 100, offset: int = 0) -> dict:
    """Row numbers of a batch hit by a problem. Modes: null, format_invalid, exact_duplicate,
    price_ratio_out_of_range, unknown_reference, near_duplicate_customer."""
    mode, rows, hit = (params or {}).get("mode"), S["rows"][batch_id], []
    if mode == "null" and column_name:
        hit = [i + 1 for i, r in enumerate(rows) if r.get(column_name) in (None, "")]
    elif mode == "exact_duplicate":
        seen = set()
        for i, r in enumerate(rows):
            k = json.dumps(r, sort_keys=True)
            if k in seen:
                hit.append(i + 1)
            seen.add(k)
    elif mode == "price_ratio_out_of_range":
        for i, r in enumerate(rows):
            try:
                ref = S["catalogue"].get(r.get("sku_id"))
                if ref and not 0.1 <= float(r["unit_price"]) / ref <= 10:
                    hit.append(i + 1)
            except (TypeError, ValueError):
                pass
    elif mode == "unknown_reference":
        hit = [i + 1 for i, r in enumerate(rows) if r.get("sku_id") and r["sku_id"] not in S["catalogue"]]
    elif mode == "near_duplicate_customer":
        # Une sonde naïve (même téléphone) signale le foyer : à l'agent de juger que ce n'est pas un doublon.
        hit = [1, 2] if SCENARIO == "household" else []  # la paire, pas seulement la nouvelle ligne
    elif mode == "format_invalid":
        hit = []
    else:
        return err("bad_mode", f"unknown or missing mode {mode!r}: pass params={{'mode': ...}} with one of null, format_invalid, exact_duplicate, price_ratio_out_of_range, unknown_reference, near_duplicate_customer")
    return {"batch_id": batch_id, "check_type": check_type, "column_name": column_name, "total_count": len(hit),
            "row_nums": hit[offset:offset + min(limit, 500)], "next_offset": None}


@mcp.tool()
def lookup_reference(kind: str, keys: list[str]) -> dict:
    """kind: product_price, product_exists, customer_exists, customer_record, web_order_email."""
    out = []
    for k in keys:
        if kind == "product_price":
            v = S["catalogue"].get(k)
        elif kind == "product_exists":
            v = k in S["catalogue"]
        elif kind == "customer_record":
            v = S["customers_on_file"].get(k)
        elif kind == "customer_exists":
            v = k in S["customers_on_file"]
        elif kind == "web_order_email":
            v = S["web_emails"].get(k)
        else:
            return err("bad_kind", f"unknown kind {kind!r}")
        out.append({"key": k, "found": bool(v) or v == 0, "value": v})
    return {"kind": kind, "results": out}


@mcp.tool()
def get_feedback(batch_id: int | None = None, status: str | None = None, limit: int = 50) -> dict:
    """Fixes the steward decided on, with the rejection reason."""
    return {"feedback": S["feedback"]}


# ---------------------------------------------------------------- écriture (journalisée)
@mcp.tool()
def create_issue(batch_id: int, issue_key: str, check_type: str, description: str, column_name: str | None = None,
                 affected_rows: int | None = None) -> dict:
    """Record a detected problem. issue_key format: feed:table:column:check."""
    if check_type not in {"completeness", "uniqueness", "validity", "consistency", "schema_drift", "volume"}:
        return err("bad_check_type", "check_type must be one of completeness, uniqueness, validity, consistency, schema_drift, volume")
    if not re.fullmatch(r"[a-z]+:[a-z]+:[a-z_*]+:[a-z_]+", issue_key):
        return err("bad_issue_key", "issue_key must look like feed:table:column:check")
    rec("create_issue", batch_id=batch_id, issue_key=issue_key, check_type=check_type, affected_rows=affected_rows)
    return {"issue_id": 1, "issue_key": issue_key, "status": "open", "consecutive_days": 1}


@mcp.tool()
def propose_fix(batch_id: int, table_name: str, fix_type: str, reasoning: str, issue_id: int | None = None,
                column_name: str | None = None, row_nums: list[int] | None = None, changes: list[dict] | None = None,
                after_value: str | None = None, merge_with: str | None = None) -> dict:
    """Apply a safe fix (200 rows or fewer) or queue it for approval."""
    if fix_type not in SAFE | {"merge", "correct_value"}:
        return err("bad_fix_type", f"unknown fix_type {fix_type!r}")
    # Mêmes contraintes que le contrat v2.1 : un modèle qui invente des paramètres doit échouer ici aussi.
    if fix_type == "map_column" and (not column_name or not after_value or row_nums or changes):
        return err("bad_args", "map_column: pass column_name (the name in this file) and after_value (the usual "
                               "column name); no row_nums, no changes")
    if fix_type in {"standardise_format", "fill_from_source", "correct_value"}:
        ok_changes = bool(changes) and all(isinstance(c, dict) and {"row_num", "before", "after"} <= set(c) for c in changes)
        if not (ok_changes or (row_nums and after_value is not None)):
            return err("bad_args", f"{fix_type}: pass changes=[{{row_num, before, after}}, ...] (exactly these keys) "
                                   "and column_name, or row_nums + after_value when every row gets the same value")
    if fix_type == "quarantine_duplicate" and not row_nums:
        return err("bad_args", "quarantine_duplicate: pass row_nums = the extra copies")
    if fix_type == "merge" and (not merge_with or not row_nums):
        return err("bad_args", "merge: pass row_nums = the duplicate row(s) and merge_with = customer_id kept")
    n = 1 if fix_type == "map_column" else len(row_nums or [c["row_num"] for c in (changes or [])])
    status = "applied" if fix_type in SAFE and n <= 200 else "awaiting_approval"
    rec("propose_fix", batch_id=batch_id, fix_type=fix_type, column_name=column_name, affected_rows=n, status=status,
        after_value=after_value, merge_with=merge_with)
    return {"status": status, "affected_rows": n, "sample_fix_ids": [1, 2, 3][:n], "message": "ok"}


@mcp.tool()
def quarantine_rows(batch_id: int, row_nums: list[int], reason: str, issue_id: int | None = None) -> dict:
    """Quarantine rows that cannot be fixed (never deletes)."""
    rec("quarantine_rows", batch_id=batch_id, count=len(row_nums), reason=reason)
    return {"quarantined_count": len(row_nums), "status": "quarantined"}


@mcp.tool()
def raise_ticket(issue_key: str, title: str, related_issue_keys: list[str] | None = None, root_cause: str | None = None,
                 affected_rows: int | None = None, sample: dict | list | None = None, drafted_fix: str | None = None,
                 priority: str = "normal") -> dict:
    """Ticket for the team that owns the source feed."""
    rec("raise_ticket", issue_key=issue_key, title=title, related=related_issue_keys)
    return {"ticket_id": 1, "status": "open", "priority": priority}


@mcp.tool()
def hand_off(batch_id: int, reason: str) -> dict:
    """Hand a missing or almost empty POS/web batch to the Data Sync Monitor."""
    rec("hand_off", batch_id=batch_id, reason=reason)
    return {"hand_off_id": 1, "batch_id": batch_id, "to_agent": "data_sync_monitor"}


@mcp.tool()
def log_decision(sim_day: str, step: str, decision: str, reasoning: str) -> dict:
    """Record a decision and its reasoning."""
    rec("log_decision", step=step, decision=decision)
    return {"log_id": 1, "status": "ok"}


if __name__ == "__main__":
    mcp.run()