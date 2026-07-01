#!/usr/bin/env bash
# aeloon_sync_check.sh v2 — 个人项目 → Aeloon novel_web 同步判定器
#
# 背景：Aeloon-Pro/novel_web 是本项目 src/integrations/config/prompts 的 vendored 整树
#       副本，本项目是单一真源。aeloon 侧只在少数文件上焊了集成胶水（云 token / 深色
#       模式 / gateway / background 自启 / 模型降级告警）。本脚本用「上次 vendored 的基
#       线 tag」做三方判定，逐文件告诉你该怎么同步，不必让 Claude 在 aeloon 里重写一遍。
#
# 判定（基线 BASE → 你的目标 TARGET，对照 aeloon 现状 ours）：
#   ✅ 已同步     aeloon == 你的 TARGET 版本，无需动作
#   🟢 直接覆盖   你单边改、aeloon 仍=基线，写入 TARGET 版即可（零冲突）
#   🆕 新增复制   TARGET 新增、aeloon 没有，新建并复制
#   🟢 可自动合并 两边都改但三方 merge 无冲突（深色/胶水会被保留）→ 可自动写回
#   🔴 需人工冲突 两边都改且 merge 有冲突，必须人工/Claude 收口
#   🗑️ 建议删除   你删了、aeloon 仍=基线，建议在 aeloon 同步删除（不自动执行）
#   ⚠️ 人工决策   双删分叉 / aeloon 删了你又改 / 你删了 aeloon 又改 等，需人判断
#
# 关键设计：对照的是「你 TARGET ref 的已提交内容」(git show TARGET:f)，不是脏工作区，
#           所以未提交的 WIP（如 iter063）不会混进同步。
#
# 用法:
#   bash scripts/aeloon_sync_check.sh                       # 基线..HEAD，只报告
#   bash scripts/aeloon_sync_check.sh BASE..TARGET          # 指定范围（任意 git ref）
#   bash scripts/aeloon_sync_check.sh --apply               # 自动执行安全桶(覆盖/新增/可自动合并)
#   AELOON_NOVEL_WEB=/path SYNC_BASE=tag SYNC_SCOPE="src" bash scripts/aeloon_sync_check.sh
#
#   --apply 只动「🟢直接覆盖 / 🆕新增复制 / 🟢可自动合并」三个可证明安全的桶；
#           🔴冲突 / 🗑️删除 / ⚠️人工 永远只打印命令，绝不自动执行。
#
# 同步并 PR merge 后：把基线 tag 前移到本次同步的 commit，下次判定才准：
#   git tag -f aeloon-handoff-iterNNN <commit>   # 并把下方 SYNC_BASE 默认值更新
set -euo pipefail

PERSONAL="${PERSONAL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
AELOON="${AELOON_NOVEL_WEB:-/Users/dingyuxuan/Desktop/Aeloon-Pro/novel_web}"
BASE="${SYNC_BASE:-aeloon-handoff-iter062}"   # iter058-062 已同步进 dev/ui (PR #541, 2026-06-23)
TARGET="${SYNC_TARGET:-HEAD}"
SCOPE="${SYNC_SCOPE:-src integrations config prompts}"
APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *..*) BASE="${arg%%..*}"; TARGET="${arg##*..}" ;;
    *) echo "未知参数: $arg（用 --help 看用法）" >&2; exit 2 ;;
  esac
done

_md5() { if command -v md5 >/dev/null 2>&1; then md5 -q "$1"; else md5sum "$1" | cut -d' ' -f1; fi; }
_md5s() { if command -v md5 >/dev/null 2>&1; then md5 -q; else md5sum | cut -d' ' -f1; fi; }

