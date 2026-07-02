"""iter 075: 跨章全文检索（读者/编辑向连贯性核查 + 长书导航）。

在一个 workspace（作品）里跨三套语料检索正文内容：
  * ``original`` —— 原著章节（``chapter_manifest.json`` + ``normalized_texts/``）
  * ``draft``    —— 已生成的续写草稿（``outputs/drafts/chapter_NN.md``）
  * ``kb``       —— 起点安全知识库（``kb_view.start_safe_knowledge``）

用途：「续写里提到某实体，原著/KB 里它是什么状态」——一键跨章定位实体/伏笔/关键词。
与章节列表页的 ``#chapter-search`` 不同：那只对已加载表格按「章节 ID/标题」本地过滤，
本模块读**正文内容**做真全文检索。

## 为什么用 ``str.lower()+find`` 而非 ``re``（安全决策，勿改）

用户输入若编译成正则（``re.compile(q)``）有两条攻击面：
  1. **ReDoS**：``ThreadingHTTPServer`` 每请求一线程但无 CPU 超时；形如 ``(a+)+$`` 的
     灾难性回溯正则能把一个核占满。字面子串 ``str.find`` 是 CPython C 实现、严格线性
     O(n·m)、零回溯，天然免疫。
  2. 语义惊吓：用户搜 ``路明非(火)`` 本意是字面标点，正则会当成分组。字面匹配下所有
     正则元字符（``. * + ? ( ) [ ] \\ ^ $``）自动当字面量，零转义、符合直觉。

因此本模块**永不把用户输入编译成正则**。大小写不敏感只影响混入的英文术语
（EVA / Chihiro 等，中文无大小写）。

## offset 与 ``str.lower()`` 的长度不变式（高亮正确性根基）

``str.lower()`` 只会让码点**扩张**（如 ``'İ'.lower()`` = ``'i'+组合点`` 长度 1→2），
从不收缩。故 ``len(text) == len(text.lower())`` ⟺ 每个码点 1:1 映射 ⟺ lower 串上的
下标在原串精确对应。命中定位在 lower 串上做；当长度相等（中文+ASCII 的绝对多数）
直接用原文切片高亮；当长度不等（罕见外文边角）改用 lower 串本身做展示文本，offset
仍落在展示文本上——高亮永远正确，仅在罕见边角把片段显示为小写。

## 输出永不含 HTML

本模块只回**原始 UTF-8 片段文本 + 整数 offsets**；HTML 转义/高亮全在前端用 DOM
构建。即使正文含 ``<script>`` 也只当纯文本字段回传（XSS 防线的后端一侧）。

Mock-friendly（铁律④）：空/过短 query、manifest 缺失、裸仓库、章节文件损坏、无 KB
—— 全部降级为跳过该语料/该章，绝不抛异常。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import chapter_splitter, kb_view, paths

# ---- 有界常量（集中定义，测试直接 import 断言；严禁静默截断）--------------------
MIN_QUERY_LEN = 1          # strip 后 < 1 → 空结果（不报错）
MAX_QUERY_LEN = 100        # 超过 → 截断到 100 再搜，结果带 truncated
CONTEXT_RADIUS = 30        # 命中前后各取 30 字
MAX_SNIPPET_LEN = 200      # 单片段字符硬上限（含省略号）
MAX_SNIPPETS_PER_CHAPTER = 5
MAX_CHAPTERS = 200         # 命中单元数上限

SOURCE_ORIGINAL = "original"
SOURCE_DRAFT = "draft"
SOURCE_KB = "kb"
_ALL_SOURCES = (SOURCE_ORIGINAL, SOURCE_DRAFT, SOURCE_KB)

# 排序：续写命中最贴近连贯性核查场景放最前，原文按章序顺读，KB 聚合垫底。
_SOURCE_RANK = {SOURCE_DRAFT: 0, SOURCE_ORIGINAL: 1, SOURCE_KB: 2}

_DRAFT_RE = re.compile(r"^chapter_(\d+)$")   # 只认正式稿，排除 chapter_NN.partial


@dataclass
class Snippet:
    """命中片段。``text`` 是原始片段（未转义、可能保留小写降级），``offsets`` 是命中
    在 ``text`` 内的字符区间，升序、互不重叠、``0 <= start < end <= len(text)``。"""

    text: str
    offsets: List[Tuple[int, int]]


@dataclass
class SearchHit:
    """一个命中单元（一章原文 / 一章续写 / 整块 KB）。

    ``chapter_no`` 仅 draft 有值（前端据此拼 ``/w/<name>/chapter/<n>``）；workspace name
    不进本纯函数，故不返回 href。``match_count`` 是该单元内命中总数（可能 > 片段数）。"""

    source: str
    chapter_id: Optional[str]
    chapter_no: Optional[int]
    title: str
    match_count: int
    snippets: List[Snippet]


@dataclass
class SearchResult:
    query: str                 # 实际执行的 query（可能被截断到 MAX_QUERY_LEN）
    total_matches: int         # 全部命中单元的 match_count 合计（MAX_CHAPTERS 截断**前**的全局真实数）
    hit_count: int             # 实际返回的命中单元数（截断后 == len(hits)）
    hits: List[SearchHit]
    truncated: bool = False
    truncated_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)    # dataclass 全可 JSON 序列化；tuple→JSON array


# ---- 匹配与片段 --------------------------------------------------------------


def _find_all(needle_lower: str, hay_lower: str, limit: int) -> List[int]:
    """返回 ``needle_lower`` 在 ``hay_lower`` 中出现的起始下标，最多 ``limit`` 个。

    ``pos = i + len(needle_lower)`` 非重叠推进——防 ``needle='aa'`` 在 ``'aaaa'`` 上
    死循环 / 超量命中。与 ``str.count`` 的非重叠计数语义一致。"""

    step = len(needle_lower)
    out: List[int] = []
    pos = 0
    while len(out) < limit:
        i = hay_lower.find(needle_lower, pos)
        if i < 0:
            break
        out.append(i)
        pos = i + step
    return out


def _make_snippet(display: str, hit_start: int, needle_len: int) -> Snippet:
    """从 ``display`` 抽取命中前后 ``CONTEXT_RADIUS`` 字的片段并标注 offset。

    ``display`` 与 ``hit_start`` 已在调用处对齐（见模块 docstring 的长度不变式）。"""

    lo = max(0, hit_start - CONTEXT_RADIUS)
    hi = min(len(display), hit_start + needle_len + CONTEXT_RADIUS)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(display) else ""
    # 换行→空格是等长替换，不影响 offset；让片段单行更紧凑。
    seg = (prefix + display[lo:hi] + suffix).replace("\n", " ")
    off_start = (hit_start - lo) + len(prefix)
    off_end = off_start + needle_len
    if len(seg) > MAX_SNIPPET_LEN:
        seg = seg[:MAX_SNIPPET_LEN]
        off_end = min(off_end, MAX_SNIPPET_LEN)
    if not (0 <= off_start < off_end <= len(seg)):
        return Snippet(text=seg, offsets=[])   # 越界兜底：宁可不高亮也不错位
    return Snippet(text=seg, offsets=[(off_start, off_end)])


def _scan_unit(
    hay: str,
    needle_lower: str,
    *,
    source: str,
    chapter_id: Optional[str],
    chapter_no: Optional[int],
    title: str,
) -> Optional[SearchHit]:
    """扫一个正文单元，返回命中的 ``SearchHit`` 或 None（无命中）。

    片段截断信息不在此记录——``search_workspace`` 从最终存活 hit 派生
    （``match_count > len(snippets)``），避免被 MAX_CHAPTERS 丢弃的章留下悬空 reason。"""

    if not hay:
        return None
    hay_lower = hay.lower()
    total = hay_lower.count(needle_lower)   # 非重叠计数（C 实现）
    if total == 0:
        return None
    needle_len = len(needle_lower)
    # 长度相等 → 原文与 lower 串 1:1 对齐，用原文切片（保留大小写）；
    # 不等（罕见外文）→ 用 lower 串本身当展示文本，offset 仍精确。
    display = hay if len(hay) == len(hay_lower) else hay_lower
    starts = _find_all(needle_lower, hay_lower, MAX_SNIPPETS_PER_CHAPTER)
    snippets = [_make_snippet(display, s, needle_len) for s in starts]
    return SearchHit(
        source=source,
        chapter_id=chapter_id,
        chapter_no=chapter_no,
        title=title,
        match_count=total,
        snippets=snippets,
    )


# ---- 每语料一个扫描器（全部 try/except 降级，绝不抛异常）------------------------


def _search_original(needle_lower: str) -> List[SearchHit]:
    try:
        manifest = chapter_splitter.load_manifest()   # manifest 缺失 → FileNotFoundError
    except Exception:
        return []
    # iter076（codex 审查 iter075 #1）：manifest 是可编辑 JSON，normalized_file 不可
    # 直接信任——resolve 后必须落在本 workspace 的 normalized_texts/ 内（resolve 同时
    # 消解 symlink），越界条目按坏章跳过，杜绝借 manifest 读 workspace 外任意文件。
    try:
        normalized_root = paths.normalized_dir().resolve()
    except Exception:
        return []
    hits: List[SearchHit] = []
    # normalized_file 级读缓存：多章共享一卷文件时把 N 次全文件 IO 降到 1 次。
    line_cache: Dict[str, Optional[List[str]]] = {}
    for entry in manifest:
        if not isinstance(entry, dict):
            continue
        try:
            nf = str(entry["normalized_file"])
            if nf not in line_cache:
                try:
                    resolved = Path(nf).resolve()
                    resolved.relative_to(normalized_root)   # 越界 → ValueError → 跳过
                    line_cache[nf] = resolved.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError, ValueError):
                    line_cache[nf] = None
            lines = line_cache[nf]
            if lines is None:
                continue
            start = int(entry["start_line"]) - 1
            end = int(entry["end_line"])
            text = "\n".join(lines[start:end])
            cid = str(entry.get("chapter_id") or "")
            hit = _scan_unit(
                text,
                needle_lower,
                source=SOURCE_ORIGINAL,
                chapter_id=cid or None,
                chapter_no=None,
                title=str(entry.get("title") or cid or "原文章节"),
            )
        except Exception:
            continue   # 单章损坏跳过，不拖垮整轮
        if hit is not None:
            hits.append(hit)
    return hits


def _search_draft(needle_lower: str) -> List[SearchHit]:
    try:
        drafts = sorted(paths.drafts_dir().glob("chapter_*.md"))
    except Exception:
        return []
    numbered: List[Tuple[int, Path]] = []
    for md in drafts:
        m = _DRAFT_RE.match(md.stem)   # stem 含 .partial 者不匹配 → 只留正式稿
        if m:
            numbered.append((int(m.group(1)), md))
    numbered.sort(key=lambda t: t[0])
    hits: List[SearchHit] = []
    for n, md in numbered:
        try:
            text = md.read_text(encoding="utf-8")
            hit = _scan_unit(
                text,
                needle_lower,
                source=SOURCE_DRAFT,
                chapter_id=None,
                chapter_no=n,
                title=f"第 {n} 章 续写",
            )
        except (OSError, UnicodeDecodeError):
            continue
        if hit is not None:
            hits.append(hit)
    return hits


def _search_kb(needle_lower: str) -> List[SearchHit]:
    try:
        # respect_start_point=True 与 writer 一致，避免搜索泄露起点后剧透。
        text = kb_view.start_safe_knowledge(respect_start_point=True)
    except Exception:
        return []
    hit = _scan_unit(
        text or "",
        needle_lower,
        source=SOURCE_KB,
        chapter_id=None,
        chapter_no=None,
        title="知识库",
    )
    return [hit] if hit is not None else []


# ---- 公开入口 ----------------------------------------------------------------


def _sort_key(hit: SearchHit) -> Tuple[int, int]:
    return (_SOURCE_RANK.get(hit.source, 99), hit.chapter_no if hit.chapter_no is not None else 0)


def _snippet_key(hit: SearchHit) -> str:
    if hit.source == SOURCE_DRAFT:
        return f"draft:{hit.chapter_no}"
    if hit.source == SOURCE_KB:
        return "kb"
    return hit.chapter_id or "original"


def search_workspace(query: str, *, sources: Optional[List[str]] = None) -> SearchResult:
    """在**当前 ``use_workspace`` 线程上下文**里跨章检索。

    调用方必须已进入 ``with use_workspace(name):``——本函数只调 ``paths.*`` 纯函数，
    不接收 workspace name（避免纯函数被 workspace 上下文污染、难测）。任何输入都返回
    ``SearchResult``，绝不抛异常。

    ``sources`` 语义：``None`` = 默认三语料全搜；显式列表 = 仅搜其中的有效来源
    （空列表 = 一个都不搜，返回空结果——供「全部取消勾选」场景用）。"""

    if sources is None:
        active = list(_ALL_SOURCES)
    else:
        active = [s for s in sources if s in _ALL_SOURCES]
    raw = (query or "").strip()
    reasons: List[str] = []
    if len(raw) > MAX_QUERY_LEN:
        raw = raw[:MAX_QUERY_LEN]
        reasons.append("query_len")
    if len(raw) < MIN_QUERY_LEN:
        return SearchResult(query=raw, total_matches=0, hit_count=0, hits=[])
    needle_lower = raw.lower()

    hits: List[SearchHit] = []
    if SOURCE_ORIGINAL in active:
        hits += _search_original(needle_lower)
    if SOURCE_DRAFT in active:
        hits += _search_draft(needle_lower)
    if SOURCE_KB in active:
        hits += _search_kb(needle_lower)

    hits.sort(key=_sort_key)   # 稳定排序：组内保持插入序（原文=manifest 序、续写=章号序）
    # iter076（codex 审查 iter075 #5）：总命中数在截断**前**求和——「共 N 处命中」是
    # 全局真实数；hits/hit_count 才是截断后的展示面（truncated_reasons 含 "chapters"）。
    total = sum(h.match_count for h in hits)
    if len(hits) > MAX_CHAPTERS:
        hits = hits[:MAX_CHAPTERS]
        reasons.append("chapters")

    # 片段触顶 reason 从**最终存活 hits** 派生——被 chapters 上限丢弃的章不会留悬空 reason。
    for h in hits:
        if h.match_count > len(h.snippets):
            reasons.append("snippets:" + _snippet_key(h))
    return SearchResult(
        query=raw,
        total_matches=total,
        hit_count=len(hits),
        hits=hits,
        truncated=bool(reasons),
        truncated_reasons=sorted(set(reasons)),
    )
