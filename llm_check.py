"""Teste Gemini seul, sans l'agent ni MCP : sépare « Google est lent ou surchargé » de « mon code est cassé ».

  python llm_check.py                      liste les modèles Gemini disponibles sur ta clé, puis chronomètre 1 appel
  python llm_check.py gemini-xxx           chronomètre un appel sur ce modèle (nom pris dans la liste)
  python llm_check.py modèle1 modèle2      compare plusieurs modèles

Lit GOOGLE_API_KEY dans .env, comme le reste du kit.
"""
import kit  # d'abord

import sys
import time

from google import genai

key = kit.ENV.get("GOOGLE_API_KEY")
if not key:
    sys.exit("GOOGLE_API_KEY manquante dans .env")
client = genai.Client(api_key=key)

names = []
try:
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions and "gemini" in m.name:
            names.append(m.name.removeprefix("models/"))
except Exception as e:  # noqa: BLE001
    print(f"(liste des modèles indisponible : {type(e).__name__}: {str(e)[:120]})")
if len(sys.argv) == 1 and names:
    print("Modèles Gemini disponibles (generateContent) :")
    for n in sorted(names):
        print("  ", n)

targets = sys.argv[1:] or [kit.ENV.get("WATCHDOG_MODEL", "gemini-flash-latest")]
for model in targets:
    t0 = time.monotonic()
    try:
        r = client.models.generate_content(model=model, contents="Reply with the single word: pong")
        print(f"{model}: OK en {time.monotonic() - t0:.1f}s -> {(r.text or '').strip()[:40]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"{model}: ECHEC après {time.monotonic() - t0:.1f}s -> {type(e).__name__}: {str(e)[:160]}")