cd "$PERSONAL"
git rev-parse "$BASE"   >/dev/null 2>&1 || { echo "✗ 基线 ref '$BASE' 不存在；先 git tag aeloon-handoff-iterNNN <commit>" >&2; exit 1; }
git rev-parse "$TARGET" >/dev/null 2>&1 || { echo "✗ 目标 ref '$TARGET' 不存在" >&2; exit 1; }
[ -d "$AELOON" ] || { echo "✗ 找不到 aeloon novel_web: $AELOON（用 AELOON_NOVEL_WEB= 指定）" >&2; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
OVERWRITE="$TMP/overwrite"; NEWCOPY="$TMP/newcopy"; AUTOMERGE="$TMP/automerge"
CONFLICT="$TMP/conflict"; DELETE="$TMP/delete"; MANUAL="$TMP/manual"; SYNCED="$TMP/synced"
: > "$OVERWRITE"; : > "$NEWCOPY"; : > "$AUTOMERGE"; : > "$CONFLICT"; : > "$DELETE"; : > "$MANUAL"; : > "$SYNCED"

echo "个人项目: $PERSONAL"
echo "aeloon  : $AELOON"
echo "基线 BASE=$BASE   目标 TARGET=$TARGET($(git rev-parse --short "$TARGET"))   范围 SCOPE=$SCOPE"
if ! git diff --quiet -- $SCOPE 2>/dev/null; then
  echo "注意 : 工作区有未提交改动(WIP)，判定基于已提交的 $TARGET，WIP 不会混入。"
fi
echo
printf '%-34s %s\n' "文件" "判定"
printf '%-34s %s\n' "----------------------------------" "----------"

ex() { git cat-file -e "$1:$2" 2>/dev/null; }   # ref:path 是否存在

while IFS= read -r f; do
  [ -z "$f" ] && continue
  bF=0; tF=0; aF=0
  ex "$BASE" "$f"   && bF=1
  ex "$TARGET" "$f" && tF=1
  [ -e "$AELOON/$f" ] && aF=1
  tsum=""; bsum=""; asum=""
  [ $tF -eq 1 ] && tsum=$(git show "$TARGET:$f" | _md5s)
  [ $bF -eq 1 ] && bsum=$(git show "$BASE:$f"   | _md5s)
  [ $aF -eq 1 ] && asum=$(_md5 "$AELOON/$f")

  verdict=""
  if [ $tF -eq 1 ] && [ $bF -eq 0 ]; then            # 你新增
    if [ $aF -eq 0 ]; then verdict="🆕 新增复制"; echo "$f" >> "$NEWCOPY"
    elif [ "$asum" = "$tsum" ]; then verdict="✅ 已同步"; echo "$f" >> "$SYNCED"
    else verdict="⚠️ 人工决策(双方各自新增且不同)"; echo "$f" >> "$MANUAL"; fi
  elif [ $tF -eq 0 ] && [ $bF -eq 1 ]; then          # 你删除
    if   [ $aF -eq 0 ]; then verdict="✅ 已同步(都已删)"; echo "$f" >> "$SYNCED"
    elif [ "$asum" = "$bsum" ]; then verdict="🗑️ 建议删除"; echo "$f" >> "$DELETE"
    else verdict="⚠️ 人工决策(你删了但 aeloon 改过)"; echo "$f" >> "$MANUAL"; fi
  else                                                # 修改
    if   [ $aF -eq 0 ]; then verdict="⚠️ 人工决策(aeloon 缺此文件，疑被其删)"; echo "$f" >> "$MANUAL"
    elif [ "$asum" = "$tsum" ]; then verdict="✅ 已同步"; echo "$f" >> "$SYNCED"
    elif [ "$asum" = "$bsum" ]; then verdict="🟢 直接覆盖"; echo "$f" >> "$OVERWRITE"
    else
      git show "$BASE:$f"   > "$TMP/b"; git show "$TARGET:$f" > "$TMP/t"; cp "$AELOON/$f" "$TMP/o"
      if git merge-file -p "$TMP/o" "$TMP/b" "$TMP/t" > "$TMP/m" 2>/dev/null; then
        verdict="🟢 可自动合并"; echo "$f" >> "$AUTOMERGE"
      else
        verdict="🔴 需人工冲突($(grep -c '^<<<<<<<' "$TMP/m" 2>/dev/null || echo '?') 处)"; echo "$f" >> "$CONFLICT"
      fi
    fi
  fi
  printf '%-34s %s\n' "$f" "$verdict"
done < <(git diff --name-only "$BASE..$TARGET" -- $SCOPE)

cnt() { wc -l < "$1" | tr -d ' '; }
echo
echo "汇总: 已同步=$(cnt "$SYNCED") 直接覆盖=$(cnt "$OVERWRITE") 新增=$(cnt "$NEWCOPY") 可自动合并=$(cnt "$AUTOMERGE") 需人工冲突=$(cnt "$CONFLICT") 建议删除=$(cnt "$DELETE") 人工决策=$(cnt "$MANUAL")"

emit() {  # $1 标题  $2 文件清单  $3 模式(overwrite/newcopy/automerge/conflict/delete/manual)
  [ -s "$2" ] || return 0
  echo; echo "===== $1 ====="
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$3" in
      overwrite|newcopy)
        echo "mkdir -p \"$(dirname "$AELOON/$f")\" && git show \"$TARGET:$f\" > \"$AELOON/$f\"" ;;
      automerge)
        echo "git show $BASE:$f >/tmp/b && git show $TARGET:$f >/tmp/t && git merge-file -p \"$AELOON/$f\" /tmp/b /tmp/t > /tmp/m && cp /tmp/m \"$AELOON/$f\"   # $f" ;;
      conflict)
        echo "git show $BASE:$f >/tmp/b && git show $TARGET:$f >/tmp/t && git merge-file \"$AELOON/$f\" /tmp/b /tmp/t   # ↑ 收口 $f 的 <<<< 冲突标记(保护深色/云token/gateway/降级)" ;;
      delete)
        echo "rm \"$AELOON/$f\"   # 确认 aeloon 无独立用途再删" ;;
      manual)
        echo "# $f —— 手工核对 base/aeloon/你的 三方差异后决定" ;;
    esac
  done < "$2"
}

