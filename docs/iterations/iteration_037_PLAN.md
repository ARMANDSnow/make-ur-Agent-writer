# Iter 037 · drama 4 站向导前 2 站 + 创作规范快照

> **文档性质**：Codex 执行前的施工单。
>
> **执行人**：Codex（§A 全部 13 子项）+ Claude（§B 创作内容，与 Codex 无关）
> **验收人**：Claude（代码级 + 单测 + dispatcher，沙箱内全程可跑）
> **基线**：commit `68f17a5` (Iteration 036 acceptance)
> **配套文档**：
> - `docs/product/short_drama_module.md` v1
> - `docs/product/short_drama_creation_standard.md` v1（agent system prompt 之源）

---

## 1. Context（为什么做这一轮）

iter 036 把 drama 模块的"地基"打完（`workspace.type` / wizard type 分支 / sidebar 函数化 / type-aware route guard / drama overview 占位）。**iter 037 起进入真正的业务逻辑**：drama 4 站审查向导（核心设定 → 钩子 → 分镜 → 角色）的**前 2 站** + 让 LLM agent 读取「创作规范快照」作 system prompt 之源。

按 `short_drama_module.md` v1 §7 拆分，本轮：
- **iter 037（本轮）** = 站 ① 核心设定 + 站 ② 钩子 + 创作规范快照机制 + drama wizard 5 字段表单
- iter 038 = 站 ③ 分镜 + 站 ④ 角色 + AI 绘画 client + Comfy 导出
- iter 039 = drama_reviewer + 4 种导出 + drama Insights

**本轮严格 mock-only**。真模型接入留给 iter 040+。

**本轮严格保持 novel + drama overview/jobs/trash 行为零回归**。iter 036 baseline 是 488 测试通过 + 沙箱 6 ERROR；本轮 commit 前确认沙箱 6 ERROR **完全不变**（新增测试让总数上升）。

iter 037 沿用 iter 035 同款"§A Codex 骨架 + §B Claude 创作内容"双轨制 —— Codex 不擅长写创作内容判断，让他写骨架更稳。

---

## 2. Scope

### §A. Codex 范围（骨架 + 框架 + UI + 测试）

| # | 子项 | 主改动 | 复杂度 |
|---|---|---|---|
| **A1** | drama wizard 5 字段表单升级（workspace 名 + 题材描述 + 赛道 5 选 1 + 集数 + 单集时长）+ 落 `data/wizard_input.json` | `wizard.py` + `templates.py` + `static.py` | 中 |
| **A2** | drama workspace 创建时复制创作规范快照 → `data/creation_standard.snapshot.md` | `cli_workspace.py` + `wizard.py` | 小 |
| **A3** | 新建 `src/drama_planner.py`（站 ① agent 框架）：mock 模式 fixture-driven；真模型 stub | 新建 ~120 行 | 中 |
| **A4** | 新建 `src/hook_designer.py`（站 ② agent 框架）：mock fixture-driven 出 3 候选 | 新建 ~80 行 | 小 |
| **A5** | 新建 `prompts/drama/drama_planner.txt` + `hook_designer.txt`（**仅框架占位**，文案 `"see creation_standard for craft rules"`） | 新建 2 文件 | 小 |
| **A6** | 新建 `src/web/drama_view.py`（聚合站状态数据给 API） | 新建 ~80 行 | 小 |
| **A7** | 新页面 `/w/<name>/write`（4 站 tab：前 2 站可用、后 2 站 empty-state "iter 038 起开放"） | `templates.py` + `routes.py` + `static.py` | 中 |
| **A8** | 新 API：`POST /api/workspace/<name>/drama/plan` / `POST .../drama/hooks` / `PUT .../drama/setup` | `routes.py` ~80 行 | 中 |
| **A9** | `_SECTIONS_DRAMA` 改 `[overview, write, jobs]`（升级 iter 036 测试断言为 3 项） | `templates.py` 1 行 + test 1 处 | 极小 |
| **A10** | drama overview 升级为"进度看板"（显示当前在哪一站、各站完成状态） | `templates.py` ~80 行 | 中 |
| **A11** | `agents.yaml` 加 `drama_agents` 段（`provider: mock_only`） | `agents.yaml` ~30 行 | 小 |
| **A12** | mock fixtures 占位 × 10（`tests/fixtures/drama/track_<track>_<station>.json`） | 新建 10 文件 | 小 |
| **A13** | 测试覆盖：~6 条边界 + 主路径 | `tests/test_drama_*.py` ~300 行 | 中 |

**§A 预计代码量**：~1200 行 src + ~300 行 tests + ~250 行 prompts/fixtures = **Codex 90-120min**

### §B. Claude 范围（创作内容，与 Codex 无关）

| # | 子项 | 文件 | 谁写 |
|---|---|---|---|
| **B1** | 5 赛道 × 2 fixture = **10 个真实创作内容 fixture**（按 `short_drama_creation_standard.md` 严格自洽：霸总 / 重生 / 推理 / 系统 / 觉醒 各赛道一个 setup + 一个 3 候选 hook） | 替换 §A12 的占位 | Claude（Codex commit 后） |
| **B2** | `prompts/drama/drama_planner.txt` + `hook_designer.txt` **真实 system prompt 内容**（参照 `short_drama_creation_standard.md` §八骨架，注入"飞天奖编剧 + AI 短剧导演"身份） | 替换 §A5 的占位 | Claude（Codex commit 后） |

**§B 不阻塞 Codex**：Codex 先用占位跑通骨架；Claude 在 Codex commit 后用真实内容替换。替换不改 schema，Codex 测试不会破。

---

## §A.1 drama wizard 5 字段表单升级

### A.1.1 后端：扩展 `wizard.start_drama_workspace`

改 `src/web/wizard.py`：

```python
import json
from pathlib import Path

# iter 037: track whitelist (与 short_drama_creation_standard.md §七 对齐)
DRAMA_TRACKS = frozenset({"霸总", "重生", "推理", "系统", "觉醒"})
DRAMA_DURATIONS = frozenset({30, 60, 90, 120})

def start_drama_workspace(body: bytes, content_type: str) -> Tuple[int, str, bytes]:
    """POST /api/wizard/drama-start handler (iter 037 升级).

    Body: JSON ``{
      "workspace": "<name>",
      "topic": "<题材描述, 1-500 字>",
      "track": "霸总" | "重生" | "推理" | "系统" | "觉醒",
      "episode_count": <int, 1-100>,
      "episode_duration_seconds": 30 | 60 | 90 | 120
    }``

    iter 036 行为：仅创建空骨架。
    iter 037 升级：
      1. 落 ``data/wizard_input.json`` 保存 5 字段
      2. 复制 ``docs/product/short_drama_creation_standard.md`` 到
         ``data/creation_standard.snapshot.md``（A2）
      3. 仍不调 LLM，不返 job_id
    """
    if "application/json" not in (content_type or "").lower():
        return _json(415, {"error": "Content-Type must be application/json"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})

    # Field validation
    name = payload.get("workspace")
    if not isinstance(name, str) or not name.strip():
        return _json(400, {"error": "missing or invalid 'workspace'"})
    name = name.strip()
    if not _validate_name(name):
        return _json(400, {"error": "invalid workspace name"})

    topic = payload.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        return _json(400, {"error": "missing or invalid 'topic'"})
    if len(topic) > 500:
        return _json(400, {"error": "'topic' too long (max 500 chars)"})

    track = payload.get("track")
    if track not in DRAMA_TRACKS:
        return _json(400, {"error": f"'track' must be one of {sorted(DRAMA_TRACKS)}"})

    ep_count = payload.get("episode_count")
    if not isinstance(ep_count, int) or not (1 <= ep_count <= 100):
        return _json(400, {"error": "'episode_count' must be an int 1-100"})

    ep_dur = payload.get("episode_duration_seconds")
    if ep_dur not in DRAMA_DURATIONS:
        return _json(400, {"error": f"'episode_duration_seconds' must be one of {sorted(DRAMA_DURATIONS)}"})

    # Create skeleton (iter 036 logic)
    try:
        result = init_workspace(name, type="drama")
    except FileExistsError:
        return _json(409, {"error": f"workspace already exists: {name}"})
    except (OSError, ValueError) as exc:
        return _json(500, {"error": f"failed to create workspace: {exc}"})

    # iter 037 A1: persist wizard input
    wizard_input_path = paths.WORKSPACE_DIR / name / "data" / "wizard_input.json"
    wizard_input = {
        "workspace": name,
        "topic": topic,
        "track": track,
        "episode_count": ep_count,
        "episode_duration_seconds": ep_dur,
        "schema_version": 1,
    }
    wizard_input_path.write_text(
        json.dumps(wizard_input, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # iter 037 A2: snapshot creation standard
    _snapshot_creation_standard(name)

    return _json(200, {"name": result["name"], "type": result["type"]})


def _snapshot_creation_standard(workspace_name: str) -> None:
    """Copy docs/product/short_drama_creation_standard.md to
    workspaces/<name>/data/creation_standard.snapshot.md.

    Raises OSError if source is missing (we treat that as a workspace
    creation failure — drama agent cannot run without the snapshot).
    """
    repo_root = Path(__file__).resolve().parents[2]  # src/web/ → src/ → repo root
    src = repo_root / "docs" / "product" / "short_drama_creation_standard.md"
    if not src.is_file():
        raise OSError(f"creation standard missing: {src}")
    dst = paths.WORKSPACE_DIR / workspace_name / "data" / "creation_standard.snapshot.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())  # bytes copy preserves encoding
```

