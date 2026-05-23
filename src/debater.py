from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .config import ROOT, load_config
from .continuation_anchor import load_continuation_anchor
from .entities import load_entity_graph, render_active_state
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .persona_loader import load_personas, render_agent_fields
from .schemas import DebateDecisions, model_to_dict
from .state import log_event, write_text_atomic
from .style import load_style_examples
from .utils import ensure_dir, extract_json_object, read_json, write_json


DEBATE_DIR = ROOT / "outputs" / "debate"
KB_PATH = ROOT / "data" / "knowledge_base" / "global_knowledge.md"
INDEX_PATH = ROOT / "data" / "knowledge_base" / "knowledge_index.json"

ROUNDS = [
    "立场陈述",
    "补充约束",
    "互相质询",
    "修正方案",
    "打分",
    "共识收敛",
]


class AgentVoteBallotItem(BaseModel):
    question_index: int
    position: Literal["agree", "abstain", "reject"]
    reason: str = ""


class AgentVoteBallot(BaseModel):
    ballots: List[AgentVoteBallotItem] = Field(default_factory=list)


def load_agents() -> List[Dict[str, Any]]:
    cfg = load_config("agents.yaml")
    return cfg.get("debate_agents", [])


def run_debate(topic: str = "龙族一至四之后的长篇续写结局方案") -> Dict[str, Any]:
    ensure_dir(DEBATE_DIR)
    if not KB_PATH.exists():
        raise FileNotFoundError("global knowledge not found; run `python main.py compress` first")
    agents = load_agents()
    if not agents:
        raise ValueError("no debate agents configured")
    knowledge = KB_PATH.read_text(encoding="utf-8")
    index = read_json(INDEX_PATH, {})
    facts = global_facts_summary()
    client = LLMClient("debate")
    log_path = DEBATE_DIR / "debate_log.jsonl"

    # Iter 016: render agents through persona binding when available. When
    # personas.json is missing/empty, render_agent_fields returns legacy
    # fields, preserving the original validation-corpus workflow.
    personas = load_personas()
    rendered_agents: List[Dict[str, Any]] = []
    for agent in agents:
        name, system_prompt, stance = render_agent_fields(agent, personas, log_context="debate")
        rendered = dict(agent)
        rendered["name"] = name or rendered.get("name") or "agent"
        rendered["system_prompt"] = system_prompt
        rendered["stance"] = stance
        rendered_agents.append(rendered)
    agents = rendered_agents
    if personas:
        log_event("debate", "persona_applied", protagonist=personas.get("protagonist_name"), author=personas.get("author_name"))

    # Resume support (iter 015 cross-novel smoke): rather than always unlinking
    # the log, read previously-completed (round, agent) entries with non-empty
    # response and skip them. Failed/empty entries are retried.
    transcript: List[Dict[str, Any]] = []
    done_keys: set = set()
    done_ballots: set = set()
    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ag = entry.get("agent")
                r = entry.get("round")
                rn = entry.get("round_name")
                resp = entry.get("response", "")
                err = entry.get("error")
                if rn == "裁决投票":
                    if not err and entry.get("ballots"):
                        done_ballots.add(ag)
                    continue
                if r is None or ag is None:
                    continue
                if err or not resp:
                    continue
                key = (r, ag)
                if key in done_keys:
                    continue
                done_keys.add(key)
                transcript.append({"round": r, "round_name": rn, "agent": ag, "response": resp})
        # Rewrite log keeping only retained entries so we don't accumulate
        # stale error rows on each resume.
        with log_path.open("w", encoding="utf-8") as fh:
            for item in transcript:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    for round_index, round_name in enumerate(ROUNDS, 1):
        for agent in agents:
            if (round_index, agent["name"]) in done_keys:
                continue
            try:
                response = client.complete_text(
                    [
                        {"role": "system", "content": agent.get("system_prompt", agent.get("stance", ""))},
                        {
                            "role": "user",
                            "content": (
                                f"辩论主题: {topic}\n"
                                f"轮次: {round_index} - {round_name}\n"
                                f"agent_name: {agent['name']}\n"
                                f"已有共识/争议:\n{json.dumps(transcript[-12:], ensure_ascii=False)[:6000]}\n\n"
                                f"人工全局事实:\n{facts}\n\n"
                                f"知识文档摘要:\n{knowledge[:9000]}\n\n"
                                f"索引统计: {json.dumps({k: len(v) if hasattr(v, '__len__') else 0 for k, v in index.items()}, ensure_ascii=False)}"
                            ),
                        },
                    ],
                    temperature=agent.get("temperature", 0.4),
                )
                item = {"round": round_index, "round_name": round_name, "agent": agent["name"], "response": response}
            except Exception as exc:
                item = {"round": round_index, "round_name": round_name, "agent": agent["name"], "error": str(exc), "response": ""}
                log_event("debate", "agent_error", agent=agent["name"], round=round_index, error=str(exc))
            transcript.append(item)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    decisions = build_decisions(agents, transcript, client)
    agent_ballots: Dict[str, List[Dict[str, Any]]] = {}
    for agent in agents:
        if agent["name"] in done_ballots:
            # Reuse previously logged ballot if present.
            continue
        ballot_entry = _collect_agent_votes(agent, decisions.get("votes", []), transcript, client)
        agent_ballots[agent["name"]] = ballot_entry["ballots"]
        log_item = {
            "round": len(ROUNDS) + 1,
            "round_name": "裁决投票",
            "agent": agent["name"],
            "response": ballot_entry["response"],
            "ballots": ballot_entry["ballots"],
        }
        if ballot_entry.get("error"):
            log_item["error"] = ballot_entry["error"]
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(log_item, ensure_ascii=False) + "\n")

    # If any ballots were resumed from log, load them now so _apply_agent_ballots
    # sees them too.
    if done_ballots:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("round_name") == "裁决投票":
                    ag = entry.get("agent")
                    if ag and ag in done_ballots and ag not in agent_ballots:
                        agent_ballots[ag] = entry.get("ballots", [])
    decisions = _apply_agent_ballots(decisions, agent_ballots, len(transcript))
    outline = build_outline(topic, decisions, transcript, client)
    write_json(DEBATE_DIR / "decisions.json", decisions)
    write_text_atomic(DEBATE_DIR / "outline.md", outline)
    log_event("debate", "done", agents=len(agents), rounds=len(ROUNDS), output=str(DEBATE_DIR))
    return {"decisions": decisions, "outline": outline}


