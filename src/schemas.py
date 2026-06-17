from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)  # type: ignore[attr-defined]
    return model.dict(by_alias=True)


def model_to_json_schema(model_cls: type[BaseModel]) -> Dict[str, Any]:
    if hasattr(model_cls, "model_json_schema"):
        return model_cls.model_json_schema()  # type: ignore[attr-defined]
    return model_cls.schema()


class EvidenceSpan(BaseModel):
    source_file: str
    chapter_id: str
    start_line: int
    end_line: int
    quote: str = Field(default="", max_length=300)
    note: str = ""


class CharacterStateChange(BaseModel):
    character: str
    before: str = ""
    after: str
    status: str = ""
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class RelationshipChange(BaseModel):
    characters: List[str]
    before: str = ""
    after: str
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class ForeshadowingItem(BaseModel):
    kind: str = Field(description="clue, payoff, unresolved, or ambiguity")
    description: str
    status: str = "unresolved"
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class WorldbuildingRule(BaseModel):
    topic: str
    detail: str
    constraint_level: str = "soft"
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class StyleSample(BaseModel):
    quote: str = Field(max_length=500)
    note: str
    source_line: Optional[int] = None


class ChapterExtraction(BaseModel):
    chapter_id: str
    volume_id: str
    title: str
    summary: str
    rolling_summary: str = ""
    character_states: List[CharacterStateChange] = Field(default_factory=list)
    relationships: List[RelationshipChange] = Field(default_factory=list)
    foreshadowing: List[ForeshadowingItem] = Field(default_factory=list)
    worldbuilding: List[WorldbuildingRule] = Field(default_factory=list)
    style_samples: List[StyleSample] = Field(default_factory=list)
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)
    manual_overrides_applied: List[str] = Field(default_factory=list)


class PremiseExpansion(BaseModel):
    """Iter 051a: structured expansion of a one-sentence premise.

    The premise-start greenfield path (048a) feeds a few-dozen-char seed to
    prepare-greenfield; KB / entity_graph come out too thin for debate /
    plan-chapters to chew on. This schema is the LLM expansion artifact:
    persisted as an independent product next to seed.txt (never overwriting
    it — seed is the user's words, this is model inference), shown and
    editable in workbench stage ①, and consumed by the prepare/debate prompt
    chain when present. Per-field max_length doubles as the M-4 length gate
    for the PUT edit endpoint (validation goes through this model).
    """

    genre_tone: str = Field(default="", max_length=300, description="题材与基调，一两句")
    protagonist: str = Field(default="", max_length=2000, description="主角卡：身份/欲望/缺陷/起点处境")
    world_notes: List[str] = Field(
        default_factory=list, max_items=20, description="世界观要点，每条一句（≤20 条）"
    )
    central_conflict: str = Field(default="", max_length=2000, description="贯穿全书的主冲突")
    ending_anchor: str = Field(default="", max_length=1000, description="结局锚点：故事最终走向哪里")
    arc_hints: List[str] = Field(
        default_factory=list, max_items=20, description="前 N 章弧线提示，每条一句（≤20 条）"
    )

    @model_validator(mode="after")
    def _cap_list_item_length(self) -> "PremiseExpansion":
        # max_length on the list fields' items isn't expressible with the
        # min_items/max_items style used elsewhere in this file; enforce the
        # per-item cap here so prompt injection stays bounded.
        for field_name in ("world_notes", "arc_hints"):
            for item in getattr(self, field_name):
                if not isinstance(item, str) or len(item) > 500:
                    raise ValueError(f"{field_name} items must be strings of <=500 chars")
        return self


