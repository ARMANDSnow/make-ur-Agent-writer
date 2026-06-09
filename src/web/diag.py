"""iter 048a: model-key connectivity diagnostics for the workbench.

Pure aggregation: enumerate the model configured for each task family,
de-dupe by model name, and probe each distinct model exactly once via
``LLMClient.ping()``. No writes, no side effects on workspace data.

In mock mode (the default, and what ``unittest discover`` forces) every
probe short-circuits with zero network I/O — so this module is safe to
import and call from tests without touching the network.

Triggered only by an explicit user click in the WebUI ("test key"), this
is the diagnostics analogue of ``python main.py preflight``: a single
``max_tokens=1`` request per *distinct* model, and the api_key is never
echoed back to the client (see ``LLMClient.ping``).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..llm_client import LLMClient


# Task families whose configured model the workbench surfaces. Hard-coded
# here (rather than derived from config.py internals) so the diagnostics
# table stays a stable, reviewable surface — adding a task is a deliberate
# edit, not an implicit consequence of a config refactor.
TASKS: List[str] = ["write", "review", "debate", "extract", "compress", "plot_planner"]


def collect_model_diagnostics() -> Dict[str, Any]:
    """Probe each distinct configured model once.

    Returns::

        {
          "is_mock": bool,         # True when every probed model is a mock
          "tasks": {task: model},  # task family -> resolved model name
          "models": [ping result], # one entry per DISTINCT model
          "all_ok": bool,          # True when every probe returned ok
        }

    De-duping by model keeps cost and latency bounded: in mock mode all
    tasks collapse to a single ``mock`` entry (one short-circuited probe);
    in real mode it is typically the main model plus at most a couple of
    task-specific overrides.
    """
    task_models: Dict[str, str] = {}
    clients_by_model: Dict[str, LLMClient] = {}
    for task in TASKS:
        try:
            client = LLMClient(task)
        except Exception as exc:
            # A single broken task config must not sink the whole table.
            task_models[task] = f"<config error: {type(exc).__name__}>"
            continue
        task_models[task] = client.model
        clients_by_model.setdefault(str(client.model), client)

    results: List[Dict[str, Any]] = []
    all_ok = True
    is_mock = True
    for client in clients_by_model.values():
        res = client.ping()
        results.append(res)
        if not res.get("ok"):
            all_ok = False
        if not res.get("mock"):
            is_mock = False

    if not clients_by_model:
        # Every task config errored — nothing was probed.
        all_ok = False
        is_mock = False

    return {
        "is_mock": is_mock,
        "tasks": task_models,
        "models": results,
        "all_ok": all_ok,
    }