def _transcript_summary(transcript: List[Dict[str, Any]]) -> str:
    if len(transcript) <= 30:
        return json.dumps(transcript, ensure_ascii=False)
    first_6 = transcript[:6]
    last_24 = transcript[-24:]
    return json.dumps(first_6 + [{"__truncated__": f"{len(transcript) - 30} items omitted"}] + last_24, ensure_ascii=False)


def _fallback_ballots(agent_name: str, votes: List[Dict[str, Any]], reason: str) -> List[Dict[str, Any]]:
    return [
        {
            "agent_name": agent_name,
            "question_index": idx,
            "position": "abstain",
            "reason": reason,
        }
        for idx, _vote in enumerate(votes)
    ]


def _question_list_for_ballot(votes: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"{idx}. {vote.get('question', '')} -> proposed result: {vote.get('result', '')}"
        for idx, vote in enumerate(votes)
    )


def _ballot_data_is_complete(data: Dict[str, Any], expected_count: int) -> bool:
    ballots = data.get("ballots", [])
    if expected_count == 0:
        return ballots == []
    if len(ballots) != expected_count:
        return False
    try:
        indexes = {int(item["question_index"]) for item in ballots}
    except (KeyError, TypeError, ValueError):
        return False
    return indexes == set(range(expected_count))


def _infer_position_from_reason(reason: Any) -> Literal["agree", "abstain", "reject"]:
    if not isinstance(reason, str):
        return "abstain"
    text = reason.lower()
    reject_keywords = ("反对", "反驳", "拒绝", "否决", "不同意", "不支持", "disagree", "reject", "oppose", "against")
    agree_keywords = ("同意", "赞同", "支持", "认可", "agree", "approve", "support")
    if any(keyword in text for keyword in reject_keywords):
        return "reject"
    if any(keyword in text for keyword in agree_keywords):
        return "agree"
    return "abstain"