class WriterStyleCard(BaseModel):
    """Iter 056: 轻量「作家风格卡」——结构化的简短风格特征描述。

    仅 premise 自创书注入（续写书靠原著 style_examples + 起点前原文）。每字段
    都很短：卡片随 writer prompt 的可缓存段注入，长 prose 会让每次写作调用膨
    胀。per-field max_length 同时充当 PUT 编辑端点的长度门（校验走本 model，与
    PremiseExpansion 同范式）。name/category 是身份元字段（卡头展示 / 预置分
    组），不进 prompt 正文列表。
    """

    name: str = Field(default="", max_length=40, description="风格卡名称，如『冷峻克制·硬汉派』")
    category: str = Field(default="", max_length=40, description="风格定位/流派标签，如『悬疑』『古典武侠』")
    rhythm: str = Field(default="", max_length=200, description="叙事节奏：快/慢、张弛、场景切换密度")
    sentence: str = Field(default="", max_length=200, description="句式特征：长短句配比、语序、标点习惯")
    diction: str = Field(default="", max_length=200, description="用词偏好：书面/口语、雅俗、生僻字、方言色彩")
    imagery: str = Field(default="", max_length=300, description="意象与比喻：取材范围、密度、感官通道偏好")
    dialogue: str = Field(default="", max_length=300, description="对话风格：信息密度、潜台词、人物腔调区分度")
    subtext: str = Field(default="", max_length=300, description="含蓄度：直白抒情 vs 留白克制；情绪外显程度")
    narration: str = Field(default="", max_length=200, description="叙述视角与距离：全知/限知、与人物的心理贴近度")
    signatures: List[str] = Field(
        default_factory=list,
        max_items=12,
        description="标志性笔法/惯用手法，每条一句（≤12 条；描述手法，不给字面例句以免污染输出）",
    )
    taboo: List[str] = Field(
        default_factory=list, max_items=12, description="该风格要避免的笔法，每条一句（≤12 条）"
    )

    @model_validator(mode="after")
    def _cap_list_item_length(self) -> "WriterStyleCard":
        # 同 PremiseExpansion：list 项的 max_length 用 max_items 风格表达不了，
        # 在这里逐项卡死，保证注入到 prompt 的体量有界。
        for field_name in ("signatures", "taboo"):
            for item in getattr(self, field_name):
                if not isinstance(item, str) or len(item) > 300:
                    raise ValueError(f"{field_name} items must be strings of <=300 chars")
        return self


class ReviewIssue(BaseModel):
    message: str
    rule_id: Optional[str] = None
    severity: Optional[str] = None
    anchor: Optional[str] = None


class AgentSubScores(BaseModel):
    """Iter 022 B3: replace single 0-10 score with 3 sub-scores.

    The 5-8 agent panel before iter 022 all gave 7 because the single
    score was a coarse "approve probability" proxy. Splitting into
    plot (情节推进力) / prose (文笔质感) / fidelity (与原作贴合度) lets
    each agent have meaningful per-axis disagreement and surfaces
    weakness patterns (e.g. all-7 on plot but 5 on fidelity).
    """

    plot: int = Field(default=7, ge=0, le=10, description="情节推进力")
    prose: int = Field(default=7, ge=0, le=10, description="文笔质感")
    fidelity: int = Field(default=7, ge=0, le=10, description="与原作贴合度")


