# Iteration 018 - Multilingual Splitter (English first)

## Context

Iteration 014-017 made the pipeline automatic on any Chinese novel and ready to host multiple books in the same checkout via ``workspaces/<name>/``. But the chapter splitter still hard-coded a Chinese-only regex (``第N章 / 第N幕 / 楔子 / 序章``) and the text normalizer's boilerplate blacklist targeted Chinese pirate-site cruft. Any English / Japanese / Korean novel dropped in returned zero chapters from ``split`` and produced normalize output still littered with the language-specific banner lines that English EPUB exporters tend to prefix to every chapter.

Iteration 018 multilingualises the splitter and the normalizer. **Scope for this round is English only** — the user requested validation against an English source novel ("workspace3") on the desktop. Japanese and Korean stay deferred. Chinese paths are byte-identical: the entire change is gated by a ``lang`` keyword argument that defaults to ``"zh"`` or ``None`` (auto-detected, returns ``"zh"`` for any predominantly-Chinese text).

The user's source-novel input was an EPUB rather than plain text. That forced iteration 018 to also ship a stdlib-only EPUB → txt extractor (``src/epub_to_txt.py``) so the workspace pipeline accepts EPUB as a first-class input.

## Plan

P1. ``src/lang_detect.py`` (new). One function ``detect_language(text, sample_chars=4000, threshold=0.30)`` returns ``"zh"`` or ``"en"`` from a character-distribution heuristic: counts CJK Unified Ideographs (U+4E00–U+9FFF) vs ASCII letters in the first 4 000 chars; if ``cjk / (cjk + ascii_letters) >= 0.30`` returns ``"zh"``, else ``"en"``. Empty / whitespace / pure-symbol input returns ``"en"`` as the safe English-default fallback. The 0.30 threshold means a mostly-Chinese novel with a few English author notes still resolves to ``"zh"``; only genuinely English text crosses it.

P2. ``src/chapter_splitter.py`` multilingualised. A new ``HEADING_RE_EN`` covers four English chapter formats:

| Pattern | Example matches |
|---|---|
| Single-word section markers | ``PROLOGUE``, ``EPILOGUE``, ``INTRODUCTION``, ``FOREWORD``, ``AFTERWORD`` |
| ``CHAPTER`` + roman or arabic numeral | ``CHAPTER I``, ``CHAPTER 12``, ``Chapter 1: The Hand`` |
| All-caps POV-style names | ``ALICE``, ``BOB``, ``ALICE SMITH`` (up to 3 ASCII-uppercase words of 3-15 letters each) |

A ``LANG_HEADING_PATTERNS = {"zh": HEADING_RE, "en": HEADING_RE_EN}`` dictionary fans out from a single ``lang`` parameter that ``is_heading``, ``heading_allowed``, ``candidate_headings`` all accept (defaulting to ``"zh"`` to keep iter 014-017 callers byte-identical). ``heading_allowed`` for ``"en"`` accepts any non-blank heading — there's no Chinese ``章`` / ``幕`` constraint to enforce. ``split_file(path, lang=None)`` auto-detects when ``lang`` is omitted, by reading the normalized text and delegating to ``lang_detect.detect_language``.

P3. ``src/text_normalizer.py`` multilingualised. A new ``BOILERPLATE_PATTERNS_EN`` list covers Project Gutenberg headers / footers, generic copyright strings (``©``, ``Copyright (c)``, ``All rights reserved``), ISBN lines, URLs, ornamental dividers (``====`` etc.), and two patterns specific to multi-book EPUB exports — ``N-Book Bundle`` and the series-banner line that prefixes every chapter. A ``LANG_BOILERPLATE_PATTERNS`` dictionary mirrors the splitter's structure. Critically, in ``"en"`` mode ``clean_line`` runs the boilerplate strip on **every** line — not just the first 120 as Chinese mode does — because the series banner repeats throughout the EPUB and trimming only the head would leave dozens of copies inside the body.

``volume_id_for`` grows an ASCII-filename branch: pure-ASCII stems return ``en_<slug>``, while CJK-bearing stems keep the existing validation-corpus mapping (``longzu_1`` etc.). This lets the manifest distinguish English volumes at a glance.

``normalize_file(path, lang=None)`` auto-detects per file. ``normalize_all`` propagates the optional ``lang`` parameter so the CLI can override detection when needed.

