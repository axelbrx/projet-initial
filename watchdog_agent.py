"""Agent Data Hygiene Watchdog (Google ADK) : brouillon v0.1 du sprint 2, par Maxime.

  python watchdog_agent.py 3                              un jour (le simulateur doit avoir livré ce jour)
  python simulator.py step --agent watchdog_agent:run_day
  python simulator.py run  --agent watchdog_agent:run_day --timeout 1800

Principe : le simulateur n'appelle run_day qu'une fois par jour, et un plantage = journée sans agent.
Donc :
  1. tout est dans un try/except global, avec un budget de temps inférieur au timeout du simulateur ;
  2. les lectures et les règles fixes du sujet (lot manquant -> hand-off, profils, sondes de détection)
     passent par un client MCP direct, SANS LLM : cela économise le quota Gemini ;
  3. le LLM n'est appelé que pour les lots où une vérification a échoué (c'est là qu'est le jugement) ;
  4. un lot en échec n'arrête pas les suivants.
Tout passe par les tools du serveur MCP (login 'agent'), jamais par SQL direct.
"""
import kit  # d'abord : il vérifie la version de Python

import asyncio
import json
from collections import deque
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]")  # ADK annonce ses fonctions expérimentales
import logging
for _name in ("google_adk", "google.adk"):  # ADK imprime une pile de 300 lignes à chaque erreur du LLM ;
    logging.getLogger(_name).setLevel(logging.CRITICAL)  # notre ligne "[watchdog] ... failed: <cause>" suffit

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from watchdog_instructions import INSTRUCTIONS

# ---------------------------------------------------------------- réglages (à justifier en semaine 3)
MCP_SERVER = Path(kit.ENV.get("WATCHDOG_MCP_SERVER", kit.ROOT / "mcp_server.py"))  # nom à confirmer (Joumana)
DAY_BUDGET_S = int(kit.ENV.get("WATCHDOG_DAY_BUDGET", 780))   # reste sous le timeout du simulateur (900 s)
MAX_RETRIES = 4                                               # sur 429 / RESOURCE_EXHAUSTED
_LOCAL = kit.ENV.get("WATCHDOG_MODEL", "").startswith(("ollama", "openai/", "anthropic/"))
RPM = int(kit.ENV.get("WATCHDOG_RPM", 0 if _LOCAL else 5))    # requêtes LLM/minute (Gemini gratuit : 5) ; 0 = sans limite
LLM_TURN_TIMEOUT_S = int(kit.ENV.get("WATCHDOG_TURN_TIMEOUT", 120))  # sans événement du LLM ni d'un tool
NULL_JUMP = 0.05                                              # complétude : +5 points sur la baseline
FORMAT_DROP = 0.001                                           # validité : toute baisse mesurable du format
VOLUME_BAND = 0.30                                            # volume : +-30 % de la moyenne du jour de semaine
HANDOFF_RATIO = 0.20                                          # sous 20 % de la moyenne : hand-off
VOLUME_FEEDS = ("pos", "web")
DEFAULT_GEMINI = "gemini-flash-latest"
APP = "data_hygiene_watchdog"

# Sondes de détection (code, sans LLM) : (check_type, column_name, params de find_affected_rows).
# exact_duplicate et price_ratio_out_of_range sont dans le contrat v2.1 ; unknown_reference et
# near_duplicate_customer sont à AJOUTER (contrat v2.2). Une sonde refusée par le serveur est ignorée.
# Ce que veut dire le résultat de chaque sonde : sans cette phrase, un petit modèle compare les lignes
# signalées entre elles (donc les trouve toutes différentes) au lieu de les comparer aux lignes précédentes.
PROBE_MEANING = {
    "exact_duplicate": "VERIFIED BY CODE: each listed row is an exact copy of an EARLIER row of the same batch "
                       "(the listed rows are the extra copies, the first copy is not listed). Not a false positive: "
                       "do not compare the listed rows with each other. Quarantine them with quarantine_duplicate.",
    "unknown_reference": "VERIFIED BY CODE: the listed rows point to a SKU or customer absent from the reference "
                         "tables (check today's staging batches before concluding).",
    "price_ratio_out_of_range": "VERIFIED BY CODE: the listed prices are over 10x or under 0.1x the catalogue price.",
    "near_duplicate_customer": "CANDIDATE ONLY: the listed customers share a phone or postcode. This is often a "
                               "household. If the emails differ after normalisation AND the names differ, they are "
                               "two people: log_decision only, NO issue and NO ticket (a doubt is not a problem). "
                               "Propose a merge only if email AND phone or postcode agree.",
}

