"""iter 026: 9-step SOP orchestration shared by CLI and WebUI.

This module is the single source of truth for "run the whole pipeline from
a raw novel txt all the way to ``chapter_01.md``". The same function is
called by both:

* ``main.py auto-pipeline`` — a CLI one-liner that ``verify.sh`` upgrades
  to in place of the legacy ``run-all`` smoke (which skips bootstrap-apply
  and plan-chapters).
* ``src/web/jobs.py`` — the WebUI background worker invoked by the
  onboarding wizard. The wizard does NOT re-implement step sequencing in
  JS; it uploads the source file and then polls a single job whose worker
  runs ``run_auto_pipeline``.

Keeping the orchestration here (instead of duplicating it in the wizard)
prevents the CLI / GUI from drifting on step ordering, default arguments,
or what counts as a successful step.

Mock-only acceptance: every step ultimately calls into LLM-using modules
that already honor ``OPENAI_MODEL=mock``; the orchestrator itself does no
LLM calls.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .auto_bootstrap import bootstrap_all
from .chapter_splitter import split_all
from .cli_apply_bootstrap import apply_bootstrap
from .compressor import compress_all
from .debater import run_debate
from .extractor import extract_all
from .plot_planner import generate_chapter_plan
from .text_normalizer import normalize_all
from .writer import write_chapters


# Step labels are part of the public API: the WebUI's progress bar shows
# these to the user and tests assert progress_cb is called with these
# exact strings in this exact order. Reorder = breaking change.
STEPS = (
    "normalize",
    "split",
    "extract",
    "compress",
    "bootstrap",
    "apply-bootstrap",
    "debate",
    "plan-chapters",
    "write",
)


ProgressCallback = Callable[[str, float], None]


def run_auto_pipeline(
    *,
    target_chapters: int = 1,
    progress_cb: Optional[ProgressCallback] = None,
    skip_extract: bool = False,
    extract_limit: Optional[int] = 5,
    force: bool = False,
    plan_chapters_target: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the 9-step SOP end-to-end against the active workspace.

    The active workspace is resolved by ``src.paths.workspace_name()``,
    which reads ``WORKSPACE_NAME`` (or ``BOOK``) from the environment.
    The WebUI sets this via ``src.web.workspace_ctx.use_workspace``; the
    CLI honors ``--book`` via ``main._consume_book_pre_arg``.

    Args:
        target_chapters: How many chapters ``write_chapters`` should
            produce. Defaults to 1 because the wizard's first run only
            needs to prove ch1 lands; users grow the corpus afterward
            via ``write_book.sh``.
        progress_cb: Optional callback ``(step_label, fraction)`` invoked
            once per step boundary BEFORE the step runs. ``fraction`` is
            ``step_index / len(STEPS)`` so the UI can render a 9-segment
            progress bar. After the final step a sentinel call
            ``("done", 1.0)`` fires so consumers don't need a "did the
            last step finish" guard.
        skip_extract: When True, skip the extract step. Useful for tests
            that pre-seed ``data/extracted_jsons/`` or for re-runs after
            a partial failure.
        extract_limit: Per-call cap forwarded to ``extract_all``. None =
            no cap. Defaults to 5 to keep onboarding cheap in mock mode.
        force: Forwarded to extract / bootstrap / write where supported.
        plan_chapters_target: Override the chapter_plan size. None lets
            the planner use its built-in default (typically 5+ for usable
            outline depth). If you set this below ``target_chapters`` the
            writer may run out of plan entries.

    Returns:
        A dict keyed by step label whose values are each step's native
        return type (e.g. ``normalize`` returns the manifest list,
        ``apply-bootstrap`` returns a dict of per-proposal apply results).
        On exception the partial dict is NOT returned — the exception
        propagates and the caller decides how to surface it.
    """

    total = len(STEPS)
    results: Dict[str, Any] = {}

    def _notify(step: str, index: int) -> None:
        if progress_cb is not None:
            progress_cb(step, index / total)

    _notify("normalize", 0)
    results["normalize"] = normalize_all()

    _notify("split", 1)
    results["split"] = split_all()

    _notify("extract", 2)
    if skip_extract:
        results["extract"] = {"skipped": True}
    else:
        results["extract"] = extract_all(
            volume="all", limit=extract_limit, force=force
        )

    _notify("compress", 3)
    results["compress"] = compress_all()

    _notify("bootstrap", 4)
    proposals = bootstrap_all(force=force)
    results["bootstrap"] = proposals

    # ``bootstrap_all`` returns a dict whose keys are exactly the proposal
    # names ``apply_bootstrap`` knows how to consume. Iterating the keys
    # keeps the two in sync — if bootstrap_all ever adds a proposal we'd
    # apply it automatically without code change here.
    #
    # Per-proposal try/except: in mock mode the LLM returns canned data
    # that may reference non-existent files (e.g. style_examples points
    # ``source_file`` at ``data/normalized_texts/mock.txt`` regardless of
    # what's actually on disk). In real mode a single proposal whose
    # schema is malformed also shouldn't kill the whole onboarding —
    # the writer can fall back to generic style guidance.
    #
    # Iter 026 code-review #4: catch only the failure modes a proposal
    # legitimately exhibits (missing source file / malformed payload).
    # PermissionError, KeyError, MemoryError, ImportError, etc. signal
    # a real environment problem and must propagate so the user sees a
    # trace_id that points to the root cause instead of cascading
    # 'apply_failed' → opaque downstream failure 3 steps later.
    _notify("apply-bootstrap", 5)
    applied: Dict[str, Any] = {}
    for name in proposals.keys():
        try:
            applied[name] = apply_bootstrap(name, confirm=True)
        except (FileNotFoundError, ValueError) as exc:
            # ``json.JSONDecodeError`` is a ``ValueError`` subclass, so
            # corrupt-proposal-file failures also land here.
            applied[name] = {
                "name": name,
                "status": "apply_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
    results["apply-bootstrap"] = applied

    _notify("debate", 6)
    results["debate"] = run_debate()

    _notify("plan-chapters", 7)
    plan_target = plan_chapters_target
    if plan_target is None:
        # Ensure the plan is at least as long as what we're about to
        # write — writer needs chapter_plan[i] for chapter i.
        plan_target = max(target_chapters, 5)
    results["plan-chapters"] = generate_chapter_plan(
        target_chapters=plan_target, force=force
    )

    _notify("write", 8)
    results["write"] = write_chapters(chapters=target_chapters, force=force)

    if progress_cb is not None:
        progress_cb("done", 1.0)
    return results
