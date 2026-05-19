#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CHAPTERS="${1:-2}"
mkdir -p logs outputs/drafts/snapshots
ts="$(date +%Y%m%d_%H%M%S)"
log_path="logs/write_book_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

{
  for i in $(seq 1 "$CHAPTERS"); do
    chapter_path=$(printf "outputs/drafts/chapter_%02d.md" "$i")
    if [ -f "$chapter_path" ]; then
      echo "Chapter $i already exists, skipping: $chapter_path"
      continue
    fi

    python3 main.py preflight
    python3 main.py write --chapters 1 --resume-from "$i" --force
    python3 main.py review-chapter "$i"
    python3 main.py status

    if [ "$i" -lt "$CHAPTERS" ]; then
      proposal_path=$(printf "outputs/drafts/chapter_%02d.entity_advance_proposals.json" "$i")
      echo ""
      echo "=== Chapter $i done. Check $proposal_path ==="
      echo "=== Dry run: python3 main.py apply-advance --chapter $i --proposal-idx <comma-list> ==="
      echo "=== Apply:   python3 main.py apply-advance --chapter $i --proposal-idx <comma-list> --confirm ==="
      echo "=== Then re-run: bash scripts/write_book.sh $CHAPTERS to continue ==="
      echo "Write book log written: $log_path"
      exit 0
    fi
  done

  snap="outputs/drafts/snapshots/${ts}"
  mkdir -p "$snap"
  cp outputs/drafts/chapter_*.md "$snap/" 2>/dev/null || true
  cp outputs/drafts/chapter_*.meta.json "$snap/" 2>/dev/null || true
  cp outputs/drafts/chapter_*.entity_advance_proposals.json "$snap/" 2>/dev/null || true
  cp outputs/drafts/rolling_chapter_summary.json "$snap/" 2>/dev/null || true
  cp -r outputs/reviews "$snap/" 2>/dev/null || true
  cp outputs/debate/decisions.json "$snap/debate_decisions.json" 2>/dev/null || true
  cp outputs/debate/outline.md "$snap/debate_outline.md" 2>/dev/null || true
  echo "Snapshot saved: $snap"
  echo "Write book log written: $log_path"
} 2>&1 | tee "$log_path"
