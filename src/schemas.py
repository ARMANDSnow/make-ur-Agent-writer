from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


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


class ReviewIssue(BaseModel):
    message: str
    rule_id: Optional[str] = None
    severity: Optional[str] = None
    anchor: Optional[str] = None


class AgentReview(BaseModel):
    agent_name: str
    verdict: str = Field(description="Approve or Reject")
    score: int = Field(default=7, ge=0, le=10)
    issues: List[Union[str, ReviewIssue]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    comparison_checklist: List[str] = Field(default_factory=list)


class ChapterSummary(BaseModel):
    summary: str = ""
    key_events: List[str] = Field(default_factory=list)
    ending_state: str = ""


class ChapterPlanItem(BaseModel):
    chapter_no: int
    title: str
    opening_scene: str = Field(description="一句话具体开场场景，writer 必须遵守")
    key_events: List[str] = Field(description="本章必须发生的 2-5 个核心事件", min_items=2, max_items=5)
    relationships_in_play: List[str] = Field(default_factory=list, description="本章重点演进的关系")
    ending_hook: str = Field(description="本章结尾留给下章承接的钩子")
    target_chinese_chars: int = Field(default=4000, ge=2500, le=6000)
    plot_purpose: str = Field(description="本章在整本书情节弧线中的作用")


class ChapterPlan(BaseModel):
    target_chapters: int
    overall_arc: str = Field(description="整本书的情节弧线")
    chapters: List[ChapterPlanItem]
    generated_by: str = "plot_planner_v1"


class EntityAdvanceProposal(BaseModel):
    src_id: str
    dst_id: str
    old_active_state: str = ""
    new_state: str
    trigger_event: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


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