def _normalized_position(value: Any, reason: Any) -> Literal["agree", "abstain", "reject"]:
    text = str(value).strip().lower() if value is not None else ""
    aliases = {
        "agree": "agree",
        "approve": "agree",
        "support": "agree",
        "yes": "agree",
        "赞同": "agree",
        "同意": "agree",
        "支持": "agree",
        "reject": "reject",
        "disagree": "reject",
        "oppose": "reject",
        "against": "reject",
        "no": "reject",
        "反对": "reject",
        "拒绝": "reject",
        "否决": "reject",
        "abstain": "abstain",
        "neutral": "abstain",
        "skip": "abstain",
        "弃权": "abstain",
        "中立": "abstain",
    }
    if text in aliases:
        return aliases[text]  # type: ignore[return-value]
    return _infer_position_from_reason(reason)


def _repair_ballot_dict(raw: Any, agent_name: str, expected_count: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"ballots": []}
    raw_ballots = raw.get("ballots", [])
    if not isinstance(raw_ballots, list):
        return {"ballots": []}

    repaired: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_ballots):
        if not isinstance(item, dict):
            continue
        reason = item.get("reason", item.get("rationale", item.get("explanation", "")))
        position_value = item.get(
            "position",
            item.get("answer", item.get("preference", item.get("verdict", item.get("vote")))),
        )
        try:
            question_index = int(item.get("question_index", idx))
        except (TypeError, ValueError):
            question_index = idx
        repaired.append(
            {
                "agent_name": str(item.get("agent_name", agent_name) or agent_name),
                "question_index": question_index,
                "position": _normalized_position(position_value, reason),
                "reason": str(reason or ""),
            }
        )
    return {"ballots": repaired}


def _collect_agent_vote_json(
    agent: Dict[str, Any],
    votes: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
    client: LLMClient,
    *,
    retry: bool = False,
) -> Dict[str, Any]:
    agent_name = agent["name"]
    expected_count = len(votes)
    if retry:
        system_content = (
            "你之前漏掉了 ballot；这次必须输出完整 JSON。"
            f"ballots 数组长度必须严格等于 {expected_count}，一个不少。"
        )
        user_intro = (
            f"你必须为每一个议题输出一个 ballot。禁止返回空数组。"
            f"ballots 数组长度必须严格等于 {expected_count}。"
            f"question_index 必须是 0 到 {max(expected_count - 1, 0)} 中唯一的整数。"
        )
        transcript_text = ""
    else:
        system_content = (
            f"{agent.get('system_prompt', agent.get('stance', ''))}\n"
            "你正在进行辩论后的裁决投票。只输出合法 JSON。"
        )
        user_intro = (
            f"你必须为下面每一个议题输出一个 ballot。ballots 数组长度必须严格等于 {expected_count}。"
            f"每个 ballot 的 question_index 必须是 0 到 {max(expected_count - 1, 0)} 中唯一的一个整数。"
            "禁止返回空数组。"
            "position 只能是 agree、abstain 或 reject，并写一句简短 reason。"
            "如果你倾向支持，必须显式写 position: agree；反对写 reject；无法判断写 abstain。"
        )
        transcript_text = f"\n\n辩论记录摘要:\n{_transcript_summary(transcript)[:8000]}"
    content = client.complete_text(
        [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    f"{user_intro}\n\n"
                    f"agent_name: {agent_name}\n"
                    f"议题清单（numbered question list，question_index 从 0 开始）:\n"
                    f"{_question_list_for_ballot(votes)}"
                    f"{transcript_text}"
                ),
            },
        ],
    )
    raw = json.loads(extract_json_object(content))
    return _repair_ballot_dict(raw, agent_name, expected_count)