# Conseils ajoutés au message selon les signaux : ils ne dépendent d'aucun scénario.
SIGNAL_HINTS = {
    "completeness": "COMPLETENESS: a value that is on file is never a reason to quarantine. If a VALUES ON FILE block "
                    "is given, use it as it is (create_issue, then fill_from_source). Without such a block, look "
                    "the keys up with lookup_reference (customer_record, or web_order_email) before deciding. "
                    "Quarantine only rows no source can fill. An upstream cause means raise_ticket as well.",
    "schema": "SCHEMA DRIFT: do not call find_affected_rows (it has no schema mode). Compare missing_columns with "
              "new_columns using the sample rows. Always create_issue with check_type schema_drift, then "
              "map_column if the match is clear, otherwise raise_ticket.",
    "volume": "VOLUME: if the ratio matches a calendar event, only log_decision. You have no hand-off tool: "
              "missing or almost empty batches were already handled by code.",
}

# Un seul log_decision par lot : les modèles locaux le répètent 2 à 4 fois et polluent agent_log.
LOGGED = {"done": False}


def before_tool(tool, args, tool_context):
    if tool.name == "log_decision":
        if LOGGED["done"]:
            return {"status": "ok", "note": "decision already logged for this batch, nothing more to do"}
        LOGGED["done"] = True
    return None


# Tools que le LLM ne voit pas : le code les appelle lui-même (retire aussi la possibilité de les mal utiliser).
HIDDEN_FROM_LLM = {"hand_off", "get_feedback", "list_batches"}


def tool_visible(tool, readonly_context=None):
    return tool.name not in HIDDEN_FROM_LLM


PROBES = {
    "orders": [("uniqueness", None, {"mode": "exact_duplicate"}),
               ("consistency", None, {"mode": "unknown_reference"}),
               ("validity", "unit_price", {"mode": "price_ratio_out_of_range"})],
    "customers": [("uniqueness", None, {"mode": "exact_duplicate"}),
                  ("uniqueness", None, {"mode": "near_duplicate_customer"})],
    "products": [("uniqueness", None, {"mode": "exact_duplicate"})],
}


_T0 = time.monotonic()


def log(msg):
    print(f"  [watchdog +{time.monotonic() - _T0:5.1f}s] {msg}", flush=True)


# ---------------------------------------------------------------- LLM
def model_names():
    """Modèle principal, puis les modèles de secours (WATCHDOG_FALLBACK_MODELS, séparés par des virgules)."""
    first = kit.ENV.get("WATCHDOG_MODEL", DEFAULT_GEMINI)
    fallbacks = [m.strip() for m in kit.ENV.get("WATCHDOG_FALLBACK_MODELS", "").split(",") if m.strip()]
    return [first] + [m for m in fallbacks if m != first]


def model(name=None):
    name = name or model_names()[0]
    if name.startswith(("ollama", "openai/", "anthropic/")):  # tout ce que LiteLLM sait servir
        from google.adk.models.lite_llm import LiteLlm
        return LiteLlm(model=name)
    if not kit.ENV.get("GOOGLE_API_KEY"):
        raise RuntimeError("No LLM configured: set GOOGLE_API_KEY or WATCHDOG_MODEL in .env")
    os.environ.setdefault("GOOGLE_API_KEY", kit.ENV["GOOGLE_API_KEY"])
    return name


