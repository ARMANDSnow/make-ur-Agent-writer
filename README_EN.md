# Continuator

Read in a published novel, pull out its settings and characters, then keep writing it with a group of LLM agents. Continuation, planning, and review go to different models, and the whole pipeline runs locally.

English · [简体中文](README.md)

The source corpus stays out of the repo. `小说txt/`, `data/`, `outputs/`, and `logs/` are all in `.gitignore` — only the engine lives here.

## What it does

A continuation run roughly goes:

normalize the source → split into chapters → extract entities and settings → compress into a knowledge base → a few agents debate the direction → a strong model plans the next N chapters → a cheap model writes each chapter → a reviewer panel plus a linter gate it → write to disk.

The CLI entry points are `write-readiness` and `write-book`. There is also a local web UI (`main.py web`) that puts the same flow in the browser.

Books it has run on include Dragon Raja, A Song of Ice and Fire, and original novels. Current acceptance evidence and the distinction between implemented and real-model-validated paths live in [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md).

## A few design choices

- Development defaults to mock. The full unit suite runs without spending tokens; `tests/__init__.py` force-sets `OPENAI_MODEL=mock` so a stray `.env` cannot leak into tests. The current count is kept in the handoff rather than duplicated here.
- Real-model runs go through preflight first. A few categories of FATAL checks — env, context limit, provider routing, manifest integrity — must pass before anything runs.
- One workspace per book (`workspaces/<name>/`), switched with `--book`; books never share data.
- Chinese/English chapter splitting is auto-detected; EPUB is converted to txt with the standard library (`zipfile + xml.etree + html.parser`), no new dependencies.
- The reviewer is fail-closed: a JSON parse failure is recorded as Abstain rather than a silent approve; a single substantive Reject from any reviewer fails the chapter.
- Every LLM call logs tokens and cost; `estimate-cost` aggregates by provider pricing.

## Quick start

Mock mode needs no key and makes no billable model-provider calls. LiteLLM may refresh its public model-cost map during import and falls back to a bundled local copy on failure:

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
pip install -r requirements.txt
bash scripts/verify.sh
```

`verify.sh` runs the full unit suite plus one mock pipeline; exit 0 means it's installed correctly.

Real-model mode uses `.env`:

```bash
cp .env.example .env
# OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
# for a separate planner model, set PLANNER_*; otherwise it follows OPENAI_*
python3 main.py preflight
```

A non-zero preflight exit means don't run the real model yet.

## Onboarding a new book

```bash
# create a workspace and drop the txt or epub in
python3 main.py workspace-init myBook
cp ~/your-novel.txt workspaces/myBook/小说txt/
# epub goes through the stdlib extractor:
# python3 main.py --book myBook epub-import --src ~/novel.epub --out myBook.txt

# normalize and split; language is auto-detected
python3 main.py --book myBook normalize
python3 main.py --book myBook split

# extract settings, generate 5 kinds of proposal, confirm after a human review
python3 main.py --book myBook init-book --extract-limit 10
for name in global_facts entity_graph continuation_anchor style_examples personas; do
  python3 main.py --book myBook apply-bootstrap --name $name --confirm
done

# set the start point, debate, plan
python3 main.py --book myBook set-start-point <chapter_id_or_volume_id>
python3 main.py --book myBook debate
python3 main.py --book myBook plan-chapters --chapters 3 --force --require-start-point