> **Codex 注意**：
> - 不要把 `_snapshot_creation_standard` 放进 `cli_workspace.init_workspace`（那是 type-agnostic 的；drama-specific 操作放 wizard 层）。
> - iter 036 的旧 `start_drama_workspace` 整段替换；不要兼容老的 1 字段表单。

### A.1.2 前端：wizard `panel-drama` 改 5 字段表单

改 `templates.render_wizard` 里 `panel-drama` 部分：

```html
<section class="card" id="panel-drama" hidden>
  <div class="card-header"><h3 class="ornament">第 1 步 · 短剧 workspace</h3></div>
  <div class="card-body">
    <form id="drama-form" class="stack">
      <div class="field">
        <label>workspace 名</label>
        <input name="workspace" required pattern="..." title="...">
      </div>
      <div class="field">
        <label>题材描述（1-500 字）</label>
        <textarea name="topic" rows="3" maxlength="500" required
          placeholder="例：26 岁女主被未婚夫抛弃当晚，重生回三年前同一天的早晨，决定亲手把对方在商场上一步步打回原形"></textarea>
      </div>
      <div class="field">
        <label>赛道</label>
        <div class="cluster">
          <label class="field-check"><input type="radio" name="track" value="霸总" required> 霸总</label>
          <label class="field-check"><input type="radio" name="track" value="重生"> 重生</label>
          <label class="field-check"><input type="radio" name="track" value="推理"> 推理</label>
          <label class="field-check"><input type="radio" name="track" value="系统"> 系统</label>
          <label class="field-check"><input type="radio" name="track" value="觉醒"> 觉醒</label>
        </div>
      </div>
      <div class="form-grid-2">
        <div class="field">
          <label>集数（1-100）</label>
          <input name="episode_count" type="number" min="1" max="100" value="12" required>
        </div>
        <div class="field">
          <label>单集时长（秒）</label>
          <div class="cluster">
            <label class="field-check"><input type="radio" name="episode_duration_seconds" value="30"> 30</label>
            <label class="field-check"><input type="radio" name="episode_duration_seconds" value="60" checked> 60</label>
            <label class="field-check"><input type="radio" name="episode_duration_seconds" value="90"> 90</label>
            <label class="field-check"><input type="radio" name="episode_duration_seconds" value="120"> 120</label>
          </div>
        </div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>
        <button type="submit" class="btn btn-primary">创建并进入续写</button>
      </div>
    </form>
    <div id="drama-error"></div>
  </div>
</section>
```

### A.1.3 JS：`JS_WIZARD` 的 drama 提交逻辑改成 5 字段

```javascript
if (dramaForm) {
  dramaForm.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    dramaErrBox.innerHTML = "";
    const fd = new FormData(dramaForm);
    const payload = {
      workspace: (fd.get("workspace") || "").trim(),
      topic: (fd.get("topic") || "").trim(),
      track: fd.get("track") || "",
      episode_count: Number(fd.get("episode_count") || 0),
      episode_duration_seconds: Number(fd.get("episode_duration_seconds") || 0),
    };
    const submitBtn = dramaForm.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    try {
      const res = await fetch("/api/wizard/drama-start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        dramaErrBox.innerHTML = '<div class="alert error">创建失败 (' + res.status + "): " +
          escapeHtml(data.error || "") + "</div>";
        submitBtn.disabled = false;
        return;
      }
      sessionStorage.setItem("__pending_toast",
        JSON.stringify({ kind: "info", msg: "短剧 workspace 已创建：" + data.name }));
      // iter 037: 跳转到 write step=setup（不是 / 概览）
      window.location.href = "/w/" + encodeURIComponent(data.name) + "/write?step=setup";
    } catch (err) {
      dramaErrBox.innerHTML = '<div class="alert error">网络错误: ' + escapeHtml(String(err)) + "</div>";
      submitBtn.disabled = false;
    }
  });
}
```

---

## §A.2 创作规范快照机制

详见 §A.1.1 中的 `_snapshot_creation_standard` 函数。**关键约束**（写入 §3 红线）：

- 快照源：`docs/product/short_drama_creation_standard.md`（仓库根相对路径）
- 快照目标：`workspaces/<name>/data/creation_standard.snapshot.md`
- 缺源文件时 wizard 提交直接 500（工程错误，不容错）
- 一旦快照落盘，**任何 drama agent 只读这份快照，绝不读全局文件** —— 保证已生成内容可复现

---

## §A.3 `src/drama_planner.py`（站 ① agent）

