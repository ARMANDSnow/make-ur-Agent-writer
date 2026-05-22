<div align="center">

# Continuator

**A multi-agent LLM pipeline for long-form novel continuation, built with engineering discipline.**

[English](README.md) · [简体中文](README.zh.md)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-135_passing-brightgreen.svg)](#status)
[![Iterations](https://img.shields.io/badge/iterations-15_logged-orange.svg)](docs/iterations/)
[![LiteLLM](https://img.shields.io/badge/router-LiteLLM-purple.svg)](https://github.com/BerriAI/litellm)
[![Mock-first](https://img.shields.io/badge/dev-mock_first-success.svg)](#quick-start)

</div>

---

## TL;DR

Read a published novel → build a structured knowledge base → debate the continuation direction with 6 agents → plan N chapters with a strong reasoner → write each chapter with a cheap fast model → 8-reviewer quality gate → measured cost & quality.

**Not** "yet another GPT wrapper." The interesting part is the **engineering scaffold around the LLM**: 15 iterations of mock-first development, real-model validation, preflight guardrails, prompt-cache-aware writer, entity graph for relationship consistency, per-call cost telemetry.

Validated on 《龙族》 (Dragon Raja, by 江南) as test corpus — 5 volumes, 2.3M source characters. Latest measured chapter: **4507 Chinese characters, user-rated 8/10, $0.42 per chapter.**

> The source novel itself is gitignored. This repo ships the engine, not the corpus.

---

## Why this might catch your eye

| Layer | What it looks like in code |
|---|---|
| **Mock-first dev** | 135 unit tests, **runs in 3 seconds** without burning a single token. `tests/__init__.py` force-sets `OPENAI_MODEL=mock` to prevent `.env` leakage. |
| **Preflight guardrails** | 7 categories of FATAL checks before any real-model call: env / context limit / agents config / rolling state / manifest integrity / **provider routing** / manual facts. |
| **Cost telemetry** | Every call logs `request_hash`, prompt/response tokens, cache_read/cache_write tokens. `estimate-cost` aggregates with provider-specific pricing. |
| **Chunked extraction** | Chapters >24k chars split front/middle/end; **all-or-nothing merge** so no half-baked summaries. |
| **Structured debate** | 6 agents × 6 rounds + structured ballot with `position: agree/abstain/reject`. Majority aggregation with tie/multi-reject markers. Empty-ballot fallback path. |
| **Entity graph w/ timeline** | Characters/locations/concepts as entities. Relationships carry `timeline[]` with `active=true` markers. **Writer sees only active state**; a "relationship consistency" reviewer agent verifies. 32 entities / 33 relationships in current test graph. |
| **Style example injection** | User curates 3-5 prose passages from the source author, dropped into writer's prompt cache for voice matching. |
| **Two-tier model architecture** | Planner: Claude Opus (high reasoning, runs once per N chapters). Writer: DeepSeek-V4 (cheap, runs per chapter). LiteLLM routes both. |
| **Iteration log** | [15 entries](docs/iterations/), each with Context / Plan / Acceptance criteria / Measured results / File summary. The repo doubles as an engineering journal. |
| **Snapshot mechanism** | Real-model outputs auto-snapshotted to `outputs/drafts/snapshots/<ts>/` so a subsequent mock run can never overwrite them. |
| **Polish pass** | When the lint + 7 reviewers approve but the chapter is still <3000 Chinese chars, a polish call forcibly expands it. |

---

## Architecture

```mermaid
flowchart LR
    subgraph "Source (gitignored)"
        TXT[raw novel volumes]
    end

    subgraph "Data layer"
        NORM[normalized_texts]
        MANIFEST[chapter_manifest.json]
        EXTRACT[extracted_jsons]
        ROLL[rolling_summaries]
        KB[knowledge_base]
        EG[entity_graph.json]
        FACTS[manual_overrides/<br/>global_facts.json]
        STYLE[style_examples]
    end

    subgraph "Pipeline"
        N[normalize]:::local
        SP[split]:::local
        EX[extract]:::llm
        CP[compress]:::llm
        DB[debate<br/>6 agents × 6 rounds]:::llm
        PL[plan-chapters<br/>Claude Opus]:::strong
        WR[write<br/>+ 8 reviewers + polish]:::llm
        RV[review<br/>standalone re-check]:::llm
    end

    subgraph "Outputs"
        OUT[outputs/drafts<br/>chapter_NN.md + meta.json]
        SNAP[outputs/drafts/snapshots/&lt;ts&gt;/]
        REVIEWS[outputs/reviews]
    end

    TXT --> N --> NORM --> SP --> MANIFEST
    MANIFEST --> EX
    EX --> EXTRACT
    EX --> ROLL
    EXTRACT --> CP --> KB
    KB --> DB
    EG --> DB
    FACTS --> DB
    DB --> PL
    PL --> WR
    KB --> WR
    EG --> WR
    STYLE --> WR
    FACTS --> WR
    ROLL --> WR
    WR --> OUT --> SNAP
    OUT --> RV --> REVIEWS

    classDef local fill:#e8f5e9,stroke:#388e3c,color:#1b5e20
    classDef llm fill:#fff3e0,stroke:#f57c00,color:#bf360c
    classDef strong fill:#e3f2fd,stroke:#1976d2,color:#0d47a1
```

Three execution tiers:

- 🟩 **Local-only** — deterministic file processing, no LLM
- 🟧 **Cheap fast model** (`deepseek/deepseek-v4-pro` etc.) — per-chapter work
- 🟦 **Strong reasoner** (`Claude Opus`) — one-shot planning, called per N-chapter batch

---

## Quick start

### Mock mode — no API key, no network

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
pip install -r requirements.txt
bash scripts/verify.sh
```

`verify.sh` runs:
- 135 unit tests
- normalize → split → extract → compress → debate → write 1 chapter → review
- manifest integrity check
- report snapshot drift check
- cost estimator

All in mock mode, ~30 seconds. Exit code 0 means the entire pipeline is wired correctly.

### Real model mode

```bash
cp .env.example .env
# Edit .env:
#   OPENAI_API_KEY=sk-...
#   OPENAI_BASE_URL=https://api.deepseek.com
#   OPENAI_MODEL=deepseek/deepseek-v4-pro
#
# Optionally for the planner tier (Claude via OpenAI-compatible router):
#   PLANNER_API_KEY=...
#   PLANNER_BASE_URL=...
#   PLANNER_MODEL=openai/claude-opus-4-5

python3 main.py preflight    # 7-category FATAL check; non-zero exit if anything's off
bash scripts/write_smoke.sh  # preflight → compress → debate → write 1 chapter → review → snapshot
```

`scripts/write_smoke.sh` writes one chapter and snapshots all outputs to `outputs/drafts/snapshots/<timestamp>/`. Typical run: 5-15 minutes, $0.30-$0.50 per chapter with DeepSeek-V4.

> **Bring your own source**: put your `.txt` files into `小说txt/` (gitignored). The pipeline auto-detects UTF-16 / GB18030 and normalizes to UTF-8. `init-book` can now generate reviewable proposals for facts, entity graph, continuation anchor, and style examples.

### Quick start for any novel

```bash
python3 main.py normalize
python3 main.py split
python3 main.py init-book --extract-limit 10

# Review and edit proposals under data/proposals/ first.
python3 main.py apply-bootstrap --name global_facts
python3 main.py apply-bootstrap --name global_facts --confirm
python3 main.py apply-bootstrap --name entity_graph
python3 main.py apply-bootstrap --name entity_graph --confirm
python3 main.py apply-bootstrap --name continuation_anchor
python3 main.py apply-bootstrap --name continuation_anchor --confirm
python3 main.py apply-bootstrap --name style_examples
python3 main.py apply-bootstrap --name style_examples --confirm

python3 main.py debate
python3 main.py plan-chapters --chapters 3
# Edit outputs/debate/chapter_plan.json, then:
python3 main.py write --chapters 1 --resume-from 1 --force
python3 main.py review-chapter 1
```

`data/proposals/`, applied style examples, outputs, and logs are gitignored. Style proposals contain only line ranges and short previews; full style excerpts are copied only during explicit `apply-bootstrap --confirm`.

---

## CLI

```bash
python3 main.py <command> [options]
```

| Command | What it does |
|---|---|
| `normalize` | Detect encoding (UTF-16 / GB18030), normalize to UTF-8, save line-number map |
| `split` | Build `chapter_manifest.json` from normalized text. Each entry gets a deterministic `confidence ∈ [0,1]` |
| `extract` | Per-chapter structured extraction. Long chapters auto-chunk; all-or-nothing merge |
| `compress` | Build `knowledge_base/global_knowledge.md` + `knowledge_index.json` |
| `debate` | 6 agents × 6 rounds free-text + structured ballot vote → `outline.md` + `decisions.json` |
| `plan-chapters` | Use Claude Opus to plan N chapter-level outlines → `chapter_plan.json` |
| `write` | Generate chapters under outline + chapter plan. 8 reviewers + lint + polish |
| `review` | Re-run reviewers on existing drafts |
| `retry-failures` | Retry chapters in `data/extraction_failures/` |
| `preflight` | Read-only pre-run check; FATAL exits non-zero |
| `status` | Pipeline state report |
| `check-manifest` | Validate `chapter_manifest.json` integrity |
| `check-reports` | Verify generated Markdown reports are in sync with JSON inputs |
| `manifest-report` | Render manifest as Markdown |
| `review-summary` | Aggregate reviewer verdicts and lint rules |
| `estimate-cost` | Cost report (sums actual logged tokens + chunk estimates) |
| `run-all` | Mock-only end-to-end shortcut |

### Smoke scripts

| Script | Purpose |
|---|---|
| `scripts/verify.sh` | Mock-only sanity (no API calls). Forces `OPENAI_MODEL=mock` and unsets keys, so it always exits 0 on a clean repo |
| `scripts/real_smoke.sh` | preflight → extract 2 chapters → preflight |
| `scripts/debate_smoke.sh` | preflight → debate → estimate-cost → preflight; snapshots to `outputs/debate/snapshots/<ts>/` |
| `scripts/write_smoke.sh` | preflight → compress → debate → write 1 chapter → review → snapshot |
| `scripts/write_book.sh` | Multi-chapter continuation (iter 013+) |

---

## Project layout

```
.
├── src/                          # 26 modules
│   ├── llm_client.py             # LiteLLM wrapper with cache_control, context overflow guard, retry, request_hash
│   ├── preflight.py              # 7 FATAL categories, real-model safety gate
│   ├── extractor.py              # chunked extraction with all-or-nothing merge
│   ├── debater.py                # 6-agent debate + structured ballot with majority/tie/veto
│   ├── plot_planner.py           # Claude Opus chapter-level planner (iter 014)
│   ├── auto_bootstrap.py         # Reviewable bootstrap proposals (iter 015)
│   ├── cli_apply_bootstrap.py    # Dry-run/confirm apply workflow
│   ├── writer.py                 # writer with style/anchor/plan injection + polish pass
│   ├── reviewer.py               # 8 reviewer agents (incl. relationship-consistency)
│   ├── entities.py               # entity graph loader + active-state renderer + tag reverse index
│   ├── linter.py                 # deterministic style lint with thresholds
│   ├── schemas.py                # Pydantic models, single source of truth for shapes
│   └── ...
├── tests/                        # 31 files, 135 tests
├── docs/
│   ├── iterations/               # 15 iteration logs, each a working postmortem
│   ├── stage_01_summary.md       # mock-first foundation
│   ├── stage_02_summary.md       # first real-model validation
│   ├── notes/                    # debugging notes
│   └── AGENT_HANDOFF.md          # session continuity anchor
├── config/
│   ├── agents.yaml               # 6 debate + 8 review agents + writer config
│   ├── models.yaml               # per-task model / temperature / max_tokens / context_limit
│   └── linter.yaml               # lint rules with thresholds
├── prompts/                      # writer / reviewer / debate / extractor system prompts
├── scripts/                      # 5 entry-point shell scripts (see above)
├── main.py                       # CLI dispatch
├── data/                         # gitignored: source texts, derived data, knowledge base
└── outputs/                      # gitignored: drafts, reviews, debate artifacts, snapshots
```

---

## Engineering journal

The repo doubles as a **transparent record of how it got built**. Each iteration is one engineering decision, documented end-to-end.

### Stage 1 — Mock-first foundation (iter 001-005)
[stage_01_summary.md](docs/stage_01_summary.md) · CLI surface, observability, real-model hardening, preflight, splitter confidence.

### Stage 2 — First real-model validation (iter 006-008)
[stage_02_summary.md](docs/stage_02_summary.md) · Provider routing FATAL, debate structured voting, ballot field repair, first true-model `write` smoke.

### Stage 3 — Writing quality axis (iter 009+)
- [009](docs/iterations/iteration_009_writing_quality_surge.md) — Style injection + time anchor + length floor + +1 rewrite
- [010](docs/iterations/iteration_010_polish_and_linter_thresholds.md) — Linter thresholds + polish pass + reviewer-bypass safety
- [011](docs/iterations/iteration_011_entity_graph_and_consistency.md) — **Entity graph + consistency reviewer.** User rated chapter 8/10.
- [012](docs/iterations/iteration_012_reviewer_robustness_and_consistency_strict.md) — Reviewer JSON robustness + debate fallback
- [013](docs/iterations/iteration_013_multi_chapter_architecture.md) — Multi-chapter architecture
- [014](docs/iterations/iteration_014_plot_planner.md) — Claude Opus chapter planner
- [015](docs/iterations/iteration_015_auto_bootstrap.md) — Auto-bootstrap proposals for new novels

Each entry follows the same 8-section template: Context · Plan · Acceptance criteria · Implementation Notes · Acceptance Result · File Summary · Out-of-scope · Notes. Acceptance Result lists **measured numbers**, not promises.

---

## Latest measured results

| Metric | Value | Source |
|---|---|---|
| Test corpus | 5 volumes, 101 chapters, **2,308,674 chars** | `data/chapter_manifest.json` |
| Entity graph | **32 entities, 33 relationships** | `data/entity_graph.json` |
| Generated chapter length | **4,507 Chinese chars** (target 3500-5500) | iter 011 snapshot |
| User quality rating | **8 / 10** | iter 011 P7 verification |
| Real-model calls per chapter | 60 (compress 1 + debate 47 + write 1 + review 11) | `logs/llm_calls.jsonl` |
| DeepSeek-V4 success rate | **60/60 = 100%** | latest smoke |
| Cost per chapter | **~$0.42** | DeepSeek-V4 pricing |
| Unit tests | **135 passing in 2.2s** (mock-only) | `python3 -m unittest discover -s tests` |

---

## Stack

- **Python 3.9+**
- [LiteLLM](https://github.com/BerriAI/litellm) — multi-provider routing (OpenAI, DeepSeek, Anthropic, ...)
- [Pydantic](https://docs.pydantic.dev/) — schema source of truth
- [tiktoken](https://github.com/openai/tiktoken) — token counting (with `cl100k_base` fallback)
- [python-dotenv](https://github.com/theskumar/python-dotenv)

No async, no framework lock-in, no orchestration library. Plain Python + LLM calls + JSON I/O.

---

## Status

✅ **Stage 1** (mock foundation) — done
✅ **Stage 2** (real-model first smoke) — done
🔄 **Stage 3** (writing quality + generalization) — Phase 1 done (8/10 chapter), multi-chapter, plot planner, and auto-bootstrap engineering in progress
⏳ **Stage 4** (productization) — workspace, multilingual splitter, agent persona abstraction

See [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) for the current session continuity anchor.

---

## Scope notes

- This project is a **research-grade engineering exercise**, not a product.
- The source novel (《龙族》) is **not redistributed**. `小说txt/`, `data/`, `outputs/`, `logs/` are all gitignored. The repo ships **code, configs, prompts, docs, and the iteration log** — that's it.
- Generated continuations are derivative works of copyrighted source material and are kept local.
- To use with a different novel: drop your `.txt` files into `小说txt/`, run `init-book`, review the four proposal files under `data/proposals/`, apply them explicitly, then continue with debate → plan → write.

---

<div align="center">

Built with 15 iterations of *measure, then commit*.

</div>