def _collect_agent_votes(
    agent: Dict[str, Any],
    votes: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
    client: LLMClient,
) -> Dict[str, Any]:
    agent_name = agent["name"]
    if client.is_mock:
        ballots = _fallback_ballots(agent_name, votes, "(mock)")
        return {"response": "(mock)", "ballots": ballots}

    try:
        data = _collect_agent_vote_json(agent, votes, transcript, client)
        if not _ballot_data_is_complete(data, len(votes)):
            log_event(
                "debate",
                "ballot_retry",
                agent=agent_name,
                expected=len(votes),
                received=len(data.get("ballots", [])),
            )
            data = _collect_agent_vote_json(agent, votes, transcript, client, retry=True)
        if not _ballot_data_is_complete(data, len(votes)):
            log_event(
                "debate",
                "ballot_empty_after_retry",
                agent=agent_name,
                expected=len(votes),
                received=len(data.get("ballots", [])),
            )
            ballots = _fallback_ballots(agent_name, votes, "(missing-after-retry)")
            return {"response": json.dumps(data, ensure_ascii=False), "ballots": ballots}

        by_index = {int(item["question_index"]): item for item in data.get("ballots", [])}
        ballots: List[Dict[str, Any]] = []
        for idx, _vote in enumerate(votes):
            item = by_index.get(idx)
            if not item:
                ballots.append(
                    {
                        "agent_name": agent_name,
                        "question_index": idx,
                        "position": "abstain",
                        "reason": "(missing)",
                    }
                )
                continue
            ballots.append(
                {
                    "agent_name": agent_name,
                    "question_index": idx,
                    "position": item["position"],
                    "reason": item.get("reason", ""),
                }
            )
        return {"response": json.dumps(data, ensure_ascii=False), "ballots": ballots}
    except Exception as exc:
        log_event("debate", "ballot_fallback", agent=agent_name, error=str(exc))
        ballots = _fallback_ballots(agent_name, votes, "(parse_failed)")
        return {"response": "", "ballots": ballots, "error": str(exc)}


def _with_result_prefix(result: str, prefix: str) -> str:
    if result.startswith("[平票] ") or result.startswith("[多数反对] "):
        return result
    return f"{prefix} {result}"


def _continuation_anchor() -> str:
    return load_continuation_anchor()


def _anchor_prompt_block() -> str:
    anchor = _continuation_anchor()
    if not anchor:
        return ""
    return f"续写起点（must-anchor）:\n{anchor}\n\n"


def _style_prompt_block() -> str:
    examples = load_style_examples()
    if not examples:
        return ""
    return (
        "作者风格参考（只学习节奏、含蓄度与意象方式，不复制具体情节/人名/场景）:\n"
        f"{examples[:6000]}\n\n"
    )


def _apply_agent_ballots(
    decisions: Dict[str, Any],
    agent_ballots: Dict[str, List[Dict[str, Any]]],
    transcript_items: int,
) -> Dict[str, Any]:
    votes = decisions.get("votes", [])
    for idx, vote in enumerate(votes):
        ballots: List[Dict[str, Any]] = []
        for agent_name, agent_items in agent_ballots.items():
            for item in agent_items:
                if int(item.get("question_index", -1)) != idx:
                    continue
                ballots.append(
                    {
                        "agent_name": item.get("agent_name", agent_name),
                        "position": item.get("position", "abstain"),
                        "reason": item.get("reason", ""),
                    }
                )
        agree = [item["agent_name"] for item in ballots if item["position"] == "agree"]
        reject = [item["agent_name"] for item in ballots if item["position"] == "reject"]
        vote["for"] = agree
        vote["against"] = reject
        if len(agree) < len(reject):
            vote["result"] = _with_result_prefix(vote.get("result", ""), "[多数反对]")
        elif len(agree) == len(reject):
            vote["result"] = _with_result_prefix(vote.get("result", ""), "[平票]")
        vote["agent_votes"] = ballots
    decisions["aggregation_method"] = "majority"
    decisions["transcript_items"] = transcript_items
    return decisions


def _coerce_vote_list(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        raw_votes = raw.get("votes", [])
    elif isinstance(raw, list):
        raw_votes = raw
    else:
        raw_votes = []
    if not isinstance(raw_votes, list):
        return []

    votes: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_votes):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("议题") or item.get("title") or f"fallback vote {idx + 1}").strip()
        result = str(item.get("result") or item.get("裁决") or item.get("decision") or item.get("summary") or "").strip()
        if not result:
            result = "由辩论记录宽松推断出的临时裁决"
        supporters = item.get("for", item.get("supporters", item.get("支持", [])))
        opponents = item.get("against", item.get("opponents", item.get("反对", [])))
        if not isinstance(supporters, list):
            supporters = [str(supporters)] if supporters else []
        if not isinstance(opponents, list):
            opponents = [str(opponents)] if opponents else []
        votes.append(
            {
                "question": question,
                "result": result,
                "for": [str(name) for name in supporters],
                "against": [str(name) for name in opponents],
            }
        )
    return votes