```python
"""iter 037: drama station ① — 核心设定 agent.

Mock-first: 真模型路径在 iter 040+ 接入。本轮 mock 模式按
``wizard_input.json`` 里的 ``track`` 字段在
``tests/fixtures/drama/track_<track>_setup.json`` 查 fixture。

Snapshot consumption: drama_planner 加载时把
``workspaces/<name>/data/creation_standard.snapshot.md`` 全文塞进
system prompt 头部 —— 这是 LLM 的"身份与铁律之源"。即使本轮 mock
不调 LLM，prompt 拼装代码仍然走通，便于 iter 040+ 切换真模型。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from . import paths
from .utils import read_json_optional


# Track 拼音映射 (iter 037 §3 red line)
TRACK_PINYIN = {
    "霸总": "bazhong",
    "重生": "chongsheng",
    "推理": "tuili",
    "系统": "xitong",
    "觉醒": "juexing",
}

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "drama"


def run(workspace: str, *, mock: bool = True) -> Dict[str, Any]:
    """Run station ① for ``workspace``.

    Returns the ``core_setup`` JSON shape (see short_drama_module.md v1
    §2.2). Caller persists this to ``outputs/episodes/episode_01.setup.json``.
    """
    if not mock:
        raise NotImplementedError(
            "real-model drama planning arrives in iter 040+"
        )

    wizard_input = _load_wizard_input(workspace)
    track = wizard_input["track"]
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    # Build system prompt (consume snapshot, even though mock won't call LLM)
    snapshot = _load_snapshot(workspace)
    prompt_template = _load_prompt_template("drama_planner")
    system_prompt = _compose_prompt(snapshot, prompt_template, wizard_input)
    _log_prompt(workspace, "drama_planner", system_prompt)

    # Mock path: look up fixture
    return _load_fixture(track, "setup")


def _load_wizard_input(workspace: str) -> Dict[str, Any]:
    path = paths.WORKSPACE_DIR / workspace / "data" / "wizard_input.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing wizard_input.json for workspace {workspace!r}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_snapshot(workspace: str) -> str:
    """Load creation_standard.snapshot.md. Missing snapshot raises —
    we refuse to run a drama agent on a workspace without it because
    that would silently skip the craft rules."""
    path = paths.WORKSPACE_DIR / workspace / "data" / "creation_standard.snapshot.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing creation_standard.snapshot.md for workspace {workspace!r}; "
            f"this workspace cannot run drama agents"
        )
    return path.read_text(encoding="utf-8")


def _load_prompt_template(name: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "prompts" / "drama" / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def _compose_prompt(snapshot: str, template: str, wizard_input: Dict[str, Any]) -> str:
    """Compose system prompt: snapshot + template + user input.

    Template can reference {snapshot} / {topic} / {track} / {episode_count} /
    {episode_duration_seconds} via str.format-style placeholders.
    """
    return template.format(
        snapshot=snapshot,
        topic=wizard_input.get("topic", ""),
        track=wizard_input.get("track", ""),
        episode_count=wizard_input.get("episode_count", 0),
        episode_duration_seconds=wizard_input.get("episode_duration_seconds", 0),
    )


def _log_prompt(workspace: str, agent: str, prompt: str) -> None:
    """Log the assembled prompt to logs/drama_prompts.jsonl for audit
    (iter 037 introduces drama prompt provenance trace)."""
    log_path = paths.WORKSPACE_DIR / workspace / "logs" / "drama_prompts.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    import time
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agent": agent,
        "prompt_chars": len(prompt),
        "snapshot_chars_estimate": prompt.count("3 秒法则") and -1 or len(prompt) // 2,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_fixture(track: str, station: str) -> Dict[str, Any]:
    """Load tests/fixtures/drama/track_<track>_<station>.json (pinyin-keyed)."""
    pinyin = TRACK_PINYIN.get(track)
    if not pinyin:
        raise ValueError(f"unknown track: {track!r}")
    path = FIXTURE_DIR / f"track_{pinyin}_{station}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing fixture: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
```

---

## §A.4 `src/hook_designer.py`（站 ② agent）

```python
"""iter 037: drama station ② — 钩子设计 agent.

Mock-first 同 drama_planner. 输入是 station ① 已落盘的
``episode_01.setup.json``；输出是 3 个钩子候选（情绪 / 悬念 / 反差 各 1）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from . import paths
from .drama_planner import (
    _load_wizard_input,
    _load_snapshot,
    _load_prompt_template,
    _compose_prompt,
    _log_prompt,
    _load_fixture,
)


def run(workspace: str, *, mock: bool = True) -> Dict[str, Any]:
    """Run station ② for ``workspace``.

    Returns ``{"hooks": [{"type": "情绪钩|悬念钩|反差钩",
                          "content": "<一句话>"}, ...]}``，正好 3 个候选。
    """
    if not mock:
        raise NotImplementedError(
            "real-model drama hook design arrives in iter 040+"
        )

    setup_path = paths.WORKSPACE_DIR / workspace / "outputs" / "episodes" / "episode_01.setup.json"
    if not setup_path.is_file():
        raise FileNotFoundError(
            f"station ① must complete before station ②; "
            f"missing {setup_path}"
        )
    setup = json.loads(setup_path.read_text(encoding="utf-8"))

    wizard_input = _load_wizard_input(workspace)
    track = wizard_input["track"]

    # Build prompt (snapshot consumption identical to drama_planner)
    snapshot = _load_snapshot(workspace)
    prompt_template = _load_prompt_template("hook_designer")
    system_prompt = _compose_prompt(snapshot, prompt_template, wizard_input)
    _log_prompt(workspace, "hook_designer", system_prompt)

    return _load_fixture(track, "hooks")
```

---

## §A.5 prompts 占位

**Codex 范围**：只写框架，**禁止写具体创作规则**（Claude §B 替换）。

`prompts/drama/drama_planner.txt`：

```
{snapshot}

---

你是 drama_planner agent。你的任务是基于以下用户输入，产出第 1 集的「核心设定」JSON。

用户输入：
- 题材：{topic}
- 赛道：{track}
- 集数：{episode_count}
- 单集时长：{episode_duration_seconds} 秒

输出 JSON schema（严格）：
{{
  "episode_no": 1,
  "season_no": 1,
  "title": "<≤ 12 字>",
  "logline": "<一句话钩子，≤ 25 字>",
  "track": "{track}",
  "target_duration_seconds": {episode_duration_seconds},
  "core_setup": {{
    "protagonist": "<一句话主角介绍，含年龄 / 身份 / 关键性格>",
    "antagonist": "<一句话反派介绍，含年龄 / 身份 / 与主角对照轴>",
    "emotional_hook": "<一句话情绪钩子>"
  }}
}}

# placeholder, see creation_standard for craft rules
# 本段在 iter 037 §B（Claude）替换为真实创作规则
```

`prompts/drama/hook_designer.txt`：

```
{snapshot}

---

你是 hook_designer agent。基于已确定的核心设定，产出 3 个钩子候选（情绪 / 悬念 / 反差 各 1）。

用户输入：
- 题材：{topic}
- 赛道：{track}

输出 JSON schema（严格）：
{{
  "hooks": [
    {{"type": "情绪钩", "content": "<≤ 30 字>"}},
    {{"type": "悬念钩", "content": "<≤ 30 字>"}},
    {{"type": "反差钩", "content": "<≤ 30 字>"}}
  ]
}}

# placeholder, see creation_standard for craft rules
# 本段在 iter 037 §B（Claude）替换为真实创作规则
```

> **Codex 注意**：`{snapshot}` 是 Python str.format 占位符；agent `_compose_prompt` 会把整份 `creation_standard.snapshot.md` 塞进来。**不要在 prompt 文件里手抄创作规则的任何具体内容** —— snapshot 注入已经把规则带进来了。

---

## §A.6 `src/web/drama_view.py`

```python
"""iter 037: aggregate drama workspace state for the /w/<name>/write
4-station progress dashboard.

Pure read-only. No LLM calls.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .. import paths
from ..utils import read_json_optional


STATIONS = ["setup", "hook", "storyboard", "characters"]


def collect_drama_progress(workspace: str) -> Dict[str, Any]:
    """Return drama workspace 4-station progress shape:

      {
        "workspace": "<name>",
        "wizard_input": {... or None},
        "stations": [
          {"id": "setup",       "label": "核心设定", "status": "done|todo|locked", "data": {...} or None},
          {"id": "hook",        "label": "钩子",     "status": "done|todo|locked", "data": {...} or None},
          {"id": "storyboard",  "label": "分镜",     "status": "locked",            "data": None},
          {"id": "characters",  "label": "角色",     "status": "locked",            "data": None},
        ],
      }

    Station status rules (iter 037 K5):
      - setup done = setup file exists with core_setup.protagonist
      - hook done = setup file contains "hook" field (means user selected one)
      - storyboard/characters = "locked" until iter 038
    """
    root = paths.WORKSPACE_DIR / workspace
    wizard_input_path = root / "data" / "wizard_input.json"
    wizard_input = read_json_optional(wizard_input_path, None) if wizard_input_path.exists() else None

    setup_path = root / "outputs" / "episodes" / "episode_01.setup.json"
    setup_data = read_json_optional(setup_path, None) if setup_path.exists() else None

    setup_done = bool(
        setup_data
        and isinstance(setup_data.get("core_setup"), dict)
        and setup_data["core_setup"].get("protagonist")
    )
    hook_done = bool(
        setup_data
        and isinstance(setup_data.get("hook"), dict)
        and setup_data["hook"].get("type")
    )

    return {
        "workspace": workspace,
        "wizard_input": wizard_input,
        "stations": [
            {
                "id": "setup",
                "label": "核心设定",
                "status": "done" if setup_done else "todo",
                "data": setup_data.get("core_setup") if (setup_data and setup_done) else None,
            },
            {
                "id": "hook",
                "label": "钩子",
                "status": "done" if hook_done else ("todo" if setup_done else "locked"),
                "data": setup_data.get("hook") if (setup_data and hook_done) else None,
            },
            {
                "id": "storyboard",
                "label": "分镜",
                "status": "locked",
                "data": None,
            },
            {
                "id": "characters",
                "label": "角色",
                "status": "locked",
                "data": None,
            },
        ],
    }
```

