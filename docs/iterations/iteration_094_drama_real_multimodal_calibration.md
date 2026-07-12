# Iteration 094 - 短剧真实多模态校准

## Context

Iteration 090-092 已完成短剧五站真文本 job、全角色真生图和 episode 1 真视频的可恢复编排，并将授权、预算、超时、重试与日志边界在 mock 中收口。当前主要缺口已从工程 wiring 转为真实供应商条件下的费用、时延、成功率和产物质量证据。

本轮以“分段、可停、可审计”的方式校准真文本、真生图与单次真视频，不把三类授权合并推定。立项本身不构成任何计费请求授权；每一阶段执行前都必须先完成零计费 readiness，向用户报告模型/服务、请求上限、最坏费用、超时和精确命令，再等待对应阶段的明确授权。

## Plan

1. 盘点 Iteration 092 多模态 state machine、当前 preflight 与脱敏状态投影，固定本轮校准的 workspace、episode、产物指纹和分段证据格式；不读取 `.env`、私有原文或历史用户产物。
2. 先运行零计费的 mock 全链与真实配置 preflight，验证 fresh/resume、独立授权闸、预算/deadline、全角色图与视频 readiness；只修复真实校准暴露的阻塞 bug。
3. 真文本阶段：在单独授权后运行一次五站文本 smoke，记录每站请求数、耗时、成本、结构化修复/失败与脱敏质量评估；未授权时保持 0 真实请求。
4. 真生图阶段：在独立授权后为 episode 1 全部出场角色生成参考图，记录逐角色任务状态、耗时、成本、尺寸与质量。首轮失败/超时后先查上游任务和账单，仅经重新授权使用简化 prompt，首轮外最多 2 次、每次 180 秒。
5. 真视频阶段：只在真文本/角色图产物的 hash、freshness、全角色覆盖、公网可回连资产与费用预估全部通过后，再申请独立视频授权；获权后仅单次提交，超时不重试。
6. 将三阶段的脱敏证据汇总为校准表，对比预估与实际请求数、成本、时延、成功/失败类型和可用质量，明确哪些阈值可固化、哪些仍需更多样本。
7. 为实际暴露的 provider 状态、超时、账单不确定性、resume 和脱敏边界增加 mock 回归；不为追求“全绿”而自动重提计费任务。
8. 收官使用 `iter-finish`：先完成 correctness、security/billing boundary 以及 multimodal/provider 至少三个独立只读 subagent 视角审查并修复 findings，再运行一次最终标准验收，同步 README SOP、handoff 当前快照和项目历史。

## Acceptance

- 在任何计费请求前，mock 全链、fresh/resume、三类独立授权闸、有限正预算/超时与脱敏状态投影均通过；未授权阶段的真实网络请求数为 0。
- 真文本、真生图、真视频各自使用一次性明确授权，不从对话历史、上一阶段或 resume state 继承；每次授权前报告精确命令、服务/模型、最大提交数、最坏费用和超时。
- 获得对应授权时，五站真文本、全出场角色真生图和 episode 1 单次真视频分段执行，每段均留下不含凭据、完整 prompt、签名 URL 或上游响应正文的耗时/成本/状态/质量证据。
- 生图严格遵守“先查上游与账单，再重新授权”；总提交最多 3 次，后两次使用简化 prompt 且每次 180 秒。视频仍是单次提交、超时不重试。
- 任一上游失败、账单状态不明、预算/deadline 耗尽、产物缺失或指纹/freshness 不一致时，链路停在可恢复状态，不自动进入下一个计费阶段。
- 最终校准表清晰区分“工程闭环已验证”、“真实样本已验证”和“样本不足/未授权”，不把未执行的真实 smoke 记为通过。
- canonical 以 **1903 tests OK** 为起始基线且新增回归全绿；`bash scripts/verify.sh` exit 0；mock preflight 无 WARN/FATAL；聚焦回归、语法检查与 `git diff --check` 通过。
- correctness、security/billing boundary、multimodal/provider 至少三视角只读审查完成，主线复核 findings 并记录未修风险。

## Implementation Notes

- 在 `drama_multimodal_smoke` 增加安全的 `--report-only` 校准报告。报告把 engineering mock、`real_execution_recorded_unverified`、本地未核验记录和 operator quality review 分开；仅有本地 state 不会让 `real_sample_complete` 变为 true。
- 五站文本链记录逐站调用数、耗时、cost 与有界证据，并固定本次模型配置 SHA；resume 中模型漂移会 fail-closed。LLM audit ledger 用 task/model 对账，失败、重复失败和 crash-active step 也能补回调用与 elapsed，避免只统计成功步骤。
- 图片 attempt 增加起止时间和 objective metadata；视频在付费提交前持久化 submission count，失败也记录 elapsed。报告通过 `drama_video.read_video()` 重新验证容器、尺寸、SHA 与输入 fingerprint，避免仅相信旧 state。
- 公开报告进一步收紧模型/provider/status/error/character id 等字段：自由模型名和 provider 文本不直接公开，状态采用 allowlist/有界投影，不保存凭据、完整 prompt、签名 URL 或上游正文。
- 扩展多模态 mock 回归至 35 项，覆盖 mock/真实证据分离、无 provider 报告、秘密投影、图片/视频篡改、失败计量、模型漂移、重复失败和 crash 恢复。
- `iter094_mock_final` 完成全链 mock：engineering mock verified、real sample incomplete，真实网络请求和付费提交均为 0。用户未授权任何真文本、真生图或真视频，因此本轮没有真实供应商请求、账单或质量样本。
- 收官审查初轮暴露的正确性、账本、安全投影和 provider 证据问题均在本轮修复；三视角最终复核 PASS。
- 用户补充要求恢复项目记忆并调整收官顺序：未把 iter 093 前 2216 行逐轮日志原样回滚，而是保留短当前快照并恢复数百行精选工作记忆；`PROJECT_HISTORY.md` 恢复为默认伴随读物。耗时全量验收改为多视角审查和修复之后的最终闸门。
- 标准全量验收已在上述代码/审查修复完成后执行。之后仅有文档与 `iter-finish` 流程补充，按用户明确要求不再重复全量验收。