def _placeholder_votes(voter_names: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "question": "结构化投票缺失时是否保留当前大纲约束",
            "result": "由于 LLM 未返回有效投票，默认全员 abstain，保留辩论摘要供人工复核",
            "for": [],
            "against": [],
        },
        {
            "question": "是否需要人工复核本次 debate decisions",
            "result": "需要；本条为防空 fallback，不代表真实多数决",
            "for": [],
            "against": [],
        },
        {
            "question": "outline 是否继续生成",
            "result": "继续生成，但标记 votes_empty_fallback 以便后续追踪",
            "for": [],
            "against": [],
        },
    ]


def _legacy_llm_derived_votes(
    agents: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
    client: LLMClient,
    global_facts: str | None = None,
) -> List[Dict[str, Any]]:
    voter_names = [agent["name"] for agent in agents]
    try:
        content = client.complete_text(
            [
                {
                    "role": "system",
                    "content": "你是辩论记录整理员。宽松推断核心裁决即可，优先输出 JSON。",
                },
                {
                    "role": "user",
                    "content": (
                        "structured decisions 的 votes 为空。请基于辩论记录补 1-3 条临时裁决。"
                        "输出 JSON 对象，格式为 {\"votes\":[{\"question\":\"...\",\"result\":\"...\",\"for\":[...],\"against\":[...]}]}。"
                        "for/against 填 agent 名；不确定可留空。\n\n"
                        f"Agent 列表: {json.dumps(voter_names, ensure_ascii=False)}\n\n"
                        f"人工全局事实:\n{global_facts or global_facts_summary()}\n\n"
                        f"辩论记录:\n{_transcript_summary(transcript)[:10000]}"
                    ),
                },
            ]
        )
        try:
            raw = json.loads(extract_json_object(content))
        except (ValueError, json.JSONDecodeError):
            raw = []
        votes = _coerce_vote_list(raw)
        if votes:
            return votes[:3]
    except Exception as exc:
        log_event("debate", "votes_empty_fallback_error", error=str(exc))
    return _placeholder_votes(voter_names)


def build_decisions(
    agents: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
    client: LLMClient,
    global_facts: str | None = None,
    *,
    agent_ballots: Dict[str, List[Dict[str, Any]]] | None = None,
) -> Dict[str, Any]:
    voter_names = [agent["name"] for agent in agents]
    if client.is_mock:
        data = {
            "topic": "续写核心裁决",
            "votes": [
                {
                    "question": "路鸣泽在最终牺牲前是否保留过夺权念头",
                    "result": "有，但不把角色简化成反派",
                    "for": voter_names[:4],
                    "against": voter_names[4:],
                },
                {
                    "question": "楚子航回归后是否丢失夏弥记忆",
                    "result": "不丢失，记忆作为代价和行动动机保留",
                    "for": voter_names[:5],
                    "against": voter_names[5:],
                },
            ],
            "aggregation_method": "majority",
            "transcript_items": len(transcript),
        }
        if agent_ballots is not None:
            return _apply_agent_ballots(data, agent_ballots, len(transcript))
        return data
    try:
        result = client.complete_json(
            [
                {"role": "system", "content": "你是辩论汇总裁判。根据多轮辩论记录，提取核心投票裁决，输出合法 JSON。"},
                {
                    "role": "user",
                    "content": (
                        "根据以下辩论记录，总结 2-5 个核心投票问题及裁决结果。"
                        "每个 vote 包含 question、result、for（支持该裁决的 agent 名列表）、against（反对的 agent 名列表）。\n\n"
                        f"Agent 列表: {json.dumps(voter_names, ensure_ascii=False)}\n\n"
                        f"{_anchor_prompt_block()}"
                        f"人工全局事实:\n{global_facts or global_facts_summary()}\n\n"
                        f"辩论记录:\n{_transcript_summary(transcript)}"
                    ),
                },
            ],
            DebateDecisions,
        )
        data = model_to_dict(result)
        data["transcript_items"] = len(transcript)
        data["aggregation_method"] = "majority"
        if not data.get("votes"):
            log_event("debate", "votes_empty_fallback", reason="llm_returned_empty_votes")
            data["votes"] = _legacy_llm_derived_votes(agents, transcript, client, global_facts)
        if agent_ballots is not None:
            return _apply_agent_ballots(data, agent_ballots, len(transcript))
        return data
    except Exception as exc:
        log_event("debate", "decision_fallback", error=str(exc))
        votes = _legacy_llm_derived_votes(agents, transcript, client, global_facts)
        data = {
            "topic": "续写核心裁决",
            "votes": votes,
            "aggregation_method": "majority",
            "transcript_items": len(transcript),
        }
        if agent_ballots is not None:
            return _apply_agent_ballots(data, agent_ballots, len(transcript))
        return data


