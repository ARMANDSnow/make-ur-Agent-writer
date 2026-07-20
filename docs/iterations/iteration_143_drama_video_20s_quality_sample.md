# Iteration 143 - 短剧真视频 20 秒质量样本

## Context

iter142 已在固定 workspace `iter124_real_sop_v2` 完成一个 5.042 秒、720×1280 的真实 Episode 1 样本，但现有 runner 的时长、账本和产物路径均固定为单个 5 秒结果，不能安全原地复跑或覆盖。用户明确授权新增一个约 20 秒的真实视频质量样本，用于综合检查供应商的长时一致性；本次授权固定为最多一次 video create、项目侧预算 80 元、等待上限 30 分钟、0 自动重试。供应商文档只示例 5 秒，本地客户端允许 1–30 秒，因此 20 秒是否被上游接受本身也是本轮待验证事实。

## Plan

### Implementation Context
- `must_read`: `src/drama_video.py`, `src/drama_video_client.py`, `src/drama_video_smoke.py`, `scripts/drama_video_episode1_single_submit.sh`, `tests/test_drama_video.py`, `tests/test_drama_image_video_clients.py`, `docs/iterations/iteration_142_drama_video_asset_contract_real_retry.md`
- `expected_changes`: `src/drama_video.py`, `src/drama_video_smoke.py`, `scripts/drama_video_episode1_quality20_single_submit.sh`, `tests/test_drama_video.py`, `tests/test_drama_image_video_clients.py`, `docs/iterations/iteration_143_drama_video_20s_quality_sample.md`, `docs/iterations/iteration_142_drama_video_asset_contract_real_retry.md`
- `do_not_touch`: 不读取或修改 `.env`、`小说txt/` 和用户未跟踪体检报告；不删除、改写或伪造 iter142 的 5 秒账本与 MP4；不运行真文本、真生图、TTS、逐镜视频或 episode 2+；不自动重提 20 秒请求

1. 为 20 秒质量样本建立精确 authorization profile、固定时长与独立持久命名空间；默认 5 秒入口和 canonical local-E2E 行为保持不变。
2. 将时长与 sample identity 纳入授权、submission、asset-upload、artifact metadata、恢复和 read/QA 校验，防止 5 秒与 20 秒账本或产物互相复用。
3. 新增 exact-workspace 专用 shell 入口，固定 80 元、30 分钟、20 秒、一次 create；非法 workspace/参数在 client/network 前拒绝。
4. 以 mock 聚焦测试证明 20 秒 payload、独立产物、恢复、unknown 不重提、旧 5 秒兼容和脚本门禁。
5. implementation commit 与 canonical mock 验收通过后，先做只读 task-list 鉴权和 callback exact-byte probe，再执行一次真实 20 秒提交；抽取多时间点画面评估人物/手部/背景/文字/运动/镜头连贯性。

## Acceptance

### Review Context
- `correctness_behavior`: 5 秒默认入口完全兼容；20 秒 profile 只产生独立账本/产物并严格校验 20 秒±0.25 秒、720×1280；resume/read/status 不跨 sample 复用
- `security_boundary`: sample key、workspace、duration、budget、timeout 与 profile 全部使用代码内 allowlist；路径不可由用户自由拼接；付费 POST 前 durable marker，unknown/timeout 不自动重提
- `extra_risk_view`: 真实媒体/计费视角：供应商未承诺 20 秒能力且实际人民币费用可能不回报；本轮只允许一次 create、80 元项目侧授权预算、30 分钟轮询，不把短样本外推为完整生产质量

- `A143-01`：聚焦测试证明 20 秒 profile 与默认 5 秒 profile 的 duration、ledger、artifact、authorization 和 read/QA lineage 物理隔离，旧 5 秒结果不被改写。
- `A143-02`：专用脚本与 Python last-hop gate 同时绑定 `iter124_real_sop_v2`、20 秒、80 元、30 分钟和代码内 sample key；任何漂移在 client 构造或网络前 fail closed。
- `A143-03`：付费路径保持逐素材 upload marker、video submitting marker、一次 create 与 0 自动重试；unknown/timeout 只允许查询和人工核账。
- `A143-04`：correctness、security/boundary、真实媒体/计费三个只读审查视角无未处理有效 finding；最终一次 `bash scripts/verify.sh` 通过，工程结论保持 `mock-functional`。
- `A143-05`：真实运行最多一次 create；若上游接受，产出 20 秒±0.25 秒、720×1280 MP4 并完成多时间点抽帧与人工质量记录；若拒绝、超时或结果不明，以 provider 事实和 durable ledger 收口且不重提。

## Implementation Notes

