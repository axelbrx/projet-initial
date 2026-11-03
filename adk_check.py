"""Où l'agent se bloque-t-il ? Teste ADK + Gemini en trois étapes chronométrées, par modèle.

  python adk_check.py gemini-2.5-flash gemini-flash-latest

  1. ADK sans tools          -> le modèle répond-il via ADK ?
  2. ADK avec les tools MCP  -> l'envoi des schémas de tools bloque-t-il ?
  3. ADK avec les vraies instructions de l'agent + un tool appelé
Chaque étape s'arrête après 90 s. Utilise le faux serveur (mock_mcp.py) : aucune base de données requise.
"""
import kit  # d'abord

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["WATCHDOG_MCP_SERVER"] = str(HERE / "mock_mcp.py")
os.environ.setdefault("MOCK_SCENARIO", "household")
os.environ.setdefault("MOCK_LOG", str(Path(tempfile.gettempdir()) / "adk_check_calls.jsonl"))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types

from watchdog_agent import model, server_params
from watchdog_instructions import INSTRUCTIONS

TIMEOUT = 60


async def stage(label, model_name, instruction, prompt, with_tools):
    t0 = time.monotonic()
    toolset = McpToolset(connection_params=StdioConnectionParams(server_params=server_params(), timeout=30)) if with_tools else None
    agent = LlmAgent(name="check", model=model(model_name), instruction=instruction, tools=[toolset] if toolset else [])
    runner = InMemoryRunner(agent=agent, app_name="check")
    seen = []
    try:
        async with asyncio.timeout(TIMEOUT):
            session = await runner.session_service.create_session(app_name="check", user_id="u")
            msg = types.Content(role="user", parts=[types.Part(text=prompt)])
            async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=msg):
                for p in (ev.content.parts if ev.content else []) or []:
                    if p.function_call:
                        seen.append(f"tool:{p.function_call.name}@{time.monotonic() - t0:.1f}s")
                    elif p.text and not p.thought and ev.is_final_response():
                        seen.append(f"text@{time.monotonic() - t0:.1f}s")
        print(f"  {label:<28} OK    {time.monotonic() - t0:5.1f}s  {seen}")
        ok = True
    except BaseException as e:  # noqa: BLE001
        ok = False
        while isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        print(f"  {label:<28} ECHEC {time.monotonic() - t0:5.1f}s  {type(e).__name__}: {str(e)[:150]}  vu: {seen}")
    finally:
        for closer in ((toolset.close if toolset else None), runner.close):
            try:
                if closer:
                    await closer()
            except BaseException:  # noqa: BLE001
                pass
    return ok


async def main():
    for name in sys.argv[1:] or [kit.ENV.get("WATCHDOG_MODEL", "gemini-flash-latest")]:
        print(name)
        # On s'arrête à la première étape qui échoue : inutile de refaire attendre 60 s sur les suivantes.
        if not await stage("1. sans tools", name, "Answer in one short sentence.", "Say pong.", False):
            continue
        if not await stage("2. avec tools MCP", name, "You may use the tools. Answer in one short sentence.",
                           "Say pong. Do not call any tool.", True):
            continue
        await stage("3. instructions + 1 tool", name, INSTRUCTIONS,
                    "Day 2026-11-03. Call get_sample_rows once for batch_id 1 (limit 2), then answer in one sentence.", True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        sys.exit(str(e))