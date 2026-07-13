# Iteration 101 - 短剧完整链路残余阻塞修复

## Context

iter100 收官后的多视角只读复核确认：单集 mock happy path 虽已通过现有基线，但真文本成功后的返修、普通 Web workspace 进入真生图、多集新增角色、视频 submitted 恢复和交付投影仍存在确定性阻塞或安全边界缺口。本轮以“不调用真模型也能确定验证”为原则，修复这些状态机、血统和交付问题，并补齐此前只覆盖 fail-closed、未覆盖合法恢复路径的回归测试。

## Plan

1. 真文本 revision：将成功 attempt 从永久单槽改为可审计的新 revision；保留 crash/retry fail-closed，支持用户经新授权重新生成和重新评审。
2. 评审与组装血统：Reject/Abstain 不得发布 fresh 剧集；setup/storyboard/characters/review 漂移后手工 assemble 不得绕过重新评审。
3. 真生图入口：让既有普通 Web workspace 可在显式授权、durable ledger 和既有边界下进入真实全角色生图，不再依赖 disposable smoke workspace。
4. 多集角色：避免新增角色 ID 覆盖既有人物，修复旧集站④完成态判定和第 9 个角色硬阻塞，并保持早期集 fingerprint 稳定。
5. 视频恢复与安全：submitted 恢复不再依赖用户重填原授权；Web 日志脱敏 callback capability token。
6. 交付完整性：季包内参考图路径可解析；单集 JSON 使用 schema 投影；参考图验证真实格式并绑定角色目录。
7. 为上述路径增加聚焦测试；按 iter-finish 完成 correctness、security/boundary 与 runner/multi-episode 只读审查，最终只跑一次标准全量验收。

## Acceptance

- 新增回归覆盖：真文本成功后新 revision、Reject/Abstain 门禁、手工 assemble 血统校验、既有 workspace 真生图可达、多集角色 ID/历史状态/容量、submitted 视频页面恢复、callback 日志脱敏及导出投影/引用完整性。
- 聚焦单测与静态检查通过，`git diff --check` 无错误。
- 多视角只读审查 findings 均经主线程复核并修复或明确记录未修风险。
- 最终一次通过 `python3 -m unittest discover -s tests`、`bash scripts/verify.sh`、`python3 main.py preflight`；全程保持 mock/offline，不调用真实文本、图片或视频服务。

## Implementation Notes

- 文本返修与发布血统：付费文本账本新增显式 `confirm_new_text_revision`，重试仍复用当前 revision，新 revision 保留有界成功历史；评审记录绑定 setup/storyboard/episode cast fingerprint，Reject/Abstain 和任意输入漂移均不能发布或导出。旧评审仅在既有组装产物可证明完全同源时原子迁移，首次 multimodal 状态写入前完成且 crash 后可恢复。
- 角色与多集：季级角色库上限放宽至 999，单次生成和单集活跃阵容仍限制为 8；新增角色分配不冲突的 `cNNN`，只允许替换本集首次引入且未锁定的角色。旧数据缺少站④生成记录时 fail-closed；复用角色会补齐 episode marker，并在第 9 人场景中确定性保留本集新人、将总阵容裁到 8。
- 真生图边界：普通 Web workspace 可通过显式授权进入 media-only 图片阶段。任何 provider 调用前均在同一 workspace lock 内复核路径、fresh Approve 血统和 fingerprint；图片 state、staging、canonical PNG 使用 dirfd 与 `O_NOFOLLOW` 防止符号链接换位，macOS `/var`、`/tmp` 可信别名得到兼容。
- 视频恢复：submitted 任务只允许 resume/reconcile，不重新提交；恢复使用 durable 原始 budget、timeout、estimate 与授权，不要求用户重填预算。存在 durable real ledger 时切到 mock 会 fail-closed，状态页优先显示 submitting/submitted/failed ledger，旧 submitted 但缺授权的数据进入 reconciliation blocked。
- 交付与日志：单集 JSON、角色 JSON 与季包 manifest 均使用 schema 投影；季包 reference path 必须落在准确角色目录且为真实 PNG，ZIP 内引用与成员一一对应，缺失引用不写入 snapshot。Web access log 对 callback capability token 做脱敏。
- 审查期间补充修复了 `season_no` 非严格整数、历史角色替换边界、旧评审迁移 crash 顺序、media-only 首次状态覆盖迁移、视频 mode drift、提交中状态投影和导出 dangling ref 等 findings；未扩大到真实 provider 调用。

## Acceptance Result

- 聚焦短剧回归：`OPENAI_MODEL=mock DRAMA_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests -p 'test_drama*.py'`，350 tests，`OK`。
- 最终全量：同一 mock/offline 环境下使用项目 `.venv/bin/python3 -m unittest discover -s tests`，2044 tests，退出码 0。首次按文档裸 `python3` 执行因系统 Python 3.14 未安装 `pydantic` 在收集期失败；切换到仓库配置的 `.venv` 后通过，判定为解释器环境不匹配而非代码回归。
- 标准工程验证：`bash scripts/verify.sh` 退出码 0；`OPENAI_MODEL=mock DRAMA_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true .venv/bin/python3 main.py preflight` 为 `PREFLIGHT ok`，0 FATAL、0 WARN；`git diff --check` 通过。
- 三个独立只读 subagent 完成复审：correctness 与 runner/multi-episode 未发现残余 P0-P2 阻塞；security/boundary 未发现残余 P0/P1。主线程复核并修复全部可复现 findings。
- 保留一个不阻塞正常生成的 P2：拥有同机写权限的外部恶意进程，理论上仍可在 canonical JSON 的父目录 `lstat` 与原子替换之间制造 TOCTOU；项目内并发已由 workspace lock 隔离，图片/state 路径已使用 no-follow。该风险已同步 handoff，后续可统一迁移 JSON writer 到 dirfd/no-follow。
- 全程未读取 `.env`、`小说txt/` 或用户私有产物，未调用真实文本、图片或视频服务。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py`、`src/drama_store.py`、`src/drama_reviewer.py` | revision、评审血统、Reject/Abstain 门禁、旧数据安全迁移 |
| `src/character_designer.py`、`prompts/drama/character_designer.txt` | 多集角色 ID、历史所有权、容量裁剪与最小 prompt 投影 |
| `src/ai_draw_client.py`、`src/drama_multimodal_smoke.py` | 普通 workspace 真生图可达与 no-follow 图片/state 写入 |
| `src/drama_video.py`、`src/drama_video_smoke.py` | submitted durable 恢复、mode drift 和状态门禁 |
| `src/web/jobs.py`、`src/web/routes.py`、`src/web/server.py`、`src/web/static.py` | Web 授权参数、media-only runner、恢复 UI 与 callback 日志脱敏 |
| `src/drama_season_export.py` | schema-projected 导出、PNG 真实性/目录绑定、ZIP 引用闭包 |
| `tests/test_drama_iter101_blockers.py` 及 4 个既有短剧测试文件 | 21 个新增回归及既有断言适配 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md`、iteration 索引与本文 | SOP、当前快照、长期教训和验收证据同步 |

## 不在本轮范围

- 不执行真实文本、真生图或真视频 smoke；真实 provider 质量与计费校准仍需用户逐次授权。
- 不扩展第 2 集及以后的视频成片能力，也不新增 JPEG/WebP 参考图支持。

## Notes

- 本轮优先修复完整流程阻塞和凭据/交付边界，不顺带重构无关短剧 UI 或通用小说流水线。
- 建议提交信息：`fix(iter101): 修复短剧完整链路残余阻塞`。
