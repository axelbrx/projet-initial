"""Tests de prompts de l'agent sur le faux serveur MCP (tâche 1.7). Un scénario = un run_day.

  python prompt_test.py --dry            vérifie le montage SANS LLM (aucune clé nécessaire)
  python prompt_test.py                  lance l'agent avec le vrai LLM (Gemini ou Ollama, cf. .env)
  python prompt_test.py household        un seul scénario
  python prompt_test.py --repeat 3       3 essais par scénario : un LLM n'est pas déterministe

Chaque scénario dit ce que l'agent DOIT faire et ce qu'il ne DOIT PAS faire. Ces attentes sont celles
des règles du sujet, pas celles d'un scénario du simulateur.
Compte environ 3 à 8 requêtes LLM par scénario avec LLM : à lancer avec parcimonie sur le quota gratuit.
"""
import kit  # d'abord

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAY = date(2026, 11, 3)


def calls(log, tool=None):
    return [c for c in log if tool is None or c["tool"] == tool]


def fix_types(log):
    return {c["args"].get("fix_type") for c in calls(log, "propose_fix")}


# (description, vérification(log) -> None si OK, sinon message)
EXPECT = {
    "dup_orders": [
        ("quarantine_duplicate sur les copies (6)",
         lambda L: None if any(c["args"]["fix_type"] == "quarantine_duplicate" and c["args"]["affected_rows"] == 6
                               for c in calls(L, "propose_fix")) else "pas de quarantine_duplicate sur 6 lignes"),
        ("aucune suppression ni merge", lambda L: None if "merge" not in fix_types(L) else "merge inattendu"),
        ("une décision journalisée", lambda L: None if calls(L, "log_decision") else "pas de log_decision"),
    ],
    "renamed_column": [
        ("map_column qty -> quantity", lambda L: None if "map_column" in fix_types(L) else "pas de map_column"),
        ("issue de type schema_drift", lambda L: None if any(c["args"]["check_type"] == "schema_drift"
                                                            for c in calls(L, "create_issue")) else "pas d'issue schema_drift"),
    ],
    "crm_email_empty": [
        ("garde l'email au dossier (fill_from_source) ou ticket",
         lambda L: None if ("fill_from_source" in fix_types(L) or calls(L, "raise_ticket")) else "ni fill ni ticket"),
        ("ne met pas tout en quarantaine à l'aveugle",
         lambda L: None if not any(c["args"]["count"] >= 12 for c in calls(L, "quarantine_rows")) else "12 lignes en quarantaine"),
    ],
    "calendar_spike": [
        ("aucune issue de volume (événement du calendrier)",
         lambda L: None if not calls(L, "create_issue") else "issue créée sur un événement attendu"),
        ("aucun hand-off, aucun fix",
         lambda L: None if not calls(L, "hand_off") and not calls(L, "propose_fix") else "action inutile"),
    ],
    "household": [
        ("aucun merge entre deux personnes d'un même foyer",
         lambda L: None if "merge" not in fix_types(L) and not calls(L, "quarantine_rows") else "merge ou quarantaine à tort"),
        ("aucune issue", lambda L: None if not calls(L, "create_issue") else "fausse alarme"),
    ],
    "missing_pos": [
        ("hand-off du lot absent (règle codée)", lambda L: None if calls(L, "hand_off") else "pas de hand-off"),
        ("aucune autre action", lambda L: None if not calls(L, "propose_fix") and not calls(L, "quarantine_rows") else "action sur un lot absent"),
    ],
}
# En mode --dry le LLM est remplacé : seuls les scénarios entièrement décidés par le code ont un verdict.
DRY_DECIDED = {"missing_pos"}


async def run_one(name, dry):
    log_path = HERE / f"mock_calls_{name}.jsonl"
    log_path.unlink(missing_ok=True)
    os.environ.update({"MOCK_SCENARIO": name, "MOCK_LOG": str(log_path),
                       "WATCHDOG_MCP_SERVER": str(HERE / "mock_mcp.py")})
    import watchdog_agent as w
    prompts = []
    if dry:
        async def stub(day, work):
            async def ask(text):
                prompts.append(text)
            await work(ask)
        w.run_llm_batches = stub
    await w.run_day(DAY)
    log = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
    return log, prompts


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=list(EXPECT))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    failures = 0
    for name in args.scenarios:
        for attempt in range(args.repeat):
            log, prompts = await run_one(name, args.dry)
            tag = f"{name}" + (f" #{attempt + 1}" if args.repeat > 1 else "")
            if args.dry and name not in DRY_DECIDED:
                woke = "LLM appelé" if prompts else "LLM NON appelé"
                print(f"[dry] {tag}: {woke} ({len(prompts)} prompt), écritures par le code: "
                      f"{[c['tool'] for c in log]}")
                continue
            print(f"\n== {tag}: {len(log)} appels d'écriture {[c['tool'] for c in log]}")
            # Un run où l'agent a planté (pas de clé LLM, quota, ...) n'est PAS un succès, même si les
            # attentes négatives ("ne rien faire") sont techniquement respectées.
            if any(c["tool"] == "log_decision"
                   and c["args"].get("decision") in ("aborted", "batch not fully processed") for c in log):
                failures += 1
                print("   ABANDON l'agent s'est arrêté avant de juger (voir le message [watchdog] ci-dessus), scénario non évalué")
                continue
            for desc, check in EXPECT[name]:
                msg = check(log)
                failures += msg is not None
                print(f"   {'OK  ' if msg is None else 'ECHEC'} {desc}" + ("" if msg is None else f"  -> {msg}"))
    if not args.dry:
        print(f"\n{failures} échec(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())