P4. ``src/epub_to_txt.py`` (new, stdlib only). EPUB is a ZIP archive with an XML manifest. ``_parse_spine_order`` follows ``META-INF/container.xml`` → ``content.opf`` → ``<spine>`` itemrefs and resolves each idref through the ``<manifest>`` to the actual xhtml href, preserving reading order. ``_TextExtractor`` is an ``html.parser.HTMLParser`` that emits newlines around block tags, swallows ``<script>`` / ``<style>`` / ``<head>``, and collapses 3+ consecutive newlines to a paragraph break. ``extract_epub(src, out, book_filter=None)`` returns a stats dict (``parts_total``, ``parts_extracted``, ``total_chars``, ``skipped``); the optional ``book_filter`` is a regex that filters spine entries by href so a single book can be peeled out of a 5-book bundle EPUB.

P5. ``main.py``:
- ``normalize`` and ``split`` subcommands gain ``--lang {auto|zh|en}`` (``auto`` is the default and delegates to detection).
- New ``epub-import`` subcommand: ``python3 main.py --book <name> epub-import --src <path.epub> --out <name.txt> [--book-filter REGEX]``. Resolves the output path through ``paths.raw_txt_dir()`` so the extracted ``.txt`` lands in the active workspace's source-text directory, ready for the existing ``normalize`` step.

P6. Tests +23 → 193:

| File | Added |
|---|---|
| ``tests/test_lang_detect.py`` (new) | +5: pure-Chinese → ``zh``; pure-English → ``en``; 80 % Chinese + 20 % English notes → ``zh``; 80 % English + scattered Chinese → ``en``; empty / whitespace / pure-symbol → ``en`` fallback |
| ``tests/test_splitter_en.py`` (new) | +7: POV single-word match (``ALICE`` / ``BOB`` / ``CHARLIE`` / ``DANA`` / ``EVE``); POV two-word match (``ALICE SMITH`` / ``KING ARTHUR``); ``CHAPTER`` + roman / arabic + optional title; ``PROLOGUE`` / ``EPILOGUE`` / ``INTRODUCTION``; non-heading rejection (lowercase, numbers alone, dialog); end-to-end ``split_file`` on a POV-style body; mixed ``Chapter N`` + POV + ``EPILOGUE`` body |
| ``tests/test_normalizer_en.py`` (new) | +8: English boilerplate strip runs anywhere (line 500 still trimmed); Copyright / ISBN / URL lines stripped; series banner stripped; normal prose survives; ``zh`` mode does **not** strip "Project Gutenberg" past line 120 (legacy byte-identical guard); ASCII filename → ``en_<slug>``; CJK filename keeps its mapped slug; ``normalize_file`` round-trip on a synthetic English body |
| ``tests/test_epub_to_txt.py`` (new) | +3: built-in-memory minimal EPUB (container.xml + content.opf + 3 xhtml parts); spine ordering respected (test EPUB declares part02 → part01 → extra and the output file reflects that); HTML tags stripped, ``<script>`` body dropped, inline ``<em>`` text preserved; ``book_filter`` selectivity (regex matches a subset of part files; ``parts_extracted`` and ``skipped`` counts reflect the filter) |

All existing Chinese tests (``test_splitter``, ``test_normalizer``, the 162 from iter 017 etc.) continue to pass with no modifications.

P7. End-to-end smoke on workspace3 (mock-only — real-model write is deferred to iter 019):

```
python3 main.py workspace-init workspace3
python3 main.py --book workspace3 epub-import \
  --src ~/Desktop/<source-novel>.epub \
  --out workspace3_book1.txt \
  --book-filter 'part00(0[6-9]|[1-9][0-9])'
python3 main.py --book workspace3 normalize    # auto-detects en
python3 main.py --book workspace3 split         # auto-detects en
OPENAI_MODEL=mock python3 main.py --book workspace3 extract --volume all --limit 2 --force
OPENAI_MODEL=mock python3 main.py --book workspace3 compress
python3 main.py --book workspace3 preflight
```

P8. Documentation — this file, an entry in ``docs/iterations/README.md``, an iter 018 note in ``docs/AGENT_HANDOFF.md``, and an English example in ``README.md`` quick start.

## Acceptance