emit "🟢 直接覆盖（写入 TARGET 版，零冲突）" "$OVERWRITE" overwrite
emit "🆕 新增复制（新建并写入）"            "$NEWCOPY"  newcopy
emit "🟢 可自动合并（三方无冲突，写回 aeloon）" "$AUTOMERGE" automerge
emit "🔴 需人工冲突（解决冲突标记后再用）"   "$CONFLICT" conflict
emit "🗑️ 建议删除（不自动执行）"            "$DELETE"   delete
emit "⚠️ 人工决策"                          "$MANUAL"   manual

if [ $APPLY -eq 1 ]; then
  echo; echo "===== --apply: 执行安全桶(覆盖/新增/可自动合并) ====="
  while IFS= read -r f; do [ -z "$f" ] && continue; mkdir -p "$(dirname "$AELOON/$f")"; git show "$TARGET:$f" > "$AELOON/$f"; echo "  覆盖/新增 $f"; done < <(cat "$OVERWRITE" "$NEWCOPY")
  while IFS= read -r f; do [ -z "$f" ] && continue; git show "$BASE:$f" > "$TMP/b"; git show "$TARGET:$f" > "$TMP/t"; git merge-file -p "$AELOON/$f" "$TMP/b" "$TMP/t" > "$TMP/m" && cp "$TMP/m" "$AELOON/$f"; echo "  自动合并 $f"; done < "$AUTOMERGE"
  echo "  已跳过 🔴冲突 / 🗑️删除 / ⚠️人工（需你手工处理）"
fi

echo
echo "后续: 同步后在 aeloon 跑 novel_web 测试 → dev/ui 起新分支提 PR → merge 后 git tag -f $BASE 前移到本次 commit。"