---

## §A.7 `/w/<name>/write` 4 站 tab 页面

### A.7.1 routes.py 新增 handler

```python
def render_workspace_write_page(name: str) -> Tuple[int, str, bytes]:
    """iter 037: drama-only /w/<name>/write page.

    Returns 404 for novel workspaces (this is drama-only).
    Query: ``?step=setup|hook|storyboard|characters`` controls which
    tab opens by default (validated via _ALLOWED_TAB_KEYS).
    """
    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read
    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{name}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_write(name, list_workspaces()))
```

注册 `_ROUTES`：

```python
("GET", re.compile(r"^/w/(?P<name>[^/]+)/write/?$"),
 lambda name, **_: render_workspace_write_page(name)),
```

### A.7.2 templates.render_workspace_write

```python
def render_workspace_write(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">续写</p>'
        '<h1>4 站审查向导</h1>'
        '<p class="muted">核心设定 → 钩子 → 分镜 → 角色，每站 AI 生成 → 你改 → 下一站。</p>'
        '</div>'
        '<div id="drama-write-progress" class="cluster"></div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="setup">① 核心设定</button>'
        '<button class="tab" data-tab="hook">② 钩子</button>'
        '<button class="tab" data-tab="storyboard">③ 分镜</button>'
        '<button class="tab" data-tab="characters">④ 角色</button>'
        '</div>'
        '<div class="tab-panel active" id="tab-setup" data-station-pane="setup">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-hook" data-station-pane="hook">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-storyboard" data-station-pane="storyboard">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>分镜表 — iter 038 起开放</h3>'
        '<p class="muted">本轮 iter 037 仅实现核心设定 + 钩子。'
        '分镜（镜号 / 景别 / 运镜 / 时长 / 画面内容 / 旁白 / 台词）在下一轮上线。</p>'
        '</div></div>'
        '<div class="tab-panel" id="tab-characters" data-station-pane="characters">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>角色设定表 — iter 038 起开放</h3>'
        '<p class="muted">角色 LoRA-ready prompt 生成 + 内置 AI 绘画预览图在 iter 038 上线。</p>'
        '</div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 续写",
        page_kind="drama_write",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("续写", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="write"),
        workspace=name,
    )
```

### A.7.3 JS：drama_write 页面交互

加在 `JS_DASHBOARD` 末尾：

