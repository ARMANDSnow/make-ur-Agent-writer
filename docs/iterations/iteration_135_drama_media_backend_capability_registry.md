# Iteration 135 - 短剧媒体 Backend 能力注册与冻结解析

## Context

iter133-134 已完成 G1 持久 task DAG 与 G2 worker lease/capacity，但 worker 尚不能从受审查的代码注册表确定一个 task 对应的 backend 能力；现有 C/D/E 图片、视频、TTS capability 又分别封装在各自 attempt 中，缺少统一的 `(provider, media, model)` loud-fail 解析和冻结边界。阶段 G 的下一步 G3 先建立纯本地、零网络、零凭据的 backend contract 与静态 registry，使后续 queue/execution loop 只能消费已解析、内容寻址且与 task provider identity 匹配的冻结 binding。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_shot_image_attempts.py`, `src/drama_shot_video_attempts.py`, `src/drama_tts_attempts.py`, `config/models.yaml`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_media_backends/__init__.py`, `src/drama_media_backends/base.py`, `src/drama_media_backends/registry.py`, `tests/test_drama_media_backend_registry.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_135_drama_media_backend_capability_registry.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不动态导入用户代码，不读取凭据，不触发 provider/图片/视频/TTS，不接 queue/execution loop/Web mutation，不迁移 C-F paid ledger，不 push

1. 定义最小通用 backend descriptor/capability/binding schema，仅承载 backend/provider/media/model identity、执行形态、分阶段能力、引用/时长/分辨率等有界公共约束及内容寻址 fingerprint；不得承载凭据、endpoint、prompt、provider response、路径或费用结算事实。
2. 建立代码内显式 registry builder；注册键固定为 `(provider_id, media_kind, model_id)`，重复键、重复 backend、能力矛盾、大小写/路径歧义、未知组合与非法媒体模型 loud fail，禁止 entry point、模块字符串或用户配置驱动的动态执行。
3. 解析时同时校验 task 已冻结的 provider identity 与 registry binding，返回 immutable/content-addressed binding snapshot；task 创建或 submitted 后不得因 registry 后续变化被重解释，lost-response replay 必须继续使用原 snapshot identity。
4. 为现有 image/video/audio capability 提供纯转换/兼容边界，证明公共 registry 不改变 C/D/E 原 attempt 的 capability/artifact/authorization/receipt fingerprint；mock/local backend 也必须显式注册，不以 fallback 吞掉未知模型。
5. 用纯本地测试覆盖 deterministic order/fingerprint、unknown/duplicate/drift、strict numeric/list、snapshot freeze、旧 attempt 兼容、安全投影和零网络；queue client、provider adapter、execution loop 与 pricing/Insights 顺延。

## Acceptance

### Review Context
- `correctness_behavior`: registry key 唯一性、canonical order/content address、task provider identity binding、snapshot freeze 与 registry drift、C/D/E capability 兼容和 unknown loud fail 必须确定；不得改变 G1/G2 task/lease 或既有 paid attempt 的 artifact/receipt/fingerprint 语义
- `security_boundary`: provider/model/backend/media 标识、strict bool/int/list、重复与大小写歧义、动态 import/entry point/任意 callable、凭据/endpoint/prompt/path/response 字段和公开投影必须 fail closed；模块 import/lookup 零网络零环境凭据读取
- `extra_risk_view`: runner/media/paid 专项，复核 frozen binding 与 worker task identity、旧 submitted attempt 不被 registry 重解释、mock/local 显式注册、零 provider/计费副作用

- **A135-01**：strict descriptor/capability/binding schema 内容寻址且字段有界，拒绝额外字段、bool 冒充 int、非 canonical list/order、非法 identity、凭据/endpoint/prompt/path/response/费用事实。
- **A135-02**：代码内 registry 对 `(provider, media, model)` 唯一注册并 deterministic；duplicate/backend drift/unknown/case ambiguity loud fail，且不存在动态 import、entry point 或用户代码执行入口。
- **A135-03**：task provider identity 与解析结果 guarded binding；冻结 snapshot 在 registry 变化后仍保持原 identity，旧 submitted/unknown 不能重新解析或自动重提。
- **A135-04**：image/video/audio 兼容转换不改变现有 C/D/E capability、authorization、artifact、receipt fingerprint；公开投影脱敏，import/lookup/test provider/network/TTS 调用均为 0。
- **A135-05**：聚焦回归与 correctness/security/runner-media-paid 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- 新增 strict `DramaMediaBackendCapability/Registration/RegistrySnapshot/Binding`：registry 与 binding 都内容寻址；binding 冻结完整 registration/capability snapshot，而非只保存当前 registry 的可变引用。
- registry builder 只接受已实例化的受审查 schema 序列，不接受 mapping、模块字符串、entry point 或 callable；按 `(provider_id, media_kind, model_id)` canonical 排序。provider/model ID↔fingerprint 双向唯一；同 backend 可为同 owner/media 注册多 model，但跨 provider/media ownership、不同 model ID 复用 fingerprint 与 `.`/`..` 路径歧义 fail closed。
- C3 image、D3 video、E2 TTS capability 在转换入口重新构造验证，保持源对象与 `source_capability_fingerprint` 不变；通用 descriptor 只投影已存在的公共约束。TTS 的 provider/model 直接复用已冻结字段，且保留 synthesis POST 后独立 download 的恢复能力，不从环境或 model 名猜 provider。
- 首次 binding 限于 `planned/ready/claimed`，校验 task backend/media/provider/model fingerprints；进入 `submitting` 后没有 frozen binding 即 safe-block。携原 binding 时不以新 registry 重解释，binding 仍绑定 exact task ID/input/provider identity。
- registry/capability/registration/binding 采用 tuple 与 frozen resolution value object 深冻结；每个公开消费入口仍以 JSON-mode round-trip 重验内容指纹。安全 projection 隐藏 provider/model、registry/source/binding fingerprints 与所有 endpoint/account/prompt/path/response/paid evidence。本轮未新增 adapter callable、持久 binding store、queue、网络或计费调用。
- 三视角首轮确认 provider/model ID-fingerprint 交叉绑定、source capability mutation、TTS download 语义、`.` 路径段与浅冻结问题；修复后 correctness/security/runner-media-paid 最终均 no findings。
- 聚焦实现回归：新增 23 tests；G1-G3 + C/D/E attempt/paid store 共 145 tests OK，覆盖 deterministic registry、duplicate/unknown/drift、strict schema、冻结 replay、兼容 fingerprint、安全投影和 socket 零网络；`py_compile`、harness 与 `git diff --check` 通过。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: 静态 registry、首次 binding 时点、submitted 后禁止重解析和 C/D/E source capability 不变是后续 queue/execution loop 必须遵守的长期恢复与安全边界，需在 implementation commit 前进入模块权威契约。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 strict 通用 capability、registration、registry snapshot 与 frozen binding |
| `src/drama_media_backends/__init__.py` | 导出 G3 静态 backend API |
| `src/drama_media_backends/base.py` | 新增 C/D/E capability 纯转换与 registration 构造 |
| `src/drama_media_backends/registry.py` | 新增 deterministic registry、task binding 解析与安全 projection |
| `tests/test_drama_media_backend_registry.py` | 新增 registry、冻结、兼容、脱敏与零网络测试 |
| `docs/product/short_drama_module.md` | 晋升 G3 长期契约并更新精确完成口径 |
| `docs/iterations/iteration_135_drama_media_backend_capability_registry.md` | 本轮计划、实现与验收记录 |
| `docs/iterations/README.md` | iteration 索引 |

## 不在本轮范围

- queue client、provider submit/poll/download/validate execution loop、Web mutation、pricing/Insights。
- 动态/第三方 backend 插件、现有 paid ledger 迁移、真实图片/视频/TTS 与主观质量验证。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