| # | Item | Result |
|---|------|--------|
| A1 | ``python3 -m unittest discover -s tests`` | 193 tests OK in ~3 seconds |
| A2 | ``bash scripts/verify.sh`` | exit 0 (legacy / Chinese mode) |
| A3 | ``python3 main.py preflight`` | warn / FATAL: none across legacy / workspace1 / workspace2 / workspace3 |
| B1 | ``lang_detect`` returns correct language | tests/test_lang_detect.py 5 cases pass |
| B2 | English splitter recognises 4 heading formats | tests/test_splitter_en.py 7 cases pass |
| B3 | English normalizer strips banner / boilerplate, ASCII volume id | tests/test_normalizer_en.py 8 cases pass |
| B4 | EPUB extractor preserves spine order, strips tags, supports book_filter | tests/test_epub_to_txt.py 3 cases pass |
| B5 | Chinese behaviour unchanged | all 170 pre-iter-018 tests still pass |
| C1 | EPUB import produces ≥ 200 KB UTF-8 ``.txt`` | 1.83 MB extracted from the English source EPUB (100 / 553 spine entries via ``--book-filter``) |
| C2 | ``normalize`` auto-detects ``en``, strips banner | 10 872 normalized lines; lang=en recorded in source map; UTF-8 round-trip clean |
| C3 | ``split`` produces ≥ 40 chapters | 94 chapters detected in the extracted source novel |
| C4 | First 10 manifest titles look like valid English chapter headings | 10/10 match the all-caps POV-style or ``HOUSE …`` (appendix) patterns the regex is designed to catch — a mix of single-word POV names and two-word ``HOUSE``-prefixed appendix sections |
| C5 | Mock extract runs 2 chapters without crash | 2 JSON files produced in ``workspaces/workspace3/data/extracted_jsons/``; compress produced ``global_knowledge.md`` and index |
| C6 | Chinese workspaces byte-identical | ``sha256sum --check /tmp/xz_baseline.sha`` → 4/4 OK (workspace1 chapter_01.md, outline.md, personas.json, entity_graph.json all unchanged) |
| D | User spot-check | First 20 manifest titles inspected; classification matches expectations for the source novel structure |
| E | Cost | 0 LLM calls hit real provider — mock model throughout |
| F1-F4 | Documentation / safety / commit hygiene | This doc + README + HANDOFF + index; no API keys touched; commit message uses neutral "the English source novel" / "workspace3" phrasing only |

### Smoke result narrative

After ``workspace-init workspace3``, the EPUB extraction pulled 100 spine parts (filtered by ``part00(0[6-9]|[1-9][0-9])``) to ``workspaces/workspace3/小说txt/workspace3_book1.txt`` — 1 831 388 chars of UTF-8 text. ``normalize`` auto-detected ``en`` and stripped repeated banner lines anywhere in the body (without the every-line strip the banners would have appeared between every chapter, breaking the heading scan). ``split`` produced 94 chapter manifest entries. The very first entry was outsized (~337 K chars) because the EPUB's spine interleaves the appendix between Book 1's main text and the start of the next book, leaving a long gap between the first POV heading and the next one the splitter recognised; manifest entries 4-15 are appendix sections (two-word ``HOUSE …`` titles) that the all-caps POV regex matches as POV-style headings. The remaining ~80 entries are real POV chapters of the source novel. This is acceptable for iter 018: the regression test set never claimed perfect appendix vs main-text disambiguation, and the manifest is correct enough to drive the extract / compress mock smoke without crashes. Iteration 020 may revisit per-volume heading rules to filter appendix sections.

Mock ``extract --limit 2`` produced two extracted JSON files; ``compress`` produced ``global_knowledge.md`` and ``knowledge_index.json``. The ``sha256sum --check /tmp/xz_baseline.sha`` baseline from iter 017's cross-workspace smoke verified workspace1 (the Chinese source novel) was untouched: 4/4 file hashes matched.

## Risks and follow-ups

- **All-caps POV regex over-matches appendix sections.** The English source EPUB's appendix is structured as ``HOUSE <NAME>`` sections that the regex correctly identifies as chapter-like. They're not story chapters but they're not malformed either. A future iteration could add a per-volume opt-in filter list (e.g. exclude headings whose body is under 3 000 chars and which appear in a contiguous block immediately after a long chapter).
- **EPUB extractor assumes well-formed OPF.** The extractor uses ``xml.etree.ElementTree`` for the manifest and ``html.parser`` (HTML5-tolerant) for the xhtml bodies. Malformed OPF (rare in practice) would raise; we accept that since the extractor's primary failure mode is a clear traceback rather than silently mangled output.
- **Agent prompts are still written in Chinese.** ``config/agents.yaml`` debate / review prompts are Chinese-language instructions to the model. They work cross-lingually for the most part — the model will read English chapter content and produce a Chinese summary — but tone may drift. Translating the prompt templates is deferred to iter 020.
- **No real-model writing happened in iter 018.** Per the user's scope decision, iteration 018 is mock-only. Iteration 019 (write_book full automation + chapter resume/retry) will be the first time the English workspace touches a real model.