class RateLimiter:
    """Fenêtre glissante : jamais plus de `rpm` requêtes LLM sur `window` secondes.
    Chaque tour de LLM (y compris celui qui suit un appel de tool) est UNE requête : à 5 par minute,
    un lot de 5 tours occupe toute la minute. On attend ici plutôt que de se prendre un 429."""

    def __init__(self, rpm, window=61.0):
        self.rpm, self.window, self.stamps, self.lock = rpm, window, deque(), asyncio.Lock()
        self.count = 0

    async def wait(self):
        if self.rpm <= 0:  # modèle local : pas de quota, on compte seulement
            self.count += 1
            return
        async with self.lock:
            while True:
                now = time.monotonic()
                while self.stamps and now - self.stamps[0] >= self.window:
                    self.stamps.popleft()
                if len(self.stamps) < self.rpm:
                    self.stamps.append(now)
                    self.count += 1
                    return
                pause = self.stamps[0] + self.window - now + 0.05
                if pause > 1:
                    log(f"rate limiter: {self.rpm} requests/min reached, waiting {pause:.0f}s")
                await asyncio.sleep(pause)


LIMITER = RateLimiter(RPM)


async def before_model(callback_context, llm_request):
    """Callback ADK appelé avant chaque requête au LLM."""
    await LIMITER.wait()
    return None  # None = on laisse la requête partir


def is_transient(e):
    """Erreur du LLM qui passe d'elle-même : quota (429) ou surcharge côté Google (500, 502, 503, 504)."""
    if isinstance(e, TimeoutError):  # notre propre délai par tour : on le signale, on ne le rejoue pas
        return False
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in ("429", "resource_exhausted", "resourceexhausted", "rate limit", "quota", "503", "unavailable",
                                "high demand", "overloaded", "502", "504", "500 internal", "deadline_exceeded"))


# ---------------------------------------------------------------- client MCP direct (sans LLM)
class ToolError(RuntimeError):
    pass


def server_params():
    # MCP ne passe que quelques variables d'environnement au serveur : on passe les nôtres (PG_PORT, ...).
    server = os.environ.get("WATCHDOG_MCP_SERVER") or MCP_SERVER  # lu à l'appel : prompt_test.py le change
    return StdioServerParameters(command=sys.executable, args=[str(server)], env=dict(os.environ))


def unwrap(res):
    """Résultat d'un call_tool : lève ToolError si le tool a échoué, sinon renvoie le JSON."""
    text = " ".join(getattr(c, "text", "") or "" for c in (res.content or []))
    if res.is_error:  # MCP 2.x : champs en snake_case (is_error, structured_content)
        raise ToolError(text or "tool error")
    data = res.structured_content
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            return text
    if isinstance(data, dict) and set(data) == {"result"}:  # une liste renvoyée par un tool est enveloppée
        data = data["result"]
    if isinstance(data, dict) and data.get("status") == "error":  # convention du contrat : {status: "error", code, message}
        raise ToolError(f"{data.get('code')}: {data.get('message')}")
    return data


class Mcp:
    def __init__(self, session):
        self.session = session

    async def call(self, name, **args):
        return unwrap(await self.session.call_tool(name, {k: v for k, v in args.items() if v is not None}))

    async def try_call(self, name, **args):
        """Comme call, mais renvoie None au lieu de lever (sondes, journal : jamais bloquants)."""
        try:
            return await self.call(name, **args)
        except Exception as e:
            log(f"{name} ignored: {str(e)[:150]}")
            return None


# ---------------------------------------------------------------- détection par code (pré-filtre)
def screen_profile(profile):
    """Colonnes suspectes d'après le profil : complétude, validité, colonne nouvelle (renommage ou ajout).
    Une colonne MANQUANTE n'apparaît pas dans column_profiles (le profileur part des clés présentes) :
    le serveur doit la signaler dans missing_columns (contrat v2.2)."""
    signals = {}
    for p in profile.get("profiles", []):
        col = p["column_name"]
        null, base_null = p.get("null_rate"), p.get("baseline_null_rate")
        fmt, base_fmt = p.get("format_match"), p.get("baseline_format_match")
        if base_null is None and base_fmt is None:
            signals.setdefault("new_columns", []).append(col)  # pas de baseline : colonne ajoutée ou renommée
        if null is not None and base_null is not None and float(null) - float(base_null) > NULL_JUMP:
            signals.setdefault("completeness", []).append(
                {"column": col, "null_rate": float(null), "baseline": float(base_null)})
        if fmt is not None and base_fmt is not None and float(base_fmt) - float(fmt) > FORMAT_DROP:
            signals.setdefault("validity", []).append(
                {"column": col, "format_match": float(fmt), "baseline": float(base_fmt)})
    if profile.get("missing_columns"):
        signals["missing_columns"] = profile["missing_columns"]
    return signals