```javascript
async function initDramaWrite() {
  bindHashTabs();  // reuse iter 034 hash deep-link
  await loadStationSetup();
  await loadStationHooks();
  await loadDramaProgress();
}

async function loadDramaProgress() {
  const box = document.getElementById("drama-write-progress");
  if (!box) return;
  try {
    const data = await fetchJson(wsUrl("/drama/progress"));
    const items = (data.stations || []).map(function (s) {
      const cls = s.status === "done" ? "ready" :
                  s.status === "locked" ? "blocked" : "warn";
      return '<span class="badge ' + cls + '">' + escapeHtml(s.label) +
        " · " + escapeHtml(s.status) + "</span>";
    });
    box.innerHTML = items.join("");
  } catch (err) {
    box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
  }
}

async function loadStationSetup() {
  const pane = document.querySelector('[data-station-pane="setup"]');
  if (!pane) return;
  pane.innerHTML = skeleton(3);
  try {
    const data = await fetchJson(wsUrl("/drama/progress"));
    const station = (data.stations || []).find((s) => s.id === "setup");
    pane.innerHTML = renderStationSetup(station, data.wizard_input);
    bindStationSetupActions();
  } catch (err) {
    pane.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
  }
}

function renderStationSetup(station, wizardInput) {
  const status = station ? station.status : "todo";
  const data = station ? station.data : null;
  let html = '<div class="card"><div class="card-header"><h3 class="ornament">站 ① 核心设定</h3>' +
    '<span class="badge ' + (status === "done" ? "ready" : "warn") + '">' + status + '</span></div>' +
    '<div class="card-body stack">';
  if (wizardInput) {
    html += '<div class="kv-list compact">' +
      '<div class="k">题材</div><div class="v">' + escapeHtml(wizardInput.topic || "") + "</div>" +
      '<div class="k">赛道</div><div class="v"><code>' + escapeHtml(wizardInput.track || "") + "</code></div>" +
      '<div class="k">集数</div><div class="v">' + (wizardInput.episode_count || 0) + "</div>" +
      '<div class="k">单集时长</div><div class="v">' + (wizardInput.episode_duration_seconds || 0) + " 秒</div>" +
      '</div>';
  }
  if (data) {
    html += '<form id="station-setup-form" class="stack">' +
      '<div class="field"><label>logline</label>' +
      '<textarea name="logline" rows="2">' + escapeHtml(data.logline || "") + "</textarea></div>" +
      '<div class="field"><label>protagonist</label>' +
      '<textarea name="protagonist" rows="2">' + escapeHtml((data.core_setup || data).protagonist || "") + "</textarea></div>" +
      '<div class="field"><label>antagonist</label>' +
      '<textarea name="antagonist" rows="2">' + escapeHtml((data.core_setup || data).antagonist || "") + "</textarea></div>" +
      '<div class="field"><label>emotional_hook</label>' +
      '<textarea name="emotional_hook" rows="2">' + escapeHtml((data.core_setup || data).emotional_hook || "") + "</textarea></div>" +
      '<div class="form-actions">' +
      '<button type="button" class="btn btn-secondary" id="regenerate-setup">重新生成</button>' +
      '<button type="submit" class="btn btn-primary">保存并进入站 ② →</button>' +
      '</div></form>';
  } else {
    html += '<div class="empty-state">' +
      '<span class="ornament">✦</span>' +
      '<h3>等待生成核心设定</h3>' +
      '<p class="muted">点击"生成"让 AI 基于你的题材产出主角 / 反派 / 情绪钩子。</p>' +
      '<button type="button" class="btn btn-primary" id="generate-setup">▸ 生成核心设定</button>' +
      "</div>";
  }
  html += "</div></div>";
  return html;
}

function bindStationSetupActions() {
  const genBtn = document.getElementById("generate-setup");
  if (genBtn) {
    genBtn.addEventListener("click", async function () {
      genBtn.disabled = true;
      try {
        await postJson(wsUrl("/drama/plan"), {});
        showToast("核心设定已生成", "info");
        await loadStationSetup();
        await loadDramaProgress();
      } catch (err) {
        showToast("生成失败：" + err.message, "error");
        genBtn.disabled = false;
      }
    });
  }
  const regenBtn = document.getElementById("regenerate-setup");
  if (regenBtn) {
    regenBtn.addEventListener("click", async function () {
      regenBtn.disabled = true;
      try {
        await postJson(wsUrl("/drama/plan"), {});
        showToast("核心设定已重新生成", "info");
        await loadStationSetup();
      } catch (err) {
        showToast("重新生成失败：" + err.message, "error");
        regenBtn.disabled = false;
      }
    });
  }
  const form = document.getElementById("station-setup-form");
  if (form) {
    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const payload = {
        logline: form.elements.logline.value,
        protagonist: form.elements.protagonist.value,
        antagonist: form.elements.antagonist.value,
        emotional_hook: form.elements.emotional_hook.value,
      };
      try {
        await fetch(wsUrl("/drama/setup"), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        showToast("已保存，进入站 ②", "info");
        history.replaceState(null, "", "#hook");
        document.querySelector('.tab[data-tab="hook"]').click();
      } catch (err) {
        showToast("保存失败：" + err.message, "error");
      }
    });
  }
}

async function loadStationHooks() {
  const pane = document.querySelector('[data-station-pane="hook"]');
  if (!pane) return;
  pane.innerHTML = skeleton(3);
  try {
    const data = await fetchJson(wsUrl("/drama/progress"));
    const station = (data.stations || []).find((s) => s.id === "hook");
    if (station && station.status === "locked") {
      pane.innerHTML = '<div class="alert info">请先完成站 ①</div>';
      return;
    }
    pane.innerHTML = renderStationHooks(station);
    bindStationHooksActions();
  } catch (err) {
    pane.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
  }
}

function renderStationHooks(station) {
  const status = station ? station.status : "todo";
  const data = station ? station.data : null;
  let html = '<div class="card"><div class="card-header"><h3 class="ornament">站 ② 钩子</h3>' +
    '<span class="badge ' + (status === "done" ? "ready" : "warn") + '">' + status + '</span></div>' +
    '<div class="card-body stack">';
  if (!data) {
    html += '<div class="empty-state">' +
      '<span class="ornament">✦</span>' +
      '<h3>等待生成钩子候选</h3>' +
      '<p class="muted">AI 会出 3 个候选：情绪钩 / 悬念钩 / 反差钩，你选 1 个继续。</p>' +
      '<button type="button" class="btn btn-primary" id="generate-hooks">▸ 生成 3 个钩子</button>' +
      "</div>";
  } else {
    // already selected
    html += '<div class="kv-list compact">' +
      '<div class="k">type</div><div class="v"><code>' + escapeHtml(data.type || "") + "</code></div>" +
      '<div class="k">content</div><div class="v">' + escapeHtml(data.content || "") + "</div>" +
      '</div>' +
      '<div class="alert info">站 ② 已锁定。下一站「分镜」iter 038 起开放。</div>';
  }
  html += "</div></div>";
  return html;
}

function bindStationHooksActions() {
  const btn = document.getElementById("generate-hooks");
  if (!btn) return;
  btn.addEventListener("click", async function () {
    btn.disabled = true;
    try {
      const data = await postJson(wsUrl("/drama/hooks"), {});
      const hooks = data.hooks || [];
      // show 3 cards inline; user picks 1
      const pane = document.querySelector('[data-station-pane="hook"]');
      pane.innerHTML = '<div class="card"><div class="card-header"><h3 class="ornament">3 个候选 — 选 1 个</h3></div>' +
        '<div class="card-body stack">' +
        hooks.map(function (h, i) {
          return '<div class="advisor-item">' +
            '<span class="type">' + escapeHtml(h.type || "") + "</span>" +
            '<div class="guidance">' + escapeHtml(h.content || "") + "</div>" +
            '<button class="btn btn-secondary btn-sm" data-hook-pick="' + i + '">选这个 →</button>' +
            '</div>';
        }).join("") +
        '</div></div>';
      pane.addEventListener("click", async function (ev) {
        const pick = ev.target.closest("[data-hook-pick]");
        if (!pick) return;
        const idx = Number(pick.getAttribute("data-hook-pick"));
        await fetch(wsUrl("/drama/setup"), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hook: hooks[idx] }),
        });
        showToast("钩子已锁定", "info");
        await loadStationHooks();
        await loadDramaProgress();
      });
    } catch (err) {
      showToast("生成失败：" + err.message, "error");
      btn.disabled = false;
    }
  });
}
```

Dispatcher 加：

```javascript
if (pageKind === "drama_write") return initDramaWrite();
```

**`_ALLOWED_TAB_KEYS` 扩展**：

```javascript
const _ALLOWED_TAB_KEYS = [
  "body", "review", "lint", "advisor", "history",
  "chapters", "outline", "decisions",
  // iter 037: drama write stations
  "setup", "hook", "storyboard", "characters",
];
```

---

## §A.8 4 个新 API

```python
def api_drama_progress(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/drama/progress."""
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .workspace_meta import read as _meta_read
    if _meta_read(name).get("type") != "drama":
        return _json(400, {"error": "drama-only endpoint"})
    from .drama_view import collect_drama_progress
    return _json(200, collect_drama_progress(name))


def api_drama_plan(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/drama/plan — run station ①."""
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .workspace_meta import read as _meta_read
    if _meta_read(name).get("type") != "drama":
        return _json(400, {"error": "drama-only endpoint"})

    from .. import drama_planner
    try:
        result = drama_planner.run(name, mock=True)
    except FileNotFoundError as exc:
        return _json(500, {"error": str(exc)})
    except (ValueError, NotImplementedError) as exc:
        return _json(400, {"error": str(exc)})

    # Persist to outputs/episodes/episode_01.setup.json
    setup_path = paths.WORKSPACE_DIR / name / "outputs" / "episodes" / "episode_01.setup.json"
    setup_path.parent.mkdir(parents=True, exist_ok=True)
    setup_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _clear_overview_cache()
    return _json(200, result)


def api_drama_hooks(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/drama/hooks — run station ②."""
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .workspace_meta import read as _meta_read
    if _meta_read(name).get("type") != "drama":
        return _json(400, {"error": "drama-only endpoint"})

    from .. import hook_designer
    try:
        result = hook_designer.run(name, mock=True)
    except FileNotFoundError as exc:
        return _json(500, {"error": str(exc)})
    except (ValueError, NotImplementedError) as exc:
        return _json(400, {"error": str(exc)})

    return _json(200, result)


def api_drama_setup_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/drama/setup — user edits.

    Body shape allows partial update:
      {"logline": ..., "protagonist": ..., "antagonist": ..., "emotional_hook": ...}
        → merged into setup.core_setup
      {"hook": {"type": ..., "content": ...}}
        → setup.hook = ...
    """
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .workspace_meta import read as _meta_read
    if _meta_read(name).get("type") != "drama":
        return _json(400, {"error": "drama-only endpoint"})

    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})

    setup_path = paths.WORKSPACE_DIR / name / "outputs" / "episodes" / "episode_01.setup.json"
    if not setup_path.is_file():
        return _json(400, {"error": "station ① must run first"})
    setup = json.loads(setup_path.read_text(encoding="utf-8"))

    core_keys = {"logline", "protagonist", "antagonist", "emotional_hook"}
    if any(k in payload for k in core_keys):
        cs = setup.setdefault("core_setup", {})
        if "logline" in payload:
            setup["logline"] = payload["logline"]  # logline lives at top level
        for k in ("protagonist", "antagonist", "emotional_hook"):
            if k in payload:
                cs[k] = payload[k]
    if "hook" in payload:
        if not isinstance(payload["hook"], dict):
            return _json(400, {"error": "'hook' must be an object"})
        setup["hook"] = payload["hook"]

    setup_path.write_text(
        json.dumps(setup, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _clear_overview_cache()
    return _json(200, {"saved": True})
```