class AgentReview(BaseModel):
    agent_name: str
    verdict: Literal["Approve", "Reject"] = Field(description="Approve or Reject")
    # Iter 022 B3: new 3-axis sub-scores. The legacy `score` field is
    # kept for backward read of iter 020/021 meta.json files but is now
    # *derived* from sub-scores via weighted average if not explicitly
    # supplied. New code should write to `scores`; old meta.json files
    # parse cleanly because both fields have defaults.
    scores: AgentSubScores = Field(default_factory=AgentSubScores)
    score: int = Field(default=7, ge=0, le=10)
    issues: List[Union[str, ReviewIssue]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    comparison_checklist: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_legacy_score(self) -> "AgentReview":
        """If `scores` was provided but `score` wasn't (or was the default
        7), derive `score` as weighted avg: plot 0.4 + prose 0.3 + fidelity 0.3.
        Lets downstream code that still reads `.score` get a meaningful
        number while sub-score consumers (iter 022+) see the detail.
        """
        # Only re-derive when scores looks "explicit" (any non-default) AND
        # score is still default. This preserves byte-identical legacy
        # behavior when a caller passes only score.
        sub = self.scores
        if (sub.plot, sub.prose, sub.fidelity) != (7, 7, 7) and self.score == 7:
            weighted = sub.plot * 0.4 + sub.prose * 0.3 + sub.fidelity * 0.3
            object.__setattr__(self, "score", int(round(weighted)))
        return self


class ChapterSummary(BaseModel):
    summary: str = ""
    key_events: List[str] = Field(default_factory=list)
    ending_state: str = ""


class ChapterSegment(BaseModel):
    """Iter 046: AgentWrite-style segment with a word-count quota.

    Optional per-chapter decomposition. When a ``ChapterPlanItem`` carries
    segments AND the writer's ``segmented_write`` toggle is on, the writer
    generates the chapter segment-by-segment, honoring each quota and
    suppressing premature wrap-up on non-final segments. An empty
    ``segments`` list (the default) => single-shot generation, byte-identical
    to pre-046. Segments are intentionally excluded from the chapter plan
    fingerprint (see ``plot_planner.chapter_plan_item_fingerprint``) so
    adding the field never invalidates an already-written chapter.
    """

    segment_no: int = Field(ge=1, description="段序号，从 1 连续递增")
    beat: str = Field(description="本段要写的情节 beat，一句话")
    target_chinese_chars: int = Field(
        default=1200, ge=300, le=4000, description="本段目标中文字数（配额）"
    )
    is_final: bool = Field(
        default=False, description="是否为本章最后一段；只有最后一段写 ending_hook 收尾"
    )


class ChapterPlanItem(BaseModel):
    chapter_no: int
    title: str
    opening_scene: str = Field(description="一句话具体开场场景，writer 必须遵守")
    key_events: List[str] = Field(description="本章必须发生的 2-7 个核心事件", min_items=2, max_items=7)
    relationships_in_play: List[str] = Field(default_factory=list, description="本章重点演进的关系")
    ending_hook: str = Field(description="本章结尾留给下章承接的钩子")
    target_chinese_chars: int = Field(default=4000, ge=2500, le=6000)
    plot_purpose: str = Field(description="本章在整本书情节弧线中的作用")
    segments: List[ChapterSegment] = Field(
        default_factory=list,
        description="可选：分段写作计划（配额循环）；为空则单发生成",
    )
    chapter_plan_item_fingerprint: str = ""


class ChapterPlan(BaseModel):
    target_chapters: int
    overall_arc: str = Field(description="整本书的情节弧线")
    chapters: List[ChapterPlanItem]
    generated_by: str = "plot_planner_v1"
    schema_version: int = 1
    start_chapter_id: str = ""
    start_point_fingerprint: str = ""
    plan_fingerprint: str = ""


def _coerce_confidence(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    mapping = {
        "high": 0.85,
        "medium": 0.6,
        "mid": 0.6,
        "low": 0.3,
        "高": 0.85,
        "中": 0.6,
        "低": 0.3,
        "高置信": 0.85,
        "中置信": 0.6,
        "低置信": 0.3,
    }
    return mapping.get(normalized, value)


def _split_relationship_id(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    for sep in ("<->", "↔", "->", "→", "/", "|", ",", "，"):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    return "", ""


class EntityAdvanceProposal(BaseModel):
    src_id: str = ""
    dst_id: str = ""
    old_active_state: str = ""
    new_state: str
    trigger_event: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def repair_common_llm_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        repaired = dict(data)
        if not repaired.get("src_id"):
            repaired["src_id"] = repaired.get("source_id") or repaired.get("source") or ""
        if not repaired.get("dst_id"):
            repaired["dst_id"] = repaired.get("target_id") or repaired.get("target") or ""
        if (not repaired.get("src_id") or not repaired.get("dst_id")) and repaired.get("relationship_id"):
            src_id, dst_id = _split_relationship_id(repaired.get("relationship_id"))
            repaired["src_id"] = repaired.get("src_id") or src_id
            repaired["dst_id"] = repaired.get("dst_id") or dst_id
        if not repaired.get("new_state"):
            repaired["new_state"] = (
                repaired.get("state_after")
                or repaired.get("after")
                or repaired.get("proposed_state")
                or ""
            )
        repaired["confidence"] = _coerce_confidence(repaired.get("confidence", 0.0))
        return repaired


class EntityAdvanceProposalSet(BaseModel):
    proposed_advances: List[EntityAdvanceProposal] = Field(default_factory=list)


class LintIssue(BaseModel):
    rule: str
    severity: str
    message: str
    line: int
    excerpt: str = ""
    anchor: str = ""
    count: Optional[int] = None


class ChapterManifestEntry(BaseModel):
    chapter_id: str
    volume_id: str
    source_file: str
    normalized_file: str
    title: str
    start_line: int
    end_line: int
    char_count: int
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AgentVote(BaseModel):
    agent_name: str
    position: Literal["agree", "abstain", "reject"]
    reason: str = ""


class DebateVote(BaseModel):
    question: str
    result: str
    for_: List[str] = Field(default_factory=list, alias="for")
    against: List[str] = Field(default_factory=list)
    agent_votes: List[AgentVote] = Field(default_factory=list)


class DebateDecisions(BaseModel):
    topic: str = "续写核心裁决"
    votes: List[DebateVote] = Field(default_factory=list)
    aggregation_method: str = "majority"
    transcript_items: int = 0


class GlobalFact(BaseModel):
    fact_id: str
    statement: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    scope: str = "global"
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)
    applies_to: List[str] = Field(default_factory=list)
    # iter 047d: optional reader-known-after axis (chapter_id). Empty = use
    # evidence chapter_ids only (iter 021 behavior).
    reader_known_after: str = ""


class ProposalMeta(BaseModel):
    review_instructions: str = ""
    generated_by: str = "auto_bootstrap_v1"
    source_summary: str = ""


class GlobalFactsProposal(BaseModel):
    meta: ProposalMeta = Field(default_factory=ProposalMeta, alias="_meta")
    facts: List[GlobalFact] = Field(default_factory=list)


class EntityGraphProposal(BaseModel):
    meta: ProposalMeta = Field(default_factory=ProposalMeta, alias="_meta")
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)


class ContinuationAnchorProposal(BaseModel):
    meta: ProposalMeta = Field(default_factory=ProposalMeta, alias="_meta")
    anchor_text: str = ""
    key_state_points: List[str] = Field(default_factory=list)


class StyleExampleRange(BaseModel):
    category: str
    source_file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    preview: str = Field(default="", max_length=100)
    target_file: str


class StyleExamplesProposal(BaseModel):
    meta: ProposalMeta = Field(default_factory=ProposalMeta, alias="_meta")
    examples: List[StyleExampleRange] = Field(default_factory=list)


class SourceExcerptItem(BaseModel):
    """Iter 023: one tagged excerpt of source novel text.

    Unlike iter 015's StyleExampleRange (which only stores byte ranges
    and a 100-char preview), this stores the full excerpt text plus
    scene/character/tag metadata used by `src.source_excerpts.select_for_chapter`
    to match excerpts to upcoming chapter plans.
    """

    id: str = Field(default="", description="ex_001 etc.")
    source_chapter_id: str = Field(default="", max_length=80)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=1, ge=1)
    scene_type: str = Field(
        default="",
        max_length=20,
        description="战斗 / 心理 / 对话 / 场景描写 / 异能 / 情感 / 其它",
    )
    character_focus: List[str] = Field(
        default_factory=list, description="角色名列表，最多 5 个"
    )
    excerpt_text: str = Field(
        default="", description="实际原文片段（不超过 1500 字符）"
    )
    description: str = Field(
        default="",
        max_length=200,
        description="一句话总结片段内容，给 writer/reviewer 看",
    )
    tags: List[str] = Field(
        default_factory=list, description="≤5 个自由标签，如 '对决/觉醒/初遇'"
    )