# write
python3 main.py --book myBook write-readiness --chapters 3
bash scripts/write_book.sh --book myBook --chapters 3
```

Common `write-book` flags: `--max-retries`, `--budget-cny`, `--tier low|mid|high`, `--no-auto-advance`, `--replan-every`. Exit codes: 0 all chapters approved, 3 budget exceeded, 4 blocked.

Switch books by changing `--book`, or `export WORKSPACE_NAME=otherBook` once per shell. `workspace-list` and `workspace-show` list the existing ones.

## Web UI

If switching state in the CLI gets tedious, start a local web server:

```bash
python3 main.py web              # 127.0.0.1:8765 by default
python3 main.py web --port 9999  # custom port
```

The home page is an overview of every workspace: start point, plan, drafts, recent jobs. Inside a book you can:

- set the continuation start point (by chapter or volume)
- generate or regenerate the chapter plan
- read blockers and recommended commands
- start `write-book` after setting chapters, budget, tier, retries, and so on
- view read-only drafts, reviews, manifest, status, cost
- upload a new book through the onboarding wizard, with cooperative cancel mid-run
- soft-delete an unwanted workspace into the trash, behind a confirmation

On mobile the sidebar collapses into a drawer and wide tables scroll horizontally.

Standard library only (`http.server` + `string.Template` + vanilla JS), no front-end dependencies, bound to `127.0.0.1` by default. To just look at the UI without spending money, override `OPENAI_MODEL=mock` at startup. If the port is taken, use another one or `lsof -ti tcp:8765 | xargs kill` first.

## Directory layout

One workspace per book:

```text
workspaces/<book>/
  小说txt/                 raw txt / epub-converted text, not committed
  data/
    normalized_texts/      normalize output
    extracted_jsons/       extract output
    knowledge_base/        compress output
    manual_overrides/      confirmed settings / characters / start point
    proposals/             init-book output, awaiting human confirm
    chapter_manifest.json  chapter index
  outputs/
    debate/                debate, chapter_plan.json, outline
    drafts/                chapter_NN.md, meta, failure, snapshot
    reviews/               chapter_NN.review.json
  logs/
    llm_calls.jsonl        calls, tokens, cost
    web_jobs.jsonl         web job history
```

Only `src/`, `config/`, `scripts/`, `tests/`, and `docs/` are committed. Each book's `小说txt/`, `data/`, `outputs/`, and `logs/` are not. The repo-root `data/`, `outputs/`, and `logs/` are legacy and verify-mock paths, also untracked.

Don't edit the source text in `小说txt/` directly; to change settings, relationships, or style samples, edit `data/manual_overrides/` or regenerate a proposal. Old drafts don't need manual cleanup — the runner archives stale files on `--force` or retry.

## CLI reference

| Command | What it does |
|---|---|
| `workspace-{init,list,show,import-current}` | Multi-workspace management (iter 017) |
| `epub-import` | EPUB → UTF-8 txt, stdlib only (iter 018) |
| `normalize` / `split` | Auto-detect encoding and language; split produces `chapter_manifest.json` |
| `init-book` | Produce 5 kinds of proposal at once (entity_graph / facts / anchor / style / personas) |
| `apply-bootstrap --name X --confirm` | Commit a reviewed proposal |
| `debate` | 6 agents × 6 rounds plus a structured ballot → outline.md + decisions.json |
| `plan-chapters --chapters N` | One-shot N-chapter plan from the strong model (iter 014) |
| `write --chapters N --resume-from i --force` | Multi-chapter generation + 5+1 reviewers + lint + polish |
| `review-chapter <i>` / `chapter-status <i>` | Standalone re-review / single-chapter status JSON (iter 019) |
| `apply-advance --chapter i --auto-apply --confirm` | entity advance (iter 019) |
| `preflight` / `status` / `estimate-cost` | Guard / status / cost summary |

## Project status

| Milestone | Iterations | Status |
|---|---|---|
| Mock foundation and first real-model chain | 001-008 | Done |
| Writing quality, multi-chapter, generalized workspaces | 009-019 | Done |
| Start-point safety, production runner, local Web beta | 020-050 | Done |
| Real-model quality and long-run reliability | 051-079 | Engineering complete; novel capstone pending authorization |
| Drama core and quantitative style loop | 080-087 | Done |
| Drama delivery and real-media safety entry points | 088-092 | Engineering complete; real multimodal calibration pending staged authorization |

The Chinese [README.md](README.md) carries the living SOP table. The compact current snapshot is [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md); per-iteration evidence is indexed under [`docs/iterations/`](docs/iterations/README.md).

Milestone history and durable lessons: [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md).

## Notes

- This is a research-grade engineering exercise, not a product.
- The source novels are not redistributed: `小说txt/`, `workspaces/*/小说txt/`, `data/`, `outputs/`, and `logs/` are all gitignored. The repo ships code, configs, prompts, docs, and the iteration log.
- Generated continuations are derivative works of the source and stay local.
- Any novel works the same way: drop in a `.txt` or `.epub`, run `init-book`, and the rest of the pipeline is identical.

## Stack

- Python 3.9+
- [LiteLLM](https://github.com/BerriAI/litellm), multi-provider routing
- [Pydantic](https://docs.pydantic.dev/), single source of truth for schemas
- [tiktoken](https://github.com/openai/tiktoken), token counting (falls back to `cl100k_base`)
- [python-dotenv](https://github.com/theskumar/python-dotenv)

No async, no web framework, no orchestration library. The web dashboard is standard-library `http.server` too — plain Python + LLM + JSON I/O.