注册 `_ROUTES`：

```python
("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/progress/?$"),
 lambda name, **_: api_drama_progress(name)),
("POST", re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/plan/?$"),
 lambda name, _body=b"", **_: api_drama_plan(name, _body)),
("POST", re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/hooks/?$"),
 lambda name, _body=b"", **_: api_drama_hooks(name, _body)),
("PUT", re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/setup/?$"),
 lambda name, _body=b"", **_: api_drama_setup_save(name, _body)),
```

---

## §A.9 `_SECTIONS_DRAMA` 升级 + iter 036 测试调整

`templates.py`：

```python
# iter 037: drama workspaces gain the write section. storyboard/characters/
# reviews/insights still wait for iter 038/039.
_SECTIONS_DRAMA: Sequence[tuple[str, str, str]] = (
    ("overview", "概览", ""),
    ("write", "续写", "write"),  # <-- iter 037 added
    ("jobs", "任务", "jobs"),
)
```

**iter 036 测试调整**（K6）— `tests/test_web_routes_get.py` 里：

```python
def test_drama_sidebar_only_exposes_overview_and_jobs(self) -> None:
    # Updated iter 037: drama sidebar now includes "write" (站 ① ② 向导)
    ...
    # 断言改为 3 项：overview / write / jobs
```

请把测试方法重命名为 `test_drama_sidebar_exposes_overview_write_jobs` 并更新断言。

---

## §A.10 drama overview 升级为进度看板

改 `templates._drama_overview_main`（iter 036 写过的占位）：

```python
def _drama_overview_main(name: str, meta: dict) -> str:
    created_at = escape(meta.get("created_at") or "（未记录）")
    return (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">作品 · 短剧</p>'
        f'<h1>{escape(name)}</h1>'
        '<p class="muted">drama 工作区。点击下方"进入续写"开始 4 站审查向导。</p>'
        '</div>'
        '<div class="cluster">'
        '<span class="badge no-dot" style="color:var(--amber-strong);background:var(--amber-soft);border-color:var(--amber-soft)">短剧</span>'
        '<button type="button" class="btn btn-danger btn-sm" id="delete-workspace-btn">删除作品…</button>'
        '</div>'
        '</header>'

        # progress dashboard
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">4 站进度</h2>'
        '<span class="hint">core_setup / hook 已完成进入下一站</span></div>'
        '<div id="drama-overview-progress" class="grid cols-2"></div>'
        '</section>'

        # next action card
        '<section class="section">'
        '<div class="next-action" id="drama-overview-next-action">'
        '<p class="eyebrow ornament">下一步</p>'
        '<h2 id="drama-next-headline">载入中…</h2>'
        f'<a class="btn btn-primary" href="/w/{escape(name)}/write?step=setup">▸ 进入续写</a>'
        '</div>'
        '</section>'

        # workspace meta (从 iter 036 保留)
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">workspace 元信息</h2></div>'
        '<div class="card"><div class="card-body">'
        '<div class="kv-list compact">'
        '<div class="k">type</div><div class="v"><code>drama</code></div>'
        f'<div class="k">created_at</div><div class="v"><code>{created_at}</code></div>'
        f'<div class="k">schema_version</div><div class="v"><code>{meta.get("schema_version", 0)}</code></div>'
        '</div>'
        '</div></div>'
        '</section>'
    )
```

JS 端在 `initWorkspaceOverview` 检测到 drama workspace（通过有 `drama-overview-progress` 元素而非 `overview-summary`）走 drama 分支：

```javascript
async function initWorkspaceOverview() {
  const dramaProgress = document.getElementById("drama-overview-progress");
  if (dramaProgress) {
    initDeleteWorkspace();
    await loadDramaOverview();
    return;
  }
  const summary = document.getElementById("overview-summary");
  if (!summary) {
    initDeleteWorkspace();
    return;
  }
  // ...原 novel 逻辑保留
}

async function loadDramaOverview() {
  const box = document.getElementById("drama-overview-progress");
  const headline = document.getElementById("drama-next-headline");
  try {
    const data = await fetchJson(wsUrl("/drama/progress"));
    box.innerHTML = (data.stations || []).map(function (s) {
      const cls = s.status === "done" ? "ready" :
                  s.status === "locked" ? "blocked" : "warn";
      return '<div class="card"><div class="card-body">' +
        '<div class="cluster">' +
        '<span class="eyebrow ornament">' + escapeHtml(s.id) + "</span>" +
        '<span class="badge ' + cls + '">' + escapeHtml(s.status) + "</span></div>" +
        '<h3>' + escapeHtml(s.label) + "</h3>" +
        "</div></div>";
    }).join("");
    const todo = (data.stations || []).find((s) => s.status === "todo");
    if (todo) {
      headline.textContent = "下一步：完成「" + todo.label + "」";
    } else {
      const allDone = (data.stations || []).every((s) => s.status === "done" || s.status === "locked");
      headline.textContent = allDone ? "前 2 站已完成 — 等待 iter 038 解锁分镜" : "继续 4 站向导";
    }
  } catch (err) {
    box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
  }
}
```

---

## §A.11 agents.yaml drama 段

```yaml
# iter 037: drama agents (mock-only this iter)
drama_agents:
  drama_planner:
    role: 站 ① 核心设定 agent
    provider: mock_only  # iter 040+ 改 openai / litellm
    system_prompt_base: docs/product/short_drama_creation_standard.md
    system_prompt_snapshot: data/creation_standard.snapshot.md  # workspace-relative
    prompt_template: prompts/drama/drama_planner.txt
    sections_required: [一, 二, 三, 六, 七, 八]
    mock_fixture_pattern: tests/fixtures/drama/track_{track_pinyin}_setup.json

  hook_designer:
    role: 站 ② 钩子设计 agent
    provider: mock_only
    system_prompt_base: docs/product/short_drama_creation_standard.md
    system_prompt_snapshot: data/creation_standard.snapshot.md
    prompt_template: prompts/drama/hook_designer.txt
    sections_required: [一, 二, 三, 七]
    mock_fixture_pattern: tests/fixtures/drama/track_{track_pinyin}_hooks.json
```

> **Codex 注意**：本轮 `LLMClient` 不读这段（drama agent 直接调 `mock=True` 路径）。但 yaml 段必须落盘，iter 040+ 切真模型时直接读。

---

## §A.12 Mock fixtures 占位 × 10

10 个文件路径（全部用拼音）：

```
tests/fixtures/drama/track_bazhong_setup.json
tests/fixtures/drama/track_bazhong_hooks.json
tests/fixtures/drama/track_chongsheng_setup.json
tests/fixtures/drama/track_chongsheng_hooks.json
tests/fixtures/drama/track_tuili_setup.json
tests/fixtures/drama/track_tuili_hooks.json
tests/fixtures/drama/track_xitong_setup.json
tests/fixtures/drama/track_xitong_hooks.json
tests/fixtures/drama/track_juexing_setup.json
tests/fixtures/drama/track_juexing_hooks.json
```

每个 setup fixture 模板（Codex 用占位，**不写真实创作内容**）：

```json
{
  "episode_no": 1,
  "season_no": 1,
  "title": "placeholder, see creation_standard",
  "logline": "placeholder, see creation_standard",
  "track": "霸总",
  "target_duration_seconds": 60,
  "core_setup": {
    "protagonist": "placeholder, see creation_standard",
    "antagonist": "placeholder, see creation_standard",
    "emotional_hook": "placeholder, see creation_standard"
  },
  "_codex_note": "iter 037 §B (Claude) will replace placeholder values with real creative content matching the track motif from short_drama_creation_standard.md §七"
}
```

每个 hooks fixture 模板：

