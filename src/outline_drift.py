"""iter057 P1-C: outline 语义漂移检测(确定性 MVP)。

book_driver 现有 outline 守卫(start_point.outline_consistency_failures /
plan_outline_lineage_failures)只校验 **provenance**(起点指纹 / outline_sha256),
发现不了「outline 没变、但实际剧情走远了」这类长程必然漂移。而 writer 把 outline
**逐字注入每章 prompt**(见 book_runner readiness 注释 + writer.py:686),过时 outline
会误导后续承接。

本模块用**确定性信号**——outline 提及的实体锚点在最近 K 章 rolling(实际写出的剧情)的
命中率——暴露漂移,只产出 **warn**(调用方绝不 block)。

⚠ 范围澄清(subagent 审核纠偏):reviewer **不消费 outline**(fidelity 基准是源书原文
风格,非 outline),故漂移的真实危害在 **write-time 喂过时图纸**,不是 review 误拒。完整版
用 LLM 语义判定 + write-time 基准从静态 outline 切到滚动上下文(均需真模型验证,留后续)。
"""

from __future__ import annotations

from typing import Any, Dict, List

# 命中率低于此 → 判定 outline 关注点已被实际剧情甩开。保守取 0.4:本项目铁律是
# 误报会把用户训练成习惯性逃生,故宁可漏报(只是少一条 warn)也不误报。
DRIFT_HIT_RATE_THRESHOLD = 0.4
# 最近多少章 rolling 作为「实际剧情」参照系。
RECENT_K = 10
# 锚点少于此不判定:样本太小,命中率噪声大,易误报。
MIN_ANCHORS = 3


def _anchor_terms(entity_graph: Dict[str, Any]) -> List[str]:
    """实体名 + 别名,作为 outline↔剧情比对的候选锚点词。"""
    terms: List[str] = []
    for ent in entity_graph.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or "").strip()
        if name:
            terms.append(name)
        for alias in ent.get("aliases", []) or []:
            alias = str(alias).strip()
            if alias:
                terms.append(alias)
    return terms


def _recent_rolling_text(rolling: Dict[str, Any], recent_k: int) -> str:
    """最近 recent_k 章的 summary + key_events + ending_state 拼成「实际剧情」文本。"""
    chapters = sorted(
        (c for c in rolling.get("chapters", []) or [] if isinstance(c, dict)),
        key=lambda c: int(c.get("chapter_no", 0)),
    )
    parts: List[str] = []
    for ch in chapters[-recent_k:]:
        parts.append(str(ch.get("summary") or ""))
        parts.extend(str(e) for e in ch.get("key_events", []) or [])
        parts.append(str(ch.get("ending_state") or ""))
    return "\n".join(parts)


def outline_drift_codes(
    outline_text: str | None,
    rolling: Dict[str, Any],
    entity_graph: Dict[str, Any],
    *,
    recent_k: int = RECENT_K,
    threshold: float = DRIFT_HIT_RATE_THRESHOLD,
    min_anchors: int = MIN_ANCHORS,
) -> List[str]:
    """确定性 outline↔实际剧情漂移信号。返回 warn code 列表(空 = 无漂移 / 数据不足)。

    锚点 = outline 提及的实体名/别名(outline 关心的角色/势力);命中 = 锚点在最近 recent_k
    章 rolling(实际写出的剧情)中出现。命中率 < threshold → 剧情已甩开 outline 关注点。
    只产出 warn,**调用方绝不 block**(漏报优于误报)。锚点不足 / 无剧情则不判定。"""
    if not outline_text:
        return []
    candidates = {t for t in _anchor_terms(entity_graph) if len(t) >= 2}
    anchors = sorted(t for t in candidates if t in outline_text)
    if len(anchors) < min_anchors:
        return []  # 锚点太少,不判定(避免小样本噪声误报)
    recent_text = _recent_rolling_text(rolling, recent_k)
    if not recent_text.strip():
        return []  # 还没写出剧情,无从比对
    hits = [a for a in anchors if a in recent_text]
    hit_rate = len(hits) / len(anchors)
    if hit_rate >= threshold:
        return []
    missing = [a for a in anchors if a not in recent_text][:5]
    pct = int(round(hit_rate * 100))
    return [f"semantic_drift:hit{pct}pct:missing={'/'.join(missing)}"]