class SourceExcerptsProposal(BaseModel):
    """Iter 023 bootstrap output: 15-20 tagged source-text excerpts."""

    meta: ProposalMeta = Field(default_factory=ProposalMeta, alias="_meta")
    excerpts: List[SourceExcerptItem] = Field(default_factory=list)


class RewriteSuggestion(BaseModel):
    """Iter 023: actionable suggestion from the advisor agent.

    Strictly schema-bound to avoid vague "improve this chapter" output.
    Writer rewrite-loop optionally consumes these as guidance.
    """

    section: str = Field(
        default="", max_length=60, description="如 '第 3 段' / '开场' / '结尾 hook'"
    )
    type: str = Field(
        default="rewrite",
        description="add | rewrite | cut",
    )
    guidance: str = Field(
        default="", max_length=300, description="具体怎么改的一句话指引"
    )


class RelationshipIssue(BaseModel):
    """Iter 023 P5: programmatic relationship-conflict report.

    Emitted by `src.relationship_auditor` (no LLM call). Joined into the
    reviewer report under a synthetic agent named ``deterministic_relations``.
    """

    src_name: str = Field(default="")
    dst_name: str = Field(default="")
    draft_excerpt: str = Field(default="", max_length=200)
    graph_active_state: str = Field(default="", max_length=200)
    conflict_reason: str = Field(default="", max_length=200)


class PersonasProposal(BaseModel):
    """Iter 016: persona bindings that fill agent prompt templates.

    All fields are LLM-extracted from already-bootstrapped data (entity_graph,
    global_facts, outline, normalized texts). The fields here are intentionally
    short — they get injected verbatim into prompt templates, so longer prose
    bloats every agent call.
    """

    meta: ProposalMeta = Field(default_factory=ProposalMeta, alias="_meta")
    protagonist_name: str = Field(default="", max_length=40)
    protagonist_role: str = Field(default="", max_length=120)
    author_name: str = Field(default="", max_length=40)
    style_short_descriptor: str = Field(default="", max_length=80)
    world_setting_brief: str = Field(default="", max_length=400)
    core_relationships: List[str] = Field(default_factory=list)
    core_setting_rules: List[str] = Field(default_factory=list)