```json
{
  "hooks": [
    {"type": "情绪钩", "content": "placeholder, see creation_standard"},
    {"type": "悬念钩", "content": "placeholder, see creation_standard"},
    {"type": "反差钩", "content": "placeholder, see creation_standard"}
  ],
  "_codex_note": "iter 037 §B (Claude) will replace placeholder values with real hook candidates matching the track motif"
}
```

记得每个 setup fixture 的 `track` 字段对应真实赛道名（霸总 / 重生 / 推理 / 系统 / 觉醒），不要全部填"霸总"。

---

## §A.13 测试覆盖

新建 / 扩展的测试文件：

```
tests/test_drama_planner.py          # 站 ① agent 测试 (新建)
tests/test_hook_designer.py          # 站 ② agent 测试 (新建)
tests/test_drama_view.py             # 进度聚合测试 (新建)
tests/test_drama_wizard_full_form.py # 5 字段表单 + 快照测试 (新建)
tests/test_web_routes_get.py         # 加 /w/<name>/write GET 测试
tests/test_web_routes_post.py        # 加 4 个新 API 测试
```

至少 30 个新测试。最重要的 8 条：

1. `test_drama_wizard_full_5_field_form_renders`（dispatcher + grep）
2. `test_drama_wizard_5_field_validation_rejects_empty_topic` (400)
3. `test_drama_wizard_5_field_validation_rejects_invalid_track` (400)
4. `test_drama_wizard_5_field_validation_rejects_invalid_episode_count` (400)
5. `test_drama_wizard_creates_snapshot_and_wizard_input_files`（落盘验证）
6. `test_drama_planner_mock_returns_fixture_per_track`（5 赛道各跑一遍）
7. `test_drama_planner_raises_when_snapshot_missing`（K10）
8. `test_agent_prompt_contains_snapshot_3_seconds_law`（K10：拼好的 prompt 含"3 秒法则"）

---

## §B. Claude 范围（与 Codex 无关）

> Codex 在本节范围**禁止读、改、grep**。

| # | 子项 | 文件 | 谁写 |
|---|---|---|---|
| B1 | 10 个真实创作内容 fixture（替换 §A12 占位） | `tests/fixtures/drama/*.json` | Claude 在 Codex commit 后 |
| B2 | 2 个真实 system prompt 文案（替换 §A5 占位） | `prompts/drama/{drama_planner,hook_designer}.txt` | Claude 在 Codex commit 后 |

§B 完成后 Claude 跑全套测试确保不破，然后单独 commit `iter 037 §B content`。

---

## 3. 工程铁律

### 🚨 不可逾越的红线

1. **现有 novel + drama overview/jobs/trash 行为零回归**。iter 036 全套 488 测试 + 沙箱 6 ERROR **完全不变**。本轮新增测试让通过总数上升，但不能让任何旧测试翻红。
2. **本轮严禁动 drama 站 ③ ④ 业务逻辑**。**严禁**新建以下文件：
   - `src/storyboard_builder.py`
   - `src/character_designer.py`
   - `src/ai_draw_client.py`
   - `src/comfy_workflow_exporter.py`
   - `src/drama_reviewer.py`
   - `src/web/tables.py`
   - `src/web/storyboard_grid.py`
   - `src/web/characters.py`
3. **本轮严禁动创作内容判断**。所有 fixture `*.json` 文案字段用 `"placeholder, see creation_standard"`；所有 `prompts/drama/*.txt` 文件**仅 framework + placeholder**，不写具体规则。Claude §B 会替换。
4. **严禁触碰** `docs/product/short_drama_creation_standard.md`（Claude 写的，与你无关；snapshot 复制只读源文件，**不**改源文件）。
5. **保留 25 + 5 = 30 个 JS 标识符 + 协议表达式**。本轮新增可被字符串检测的标识符：
   - `initDramaWrite`
   - `loadStationSetup`
   - `loadStationHooks`
   - `loadDramaProgress`
   - `data-station-pane`
6. **真模型路径必须 stub**：`drama_planner.run(mock=False)` 和 `hook_designer.run(mock=False)` 都 `raise NotImplementedError("...iter 040+")`，**绝不调 LLMClient**。
7. **创作规范快照不可变**：drama agent 加载时**只读** `workspaces/<name>/data/creation_standard.snapshot.md`，**绝不读** `docs/product/short_drama_creation_standard.md` 全局文件。
8. **mock fixture 路径硬规范**：`tests/fixtures/drama/track_<pinyin>_<station>.json`，pinyin 用 `bazhong / chongsheng / tuili / xitong / juexing`。不存在的 track 抛 `ValueError("unknown track")`。
9. **不要 push**。提交 message：`Iteration 037: drama wizard 4-station scaffolding (站 ①+②) + creation standard snapshot`

### ⚠️ 容易踩的坑（K1-K10）

| # | 坑 | 对策 |
|---|---|---|
| K1 | wizard 表单拆多页 | 5 字段一个 panel，不要做多步向导 |
| K2 | wizard 提交后跳错地方 | drama-start 成功后跳 `/w/<name>/write?step=setup`，不是 `/w/<name>/` |
| K3 | 站 ① ② 数据各开一个文件 | 统一落 `outputs/episodes/episode_01.setup.json`；站 ② 追加 `hook` 字段不开新文件 |
| K4 | `_ALLOWED_TAB_KEYS` 漏扩 | 扩为 12 项（8 老 + 4 新：`setup/hook/storyboard/characters`） |
| K5 | drama_view 状态判定写错 | setup done = setup file 含 `core_setup.protagonist`；hook done = setup file 含 `hook.type`；③ ④ 永远 locked（本轮） |
| K6 | iter 036 sidebar 测试不升级 | **必须**改 `test_drama_sidebar_only_exposes_overview_and_jobs` 为 3 项断言，注释 `# Updated iter 037` |
| K7 | agents.yaml `provider: openai` | 写 `provider: mock_only` 新值；本轮 LLMClient 不读这段，但 yaml 必须落盘 |
| K8 | `__drama_session_input` 误用 localStorage | 用 `sessionStorage`（同 iter 033 `__pending_toast`） |
| K9 | 快照路径写新 helper 到 `paths.py` | 不要；硬编码 `paths.WORKSPACE_DIR / <name> / "data" / "creation_standard.snapshot.md"` |
| K10 | 测试 mock 快照内容 | **不要 mock**；测 setUp 真复制源文件到 tmp workspace，断言 prompt 含"3 秒法则" / "60 秒的内部节奏"字符串（这两个一定在快照里） |

### ✅ 必须自带的边界测试

至少 6 条（计入 §A13 的 30 个新测试）：
1. wizard 5 字段全空提交 → 400
2. wizard `episode_count` = 0 或 = 999 → 400
3. drama workspace 缺 snapshot → `drama_planner.run()` raise；API 返 500
4. drama workspace 上 `/write?step=storyboard` → 渲染 empty-state，**不**404
5. drama workspace 上 `POST /api/workspace/<name>/run` 仍 400（iter 036 V11 不破）
6. wizard 选 track=霸总 → `drama_planner` mock 返霸总 fixture

---

## 4. Codex 自检（commit 前必跑）