def build_outline(
    topic: str,
    decisions: Dict[str, Any],
    transcript: List[Dict[str, Any]],
    client: LLMClient,
    global_facts: str | None = None,
) -> str:
    if client.is_mock:
        return _hardcoded_outline(topic, decisions)
    entity_state = render_active_state(load_entity_graph())
    entity_block = (
        f"{entity_state}\n"
        "严格遵守'当前活跃关系'：大纲中的人物互动、人物对彼此的认知、关系推进必须匹配上面 active 状态。\n\n"
        if entity_state
        else ""
    )
    # Iter 016: inject persona binding so the outline LLM call anchors on the
    # current novel rather than the original validation corpus.
    personas = load_personas()
    persona_block = ""
    if personas:
        bullets = []
        if personas.get("protagonist_name"):
            bullets.append(f"- 主角：{personas.get('protagonist_name')}（{personas.get('protagonist_role') or '？'}）")
        if personas.get("author_name"):
            bullets.append(f"- 作者风格参考：{personas.get('author_name')}（{personas.get('style_short_descriptor') or '？'}）")
        if personas.get("world_setting_brief"):
            bullets.append(f"- 世界观骨架：{personas.get('world_setting_brief')}")
        if personas.get("core_relationships"):
            bullets.append("- 核心关系：" + "；".join(personas["core_relationships"]))
        if personas.get("core_setting_rules"):
            bullets.append("- 世界观硬规则：" + "；".join(personas["core_setting_rules"]))
        if bullets:
            persona_block = "# 本书 persona 绑定（大纲严格遵守，禁止引用其他小说角色或世界观）\n" + "\n".join(bullets) + "\n\n"
    try:
        text = client.complete_text(
            [
                {"role": "system", "content": "你是小说大纲撰写者，基于辩论裁决和记录生成章节大纲，输出 Markdown。"},
                {
                    "role": "user",
                    "content": (
                        f"主题: {topic}\n\n"
                        f"{persona_block}"
                        f"{_anchor_prompt_block()}"
                        f"{_style_prompt_block()}"
                        f"人工全局事实:\n{global_facts or global_facts_summary()}\n\n"
                        f"{entity_block}"
                        f"裁决结果:\n{json.dumps(decisions, ensure_ascii=False)[:6000]}\n\n"
                        f"辩论摘要:\n{_transcript_summary(transcript)[:6000]}\n\n"
                        "请输出 Markdown 大纲，包含：核心共识、投票裁决、章节方向（默认 18 章）。"
                    ),
                },
            ],
            temperature=0.3,
        )
        return text.strip() + "\n"
    except Exception as exc:
        log_event("debate", "outline_fallback", error=str(exc))
        return _hardcoded_outline(topic, decisions)


def _hardcoded_outline(topic: str, decisions: Dict[str, Any]) -> str:
    lines = [
        f"# {topic}",
        "",
        "## 核心共识",
        "- 路明非的选择必须改变结局，而不是被世界观机械碾过。",
        "- 主要情感关系需要有明确去向，但保留江南式余味。",
        "- 未闭合伏笔必须进入章节级写作约束。",
        "- 世界观硬规则优先于爽点。",
        "",
        "## 投票裁决",
    ]
    for vote in decisions.get("votes", []):
        lines.append(f"- {vote['question']}：{vote['result']}。")
    lines.extend(["", "## 章节方向", "- 以十八章为默认输出规模，每章写作前读取上一章状态和全局知识索引。"])
    return "\n".join(lines) + "\n"