## Acceptance Result

- **聚焦回归**：`tests/test_drama_multimodal_smoke.py` 共 **35 tests OK**；Python compile、shell `bash -n` 与 `git diff --check` 通过。
- **Canonical**：项目依赖环境、loopback 可用条件下共 **1915 tests OK**，相对 iter 093 基线新增 12 项；系统 Python 初次因缺少 `tiktoken` 不能作为项目基线，受限 loopback 环境初次产生 13 个环境错误，换用项目依赖环境和允许的 loopback 后全绿。
- **标准验收**：`bash scripts/verify.sh` exit 0（内含 1915 tests、mock pipeline/report/cost checks）；`python3 main.py preflight` 在 mock 配置下 ok，无 WARN/FATAL。该验收在代码 findings 修复后完成。
- **校准证据**：mock run `iter094_mock_final` 成功；报告为 engineering mock verified、real sample incomplete。真实文本请求、真实图片提交、真实视频提交均为 **0**，实际真实费用/时延/质量仍为“未授权、无样本”，没有伪记为通过。
- **correctness 审查**：独立只读视角复核状态恢复、计量、模型固定、篡改检测与报告语义，最终 PASS。
- **security/billing 审查**：独立只读视角复核授权不继承、重复计费、公开投影、凭据/URL/prompt 边界，最终 PASS。
- **multimodal/provider 审查**：独立只读视角复核图片 attempt、视频提交/容器/指纹、provider 失败与 resume 对账，最终 PASS。
- **主线程复核**：初轮 findings 均已修复并有聚焦回归；未修代码风险为 0。仍保留的产品证据缺口是未执行真文本、全角色真生图和单次真视频，且真实质量必须由 operator 人工判断。
- **流程补充后的验证**：AGENTS、README、handoff、history、iteration 与安装的 `iter-finish` 只做轻量结构/skill 校验；依据用户要求，未再次运行 canonical 或 `verify.sh`。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_094_drama_real_multimodal_calibration.md` | 本轮 8 段计划与待回填验收记录。 |
| `docs/iterations/README.md` | 追加 Iteration 094 索引。 |
| `src/drama_multimodal_smoke.py` | 校准证据、调用/耗时/成本对账、模型固定、产物复核与安全报告。 |
| `src/drama_smoke.py` | 五站 step 起始回调与逐步耗时。 |
| `tests/test_drama_multimodal_smoke.py` | 新增证据分离、失败恢复、漂移、篡改与脱敏回归。 |
| `AGENTS.md` | 明确默认记忆读物与“审查修复后再跑全量”收官顺序。 |
| `README.md` | 同步 iter 094 项目状态、SOP 与短剧校准状态。 |
| `docs/AGENT_HANDOFF.md` | 更新 iter 094 当前快照，并恢复精选阶段级工作记忆。 |
| `docs/PROJECT_HISTORY.md` | 记录 iter 094、记忆再平衡和全量验收后置的长期决策。 |
| `~/.codex/skills/iter-finish/SKILL.md` | 将多视角审查/修复移到最终全量验收之前，并更新记忆同步契约。 |

## 不在本轮范围

- 未经对应阶段明确授权的真文本、真生图或真视频请求，以及从任一已授权阶段推定其它授权。
- 真视频自动重试、批量真生图/真视频、episode 2 视频与第 3 集以上季级编排。
- 真 ComfyUI workflow、模型训练/微调、新供应商选型或公网多租户产品化。
- 小说 10-20 章 capstone 和文风阈值真模型校准。

## Notes

- 本轮已显式使用 `iter-start`；实施收官必须显式使用 `iter-finish`。
- 收官已显式使用 `iter-finish`；三视角审查与 findings 修复先于最终一次全量验收。
- README 里程碑、9 阶段 SOP、handoff 当前快照/Latest Transition、精选工作记忆和 Project History 已同步。
- 立项提交信息草案：`docs(iter094): 迭代计划 094 立项（短剧真实多模态校准）`。
- 收官提交信息草案：`docs(iter094): 收口多模态校准证据与项目记忆工作流（验收 + 审查 + SOP/handoff 同步）`。