```bash
# 1. 全套 unittest（基线 488；本轮新增 ≥ 30；6 ERROR 不变）
.venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5

# 2. dispatcher 14 路径（drama 加 /write 200，加 4 个 API endpoint）
PYTHONPATH=. .venv/bin/python3 -c "
import tempfile, json
from pathlib import Path
from src import paths
from src.cli_workspace import init_workspace
from src.web import routes

saved = paths.WORKSPACE_DIR
tmp = tempfile.mkdtemp()
paths.WORKSPACE_DIR = Path(tmp)
init_workspace('a_n', type='novel')

# drama needs wizard input + snapshot, build manually for smoke
init_workspace('b_d', type='drama')
(paths.WORKSPACE_DIR / 'b_d' / 'data' / 'wizard_input.json').write_text(
  json.dumps({'workspace':'b_d','topic':'test','track':'霸总',
              'episode_count':1,'episode_duration_seconds':60}),
  encoding='utf-8')
(paths.WORKSPACE_DIR / 'b_d' / 'data' / 'creation_standard.snapshot.md').write_text(
  '# snapshot\n\n3 秒法则\n\n60 秒的内部节奏\n', encoding='utf-8')

for p in ['/', '/trash', '/wizard', '/settings',
          '/w/a_n/', '/w/a_n/continue',
          '/w/b_d/', '/w/b_d/write', '/w/b_d/jobs',
          '/w/b_d/continue']:  # last should 404
    s, _, _ = routes.dispatch('GET', p)
    print(s, p)
"
# 前 9 条 200；最后一条 404。

# 3. 30 个保留 JS 标识符
.venv/bin/python3 -c "
from src.web import static
required = [
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    '_ALLOWED_TAB_KEYS', 'typeBadge',
    # iter 037 new
    'initDramaWrite', 'loadStationSetup', 'loadStationHooks',
    'loadDramaProgress', 'data-station-pane',
]
for kw in required:
    assert kw in static.JS_DASHBOARD, f'missing: {kw}'
print(f'all {len(required)} identifiers present')
"

# 4. drama_planner + snapshot 端到端
.venv/bin/python3 -c "
import tempfile, json
from pathlib import Path
from src import paths
from src.cli_workspace import init_workspace
from src import drama_planner

saved = paths.WORKSPACE_DIR
tmp = tempfile.mkdtemp()
paths.WORKSPACE_DIR = Path(tmp)

init_workspace('test', type='drama')
(paths.WORKSPACE_DIR / 'test' / 'data' / 'wizard_input.json').write_text(
  json.dumps({'workspace':'test','topic':'test','track':'霸总',
              'episode_count':1,'episode_duration_seconds':60}),
  encoding='utf-8')
(paths.WORKSPACE_DIR / 'test' / 'data' / 'creation_standard.snapshot.md').write_text(
  open('docs/product/short_drama_creation_standard.md').read(),
  encoding='utf-8')

result = drama_planner.run('test', mock=True)
assert result['track'] == '霸总'
print('drama_planner mock + snapshot OK; result track =', result['track'])
"
```

把以上 4 块输出**原文**贴进 §7 Codex Run Log。`FAILED (errors=6)` 那一行下补 6-ERROR 沙箱注脚。

---

## 5. Claude 验收：V1-V13

| # | 项 | 方法 |
|---|---|---|
| V1 | drama wizard 5 字段表单完整渲染 | dispatcher + grep |
| V2 | 提交后 `wizard_input.json` + `creation_standard.snapshot.md` 落盘 | 单测 |
| V3 | 提交后前端跳 `/write?step=setup` | grep JS_WIZARD |
| V4 | drama overview 升级为"进度看板"4 个 station card | dispatcher + grep |
| V5 | sidebar drama 3 项 (`overview / write / jobs`) | 单测（升级 K6） |
| V6 | `/w/<name>/write` 渲染 4 个 tab + 前 2 站可用 | dispatcher + grep |
| V7 | `/w/<name>/write?step=storyboard` 渲染 empty-state "iter 038 起开放"，**非 404** | dispatcher + grep |
| V8 | `drama_planner.run()` mock 按 track 查 fixture，5 赛道全过 | 单测 |
| V9 | `hook_designer.run()` mock 出 3 候选，5 赛道全过 | 单测 |
| V10 | drama agent 加载 snapshot 注入 prompt（含"3 秒法则" / "60 秒的内部节奏"） | 单测 |
| V11 | drama workspace 缺 snapshot → `drama_planner.run()` raise | 单测 |
| V12 | drama workspace 上 `POST /run` 仍 400（iter 036 V11 不破） | 单测 |
| V13 | iter 036 全套 488 + 6 沙箱 ERROR 不变（本轮新增 ≥ 30，总数 ≥ 518） | 全套 unittest |

**任一不过：退回 Codex 修。**

---

## 6. 不在 iter 037

- 站 ③ 分镜 / 站 ④ 角色 业务逻辑 → iter 038
- AI 绘画 HTTP client / Comfy workflow 导出 → iter 038
- `drama_reviewer` 5 维度评审 → iter 039
- 4 种导出（JSON / Markdown / CSV / Comfy）→ iter 039
- 真模型接入 → iter 040+
- 集 2+ 续写（本轮只跑集 1）→ iter 038
- LLMClient 接 `provider: mock_only` → iter 040+ 切真模型时再做

---

## 7. Codex Run Log（Codex 执行后填）

> Codex 请在这里粘贴 §4 四块命令的原文输出。`FAILED (errors=6)` 那一行下补 iter 035 同款 6-ERROR 沙箱注脚。

```
$ PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5
.......................................................
----------------------------------------------------------------------
Ran 536 tests in 4.077s

OK

$ PYTHONPATH=. .venv/bin/python3 -c "<dispatcher smoke from §4>"
[92m22:50:02 - LiteLLM:WARNING[0m: common_utils.py:979 - litellm: could not pre-load bedrock-runtime response stream shape — Bedrock event-stream decoding will be unavailable. Error: No module named 'botocore'
[92m22:50:02 - LiteLLM:WARNING[0m: common_utils.py:24 - litellm: could not pre-load sagemaker-runtime response stream shape — SageMaker event-stream decoding will be unavailable. Error: No module named 'botocore'
200 /
200 /trash
200 /wizard
200 /settings
200 /w/a_n/
200 /w/a_n/continue
200 /w/b_d/
200 /w/b_d/write
200 /w/b_d/jobs
404 /w/b_d/continue

$ .venv/bin/python3 -c "<30 JS identifiers from §4>"
all 30 identifiers present

$ .venv/bin/python3 -c "<drama_planner + snapshot smoke from §4>"
drama_planner mock + snapshot OK; result track = 霸总
```

Additional validation:

```
$ PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh
...
Ran 536 tests in 4.081s

OK
...
[auto-pipeline] done · chapters_written=1
Report snapshots OK: data/chapter_manifest.md, outputs/reviews/review_summary.md

$ PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 main.py preflight
PREFLIGHT: warn

## FATAL
- none
```

注：本地 §4 unittest tail 输出为 536 OK，未出现 `FAILED (errors=6)` 行，因此无 6-ERROR 沙箱注脚落点。裸 `bash scripts/verify.sh` 使用系统 `python3` 时出现 `FAILED (errors=70)`，根因是系统解释器缺 `pydantic`；将 `.venv/bin` 放入 `PATH` 后同一脚本退出 0。

Subagent read-only review:

- Web/API/UI reviewer: GO. 覆盖 5 字段 wizard、`/write?step=setup` 跳转、drama-only `/write` guard、4 个 drama API、`_SECTIONS_DRAMA=overview/write/jobs`、overview progress board、drama `/run` 仍 400、30 JS 标识符。残余 UX 风险：`?step=setup` 可能在 reload 时压过 `#hook`；已修为初始 query step 激活后规范成 hash。
- Drama agent/scaffold reviewer: 初始 P2 指出 `config/agents.yaml` 的 `system_prompt_base` 字段会让配置契约看起来仍指向全局 product doc。已删除该字段，只保留 workspace-relative `system_prompt_snapshot: data/creation_standard.snapshot.md`，并补测试锁住 snapshot-only config。

---

## 8. Acceptance Result（Claude 验收后填）

> Claude 填写 §5 V1-V13 结果 + Claude §B 替换进度 + 转 iter 038 backlog。

```
(待 Claude 验收后填写)
```