async def probe(mcp, batch):
    """Sondes find_affected_rows : ne renvoient que des comptes et quelques row_nums."""
    found = []
    for check, column, params in PROBES.get(batch["target_table"], []):
        res = await mcp.try_call("find_affected_rows", batch_id=batch["batch_id"], check_type=check,
                                 column_name=column, params=params, limit=200)
        if res and res.get("total_count"):
            found.append({"check": check, "mode": params["mode"], "column": column,
                          "total_count": res["total_count"], "first_row_nums": res.get("row_nums", [])[:20],
                          "meaning": PROBE_MEANING.get(params["mode"], ""),
                          "_rows": res.get("row_nums", [])[:200]})
    return found


# ---------------------------------------------------------------- un lot
async def handle_batch(mcp, ask, day, batch, feedback):
    bid, feed = batch["batch_id"], batch["feed_name"]
    profile = await mcp.call("get_batch_profile", batch_id=bid)
    signals = screen_profile(profile)

    if feed in VOLUME_FEEDS:
        vol = await mcp.call("get_volume_context", feed_name=feed, sim_day=day.isoformat())
        ratio = vol.get("ratio")
        if ratio is not None and ratio < HANDOFF_RATIO:  # règle du sujet : lot quasi vide, on passe la main
            res = await mcp.call("hand_off", batch_id=bid,
                                 reason=f"{feed} batch has {vol.get('row_count_today')} rows, "
                                        f"{ratio:.0%} of the same-weekday average ({vol.get('avg_same_weekday_30d')})")
            log(f"batch {bid} ({feed}): hand-off {res}")
            return
        if ratio is not None and abs(ratio - 1) > VOLUME_BAND:
            signals["volume"] = vol  # le LLM tranche : événement du calendrier ou incident

    found = await probe(mcp, batch)
    if found:
        signals["probes"] = found

    if not signals:
        await mcp.try_call("log_decision", sim_day=day.isoformat(), step=f"batch {bid} ({feed})",
                           decision="no check failed", reasoning="Profile within baseline, no probe hit.")
        log(f"batch {bid} ({feed}): clean, no LLM call")
        return

    # Lignes d'exemple lues par le CODE et mises dans le prompt : cela épargne au LLM un tour (donc une requête).
    wanted = []
    for f in signals.get("probes", []):
        wanted += f.get("first_row_nums", [])[:5]
    sample = await mcp.try_call("get_sample_rows", batch_id=bid, row_nums=sorted(set(wanted))[:10]) if wanted \
        else await mcp.try_call("get_sample_rows", batch_id=bid, limit=5)
    rows = [{"row_num": r.get("row_num"), **(r.get("payload") or {})} for r in (sample or {}).get("rows", [])]

    fills = await fill_candidates(mcp, batch, signals) if "completeness" in signals else []

    log(f"batch {bid} ({feed}): signals {sorted(signals)} -> LLM")
    await ask(build_prompt(day, batch, profile, signals, feedback, rows, fills))


async def fill_candidates(mcp, batch, signals):
    """Valeurs manquantes qu'une table de référence détient déjà (règle du sujet : on garde la valeur au dossier).
    Le CODE les cherche, le LLM n'a plus qu'à décider : un modèle local choisissait trop souvent la quarantaine."""
    out, bid = [], batch["batch_id"]
    if batch.get("target_table") != "customers":
        return out
    for sig in signals.get("completeness", []):
        col = sig["column"]
        hit = await mcp.try_call("find_affected_rows", batch_id=bid, check_type="completeness", column_name=col,
                                 params={"mode": "null"}, limit=200)
        nums = ((hit or {}).get("row_nums") or [])[:100]
        if not nums:
            continue
        sample = await mcp.try_call("get_sample_rows", batch_id=bid, row_nums=nums)
        keyed = {r.get("row_num"): (r.get("payload") or {}).get("customer_id") for r in (sample or {}).get("rows", [])}
        ids = sorted({v for v in keyed.values() if v})
        ref = await mcp.try_call("lookup_reference", kind="customer_record", keys=ids) if ids else None
        on_file = {x.get("key"): x.get("value") for x in (ref or {}).get("results", [])
                   if x.get("found") and isinstance(x.get("value"), dict)}
        changes, nothing = [], []
        for n in nums:
            val = (on_file.get(keyed.get(n)) or {}).get(col)
            if val in (None, ""):
                nothing.append(n)
            else:
                changes.append({"row_num": n, "before": None, "after": val})
        out.append({"column": col, "total_affected": (hit or {}).get("total_count", len(nums)),
                    "changes": changes, "nothing_on_file": nothing})
    return out


