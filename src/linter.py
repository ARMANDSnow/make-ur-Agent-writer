from __future__ import annotations

import re
from typing import Any, Dict, List

from .config import load_config
from .schemas import LintIssue, model_to_dict


def count_chinese_chars(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


class NovelLinter:
    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else load_config("linter.yaml")
        self.rules = self.config.get("rules", {})

    def lint(self, text: str) -> List[Dict[str, Any]]:
        issues: List[LintIssue] = []
        lines = text.splitlines()
        if self.rules.get("meta_chapter_markers", {}).get("enabled", True):
            issues.extend(self._meta_chapter_markers(lines))
        if self.rules.get("not_x_but_y", {}).get("enabled", True):
            issues.extend(self._not_x_but_y(lines))
        if self.rules.get("short_sentence_openings", {}).get("enabled", True):
            issues.extend(self._short_sentence_openings(lines))
        if self.rules.get("name_drift", {}).get("enabled", True):
            issues.extend(self._name_drift(lines))
        if self.rules.get("ai_cliche_terms", {}).get("enabled", True):
            issues.extend(self._ai_cliches(lines))
        if self.rules.get("short_chapter_length", {}).get("enabled", True):
            issues.extend(self._short_chapter_length(text))
        return [model_to_dict(issue) for issue in issues]

    def _meta_chapter_markers(self, lines: List[str]) -> List[LintIssue]:
        pattern = re.compile(r"^\s*(?:第\s*\d+\s*章|第[一二三四五六七八九十百零〇两]+\s*章|Chapter\s+\d+)", re.I)
        return [
            LintIssue(
                rule="meta_chapter_markers",
                severity="error",
                message="正文中出现元叙事章节标记。",
                line=i,
                excerpt=line.strip(),
                anchor=_anchor_from_line(line),
            )
            for i, line in enumerate(lines, 1)
            if pattern.search(line)
        ]

    def _not_x_but_y(self, lines: List[str]) -> List[LintIssue]:
        cfg = self.rules.get("not_x_but_y", {})
        base_warn = int(cfg.get("warn_threshold", 2))
        base_error = int(cfg.get("error_threshold", 5))
        # Iter 022 B1: scale thresholds by chapter length. The base
        # warn_threshold=2 was calibrated against ~4000-char chapters;
        # at 15000 chars (iter 021 ch1) it triggered on 9 hits which
        # is normal density for dramatic Chinese prose. Scale linearly
        # by char_count / 4000, clamped to [1.0, 5.0] so the rule
        # still bites long AI-generated runs.
        full_text = "\n".join(lines)
        chinese_chars = count_chinese_chars(full_text)
        dynamic_scaling = bool(cfg.get("dynamic_scaling", True))
        if dynamic_scaling and chinese_chars > 0:
            scale = max(1.0, min(chinese_chars / 4000.0, 5.0))
        else:
            scale = 1.0
        warn_threshold = int(round(base_warn * scale))
        error_threshold = int(round(base_error * scale))
        pattern = re.compile(r"不是.{1,28}?[，,、\s]*是")
        matches = [
            (i, line, match)
            for i, line in enumerate(lines, 1)
            for match in pattern.finditer(line)
        ]
        count = len(matches)
        if count <= warn_threshold:
            return []
        severity = "error" if count >= error_threshold else "warning"
        return [
            LintIssue(
                rule="not_x_but_y",
                severity=severity,
                message=(
                    f"疑似 AI 标记句式：不是 X，是 Y。本章命中 {count} 次，"
                    f"按章节字数 {chinese_chars} 动态阈值 = warn>{warn_threshold} / "
                    f"error>={error_threshold}（scale={scale:.2f}）。"
                ),
                line=i,
                excerpt=line.strip(),
                anchor=_anchor_from_line(line, match.start(), match.end()),
                count=count,
            )
            for i, line, match in matches
        ]

    def _short_sentence_openings(self, lines: List[str]) -> List[LintIssue]:
        cfg = self.rules.get("short_sentence_openings", {})
        threshold = int(cfg.get("threshold", 3))
        window = int(cfg.get("window", 7))
        non_empty = [(i, line.strip()) for i, line in enumerate(lines, 1) if line.strip()][:window]
        short_count = sum(1 for _, line in non_empty if re.match(r"^.{1,12}[。！？!?]$", line))
        if short_count >= threshold:
            line_no, line = non_empty[0] if non_empty else (1, "")
            return [
                LintIssue(
                    rule="short_sentence_openings",
                    severity="warning",
                    message=f"章节开头短句过密：前 {window} 个非空行中有 {short_count} 个短句。",
                    line=line_no,
                    excerpt=line,
                    anchor=_anchor_from_line(line),
                )
            ]
        return []

    def _name_drift(self, lines: List[str]) -> List[LintIssue]:
        disallowed = self.rules.get("name_drift", {}).get("disallowed_terms", [])
        issues = []
        for i, line in enumerate(lines, 1):
            for term in disallowed:
                if term.get("wrong") in line:
                    issues.append(
                        LintIssue(
                            rule="name_drift",
                            severity="warning",
                            message=f"疑似称谓漂移：{term.get('wrong')}，建议核对是否应为 {term.get('correct')}。",
                            line=i,
                            excerpt=line.strip(),
                            anchor=_anchor_from_line(line),
                        )
                    )
        return issues

    def _ai_cliches(self, lines: List[str]) -> List[LintIssue]:
        terms = self.rules.get("ai_cliche_terms", {}).get("terms", [])
        issues = []
        for i, line in enumerate(lines, 1):
            for term in terms:
                if term in line:
                    issues.append(
                        LintIssue(
                            rule="ai_cliche_terms",
                            severity="warning",
                            message=f"疑似现代 AI 腔词：{term}。",
                            line=i,
                            excerpt=line.strip(),
                            anchor=_anchor_from_line(line),
                    )
                )
        return issues

    def _short_chapter_length(self, text: str) -> List[LintIssue]:
        count = count_chinese_chars(text)
        if count >= 3500:
            return []
        severity = "error" if count < 2500 else "warning"
        return [
            LintIssue(
                rule="short_chapter_length",
                severity=severity,
                message=f"章节中文字数过短：{count}，目标 3500-5500。",
                line=1,
                excerpt=f"chinese_char_count={count}",
                anchor=f"chinese_char_count={count}",
            )
        ]


def _anchor_from_line(line: str, start: int | None = None, end: int | None = None) -> str:
    text = line.strip()
    if not text:
        return ""
    if start is None or end is None:
        return text[:100]
    left = max(0, start - 20)
    right = min(len(line), end + 20)
    anchor = line[left:right].strip()
    if left > 0:
        anchor = "..." + anchor
    if right < len(line):
        anchor = anchor + "..."
    return anchor[:100]