- 选择同一 workspace 下的静态 allowlist sample namespace，而不是复制 workspace：20 秒产物写入 `outputs/video_samples/iter143_quality_20s_v1/`，asset/submission ledger 写入 `logs/drama_video_samples/iter143_quality_20s_v1/`；iter142 的默认路径和旧授权指纹保持兼容。
- `VideoRunContract` 只由代码内 exact profile 解析，20 秒 sample 绑定 `iter124_real_sop_v2`、20 秒、80 元、30 分钟和 `quality-continuity-v1`；脚本同时固定 workspace/profile/budget/timeout，并在进程内把估算设为 80 元，不修改 `.env`。
- 20 秒 prompt 保留同一 Episode 1 高光内容，并追加开头/中段/结尾连续动作、一致性与反变形要求；实际 prompt SHA 进入 authorization fingerprint，因此 asset ledger、submission ledger、artifact meta 和 read/adopt 都绑定同一 prompt 字节。
- 审查初轮 findings：correctness/媒体指出 resume 丢失 profile；媒体指出 prompt version 未绑定实际文案。修复后 resume 保留 exact profile、共存 default/quality submitted ledger 时只轮询 quality task且 0 create；prompt drift 在任何 upload/create/poll 前 fail closed。
- correctness 复审另发现 ledger reader 未将内部 run contract 与目标 namespace 双向绑定；现已强制 default path 只接受 legacy contract、quality path 只接受完整 quality contract，并以两个方向 misplaced-ledger 的 read/status blocked 测试覆盖。
- 最终相关聚焦回归 **105 tests OK**，语法、harness 与 diff check 通过；correctness、security/boundary、真实媒体/计费三视角最终复审均为 **no findings**。

## Acceptance Result

### 工程验收

- `A143-01`：通过。默认 5 秒路径与 authorization fingerprint 保持兼容；20 秒 sample 使用独立 artifact/asset/submission namespace，并把 duration、sample ID、prompt version、实际 prompt SHA 与授权指纹共同冻结。错位 ledger、prompt drift、跨 sample resume/read/status 均 fail closed。
- `A143-02`：通过。shell 与 Python last-hop 双层固定 workspace `iter124_real_sop_v2`、20 秒、80 元、30 分钟和 exact profile；脚本拒绝其他 workspace/参数，门禁在真实 client/network 前完成。
- `A143-03`：通过。逐素材 upload 与 video create 分别在 POST 前写 sample 专属 durable marker；submitted resume 只轮询 quality task、0 upload/0 create，unknown 再运行同 profile 时 0 POST。
- `A143-04`：通过。相关聚焦回归 **105 tests OK**；correctness、security/boundary、真实媒体/计费三视角最终均 **no findings**。accepted implementation `2241789749f53300d36c7768e3894ce81c584558` 上 canonical **2792 tests、15 steps、454 秒**，run `9e969daa9c2345cdae3c416fb066ae44`，tree `7c1c83c80066bc044b112549e2ac5841a138880b`；`mock-functional` / `canonical-mock-offline`，preflight 0 FATAL / 0 WARN、tracked scope clean。

### 单次真实 20 秒尝试

- `A143-05`：按约定以 `safe-blocked` 收口。提交前只读任务列表为 **2 个 completed task**；callback-only 临时公网入口 root 与工作台路径均为 404，未暴露完整 Web。
- sample 专属 asset ledger 达到 `uploaded_all`，共确认 **2 个素材 ID**。video create 前已写 `submitting` marker，随后约 14 秒内得到结果不明异常；没有 task ID、没有 MP4，自动重试 **0**。
- 任务列表在异常后立即查询与约 30 秒后复查均保持 **2 个既有 completed task**，未观察到新增 provider task。该事实不能证明请求未到达或不会计费；实际人民币费用保持 **unknown**，不能记为 0。
- 该次 create opportunity 已消费，禁止自动或沿用本次授权重提。由于没有 20 秒产物，本轮不能评价供应商的长时人物/手部/背景/运动质量，也不升级 20 秒样本为 `provider-validated`；iter142 的 5.042 秒成功样本仍是独立、未被改写的窄证据。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: 真实媒体质量对比必须把实际 prompt SHA、时长、sample namespace 与授权指纹共同冻结，不能只依赖容易漏改的版本标签；该恢复与可比性规则适用于后续所有付费校准样本。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_143_drama_video_20s_quality_sample.md` | 建立本轮计划、验收边界与证据入口 |
| `docs/iterations/README.md` | 追加 iter143 canonical 索引 |
| `src/drama_video.py` | 增加 exact quality20 contract、独立路径、动态时长、prompt SHA lineage 与 sample-aware resume/read/status |
| `src/drama_video_smoke.py` | 在提交和恢复时透传 profile，并从精确 sample namespace 读取结果 |
| `scripts/drama_video_episode1_quality20_single_submit.sh` | 新增固定 workspace/20 秒/80 元/1800 秒的单提交入口 |
| `tests/test_drama_video.py` | 覆盖路径隔离、last-hop 门禁、20 秒 payload/QA、prompt drift、unknown 与恢复/错位账本 |
| `README.md` | 同步 20 秒样本 safe-blocked 的项目状态与 A-J SOP |
| `docs/AGENT_HANDOFF.md` | 更新 canonical、真实尝试、缺口、候选与 Latest Transition |
| `docs/PROJECT_HISTORY.md` | 晋升质量样本 exact lineage 的长期决策与工程教训 |

## 不在本轮范围

- 不覆盖或删除 iter142 已完成的 5 秒 MP4、metadata、asset ledger 与 submission ledger。
- 不测试音频、TTS、完整单集、多集、逐镜 adapter、Web provider 操作或其他模型。
- 不把项目侧 80 元授权预算解释为供应商账单硬上限或实际费用。

## Notes

- “20 秒”指目标成片时长；生成墙钟时间可能明显超过 20 秒。
- 用户要求将最终真实质量样本摘要追加到 iter142 末尾；iter143 仍作为本次代码变更与验收的 canonical 记录。