def _view(signals):
    """Signaux sans les champs internes (_rows) : ils sont déjà dits ailleurs dans le message."""
    out = json.loads(json.dumps(signals, default=str))
    for f in out.get("probes", []):
        f.pop("_rows", None)
    return out


def build_prompt(day, batch, profile, signals, feedback, rows=None, fills=None):
    head = {k: profile.get(k) for k in ("batch_id", "feed_name", "target_table", "batch_date", "row_count",
                                        "schema_hash", "missing_columns") if k in profile}
    parts = [f"Day {day.isoformat()}. Review this batch.",
             "BATCH:\n" + json.dumps(head, default=str),
             "CANDIDATE PROBLEMS from the code checks (verify them, do not trust them blindly):\n"
             + json.dumps(_view(signals), default=str, indent=1)]
    for f in signals.get("probes", []):
        if f.get("mode") == "exact_duplicate" and f.get("_rows"):
            parts.append("READY CALL for the exact duplicates (after create_issue): propose_fix with batch_id "
                         f"{batch['batch_id']}, table_name {batch.get('target_table')}, fix_type quarantine_duplicate, "
                         f"reasoning, and row_nums exactly {f['_rows']}. Send it once, with all these rows.")
    if rows:
        parts.append("SAMPLE ROWS already read for you (do not fetch them again):\n" + json.dumps(rows, default=str))
    for f in fills or []:
        if f["changes"]:
            txt = (f"VALUES ON FILE (verified by code in the reference table) for column {f['column']}: "
                   f"{len(f['changes'])} of {f['total_affected']} affected rows have a value on file. Do NOT "
                   f"quarantine those rows. Send ONE propose_fix with fix_type fill_from_source, column_name "
                   f"{f['column']} and exactly this changes list: {json.dumps(f['changes'][:60])}")
            if len(f["changes"]) > 60:
                txt += f" (first 60 shown of {len(f['changes'])}; send these 60, a later pass handles the rest)"
        else:
            txt = f"NO VALUE ON FILE for column {f['column']} in the reference table."
        if f["nothing_on_file"]:
            txt += (f". Rows with nothing on file: {f['nothing_on_file'][:60]}: quarantine only these, "
                    "and raise a ticket.")
        parts.append(txt)
    if feedback:
        parts.append("STEWARD FEEDBACK, fixes rejected earlier (change what you propose accordingly):\n"
                     + "\n".join(feedback))
    else:
        parts.append("STEWARD FEEDBACK: none so far. Do not call get_feedback.")
    hints = [SIGNAL_HINTS[k] for k, present in (
        ("completeness", "completeness" in signals),
        ("schema", "missing_columns" in signals or "new_columns" in signals),
        ("volume", "volume" in signals)) if present]
    if hints:
        parts.append("HINTS:\n" + "\n".join(hints))
    parts.append("Decide, act with your tools, and finish with one log_decision for this batch. "
                 "Every real problem gets a create_issue before its fix, quarantine or ticket.")
    return "\n\n".join(parts)


def compact_feedback(res):
    rows = res.get("feedback", []) if isinstance(res, dict) else res  # contrat : {feedback: [...]}
    out = []
    for r in rows or []:
        if r.get("status") == "rejected":
            out.append(f"- {r.get('fix_type')} on {r.get('table_name')}.{r.get('column_name')} "
                       f"(issue {r.get('issue_key')}), rejected: {r.get('rejection_reason')}")
    return out[:30]


# ---------------------------------------------------------------- le jour
async def run_llm_batches(day, work):
    """Ouvre ADK une seule fois pour tous les lots du jour ; une session par lot ; retry sur 429."""
    # Création à la demande : sans LLM disponible (clé absente, quota), tout ce que le code décide seul
    # (hand-off, lots propres) se fait quand même ; seuls les lots qui demandent du jugement sont en échec.
    state = {}
    models = model_names()  # models[0] est le modèle courant ; on passe au suivant si le LLM reste indisponible

    def ensure():
        if not state:
            toolset = McpToolset(connection_params=StdioConnectionParams(server_params=server_params(), timeout=30),
                                 tool_filter=tool_visible)
            agent = LlmAgent(name="data_hygiene_watchdog", model=model(models[0]), instruction=INSTRUCTIONS,
                             tools=[toolset], before_model_callback=before_model,
                             before_tool_callback=before_tool)
            state.update(toolset=toolset, runner=InMemoryRunner(agent=agent, app_name=APP))
        return state["runner"]

    async def close_state():
        if state:
            for key in ("toolset", "runner"):
                try:
                    await state[key].close()
                except BaseException:  # noqa: BLE001
                    pass
            state.clear()

    async def ask(text):
        timeouts = 0
        for attempt in range(MAX_RETRIES + 1):
            try:
                runner = ensure()
                LOGGED["done"] = False
                session = await runner.session_service.create_session(app_name=APP, user_id="simulator")
                async def turn(message):
                    """Un échange complet avec l'agent ; renvoie les noms des tools appelés."""
                    called = set()
                    msg = types.Content(role="user", parts=[types.Part(text=message)])
                    events = runner.run_async(user_id="simulator", session_id=session.id, new_message=msg).__aiter__()
                    try:
                        while True:
                            try:  # un tour de LLM (ou l'exécution d'un tool) qui ne répond pas ne doit pas geler la journée
                                event = await asyncio.wait_for(events.__anext__(), LLM_TURN_TIMEOUT_S)
                            except StopAsyncIteration:
                                break
                            except TimeoutError:
                                raise TimeoutError(f"no event from the LLM or a tool for {LLM_TURN_TIMEOUT_S}s "
                                                   "(quota ? modèle ? serveur MCP bloqué ?)") from None
                            for part in (event.content.parts if event.content else []) or []:
                                if part.function_call:
                                    called.add(part.function_call.name)
                                    log(f"[tool] {part.function_call.name}({json.dumps(dict(part.function_call.args or {}), default=str)[:160]})")
                                elif part.function_response:
                                    log(f"[tool result] {part.function_response.name}: {str(part.function_response.response)[:160]}")
                                elif part.text and not part.thought and event.is_final_response():
                                    log(f"[agent] {part.text.strip()[:300]}")
                    finally:
                        try:
                            await events.aclose()
                        except BaseException:  # noqa: BLE001
                            pass
                    return called

                called = await turn(text)
                if "log_decision" not in called:
                    # Le modèle s'est arrêté en route (réponse vide après un tool) : une relance, dans la même session.
                    log("agent stopped before log_decision, one reminder")
                    await turn("You stopped before finishing this batch: no log_decision was recorded. Do what is still "
                               "needed for each verified problem (fix, quarantine or ticket; fill_from_source when the "
                               "value is on file), then call log_decision. If it is not a real problem, only log_decision.")
                return
            except Exception as e:
                low = str(e).lower()
                if "perday" in low.replace(" ", "").replace("_", ""):  # quota JOURNALIER épuisé : attendre ne sert à rien
                    if len(models) > 1 and attempt < MAX_RETRIES:
                        log(f"daily quota of {models[0]} exhausted, switching to {models[1]}")
                        models.append(models.pop(0))
                        await close_state()
                        continue
                    raise RuntimeError(f"daily request quota exhausted for {models[0]} (see AI Studio, rate limits)") from e
                if ("not_found" in low or "no longer available" in low) and len(models) > 1 and attempt < MAX_RETRIES:
                    log(f"{models[0]} is not available for this key, switching to {models[1]}")
                    models.append(models.pop(0))  # modèle fermé ou retiré : inutile d'attendre, on passe au suivant
                    await close_state()
                    continue
                stuck = isinstance(e, TimeoutError)  # le LLM ne répond plus (souvent un 503 réessayé en interne)
                timeouts += stuck
                if (is_transient(e) or (stuck and timeouts <= 2)) and attempt < MAX_RETRIES:
                    if (attempt >= 1 or stuck) and len(models) > 1:  # le modèle reste indisponible : on passe au suivant
                        log(f"{models[0]} still unavailable, switching to {models[1]}")
                        models.append(models.pop(0))
                    if stuck or (attempt >= 1 and len(models) > 1):
                        await close_state()  # session ADK potentiellement bloquée : on repart d'une neuve
                    pause = 5 if stuck else min(10 * 2 ** attempt, 60)
                    log(f"LLM error ({str(e)[:90]}), retry in {pause}s ({attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(pause)  # les tools d'écriture sont idempotents : un rejeu est sans danger
                    continue
                raise

    try:
        await work(ask)
    finally:
        await close_state()


async def run_day_inner(day):
    async with stdio_client(server_params()) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        mcp = Mcp(session)
        listing = await mcp.call("list_batches", sim_day=day.isoformat())
        feedback = compact_feedback(await mcp.try_call("get_feedback", status="rejected", limit=50))

        for m in listing.get("missing_feeds", []):  # lot absent : hand-off (POS et web), sinon rien à faire
            if m["feed_name"] in VOLUME_FEEDS and m.get("batch_id"):
                res = await mcp.try_call("hand_off", batch_id=m["batch_id"],
                                         reason=f"{m['feed_name']} feed did not deliver a file for {day.isoformat()}")
                log(f"{m['feed_name']}: missing -> hand-off {res}")
            else:
                await mcp.try_call("log_decision", sim_day=day.isoformat(), step=f"feed {m['feed_name']} missing",
                                   decision="no action", reasoning="CRM and PIM send irregular updates; no file is normal.")

        async def work(ask):
            for batch in listing.get("batches", []):
                try:
                    await handle_batch(mcp, ask, day, batch, feedback)
                except Exception as e:  # un lot en échec ne doit pas empêcher les suivants
                    log(f"batch {batch['batch_id']} failed: {type(e).__name__}: {str(e)[:200]}")
                    await mcp.try_call("log_decision", sim_day=day.isoformat(),
                                       step=f"batch {batch['batch_id']} ({batch['feed_name']})",
                                       decision="batch not fully processed",
                                       reasoning=f"{type(e).__name__}: {str(e)[:300]}")

        await run_llm_batches(day, work)


async def run_day(day):
    """Point d'entrée du simulateur. Ne lève jamais : le pire cas est une journée sans correction."""
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(DAY_BUDGET_S):
            await run_day_inner(day)
        log(f"day {day.isoformat()} done in {time.monotonic() - t0:.0f}s, {LIMITER.count} LLM request(s) sent")
    except BaseException as e:  # noqa: BLE001 (volontaire : y compris le timeout du budget)
        if isinstance(e, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise  # annulation venue de l'extérieur : on ne l'avale pas (notre propre budget donne TimeoutError)
        while isinstance(e, BaseExceptionGroup) and e.exceptions:  # anyio enveloppe l'erreur réelle dans un groupe
            e = e.exceptions[0]
        log(f"day {day.isoformat()} stopped: {type(e).__name__}: {str(e)[:300]}")
        try:  # on tente de laisser une trace dans agent_log
            async with stdio_client(server_params()) as (r, w), ClientSession(r, w) as session:
                await session.initialize()
                await Mcp(session).try_call("log_decision", sim_day=day.isoformat(), step="run_day",
                                            decision="aborted", reasoning=f"{type(e).__name__}: {str(e)[:300]}")
        except BaseException:  # noqa: BLE001
            pass


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit() or not 1 <= int(sys.argv[1]) <= kit.SIM_DAYS:
        sys.exit(f"Usage: python watchdog_agent.py DAY   (1 to {kit.SIM_DAYS})")
    asyncio.run(run_day(kit.sim_dates()[int(sys.argv[1]) - 1]))