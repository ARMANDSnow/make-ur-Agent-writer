# Iteration 148 - 短剧可移植项目归档与安全导入

## Context

iter147 已完成 I1 同源只读 production workbench，A-J 阶段 I 剩余的明确缺口是 I2 可移植 archive export/import。本轮建立独立于 season deliverable 的 project archive：只收纳允许迁移的 creative/render/selection/media/evidence 成员，每个成员绑定 path/size/SHA-256/MIME/schema；导入必须先完整 preflight，再原子创建新 drama workspace，不覆盖任何已有 workspace。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_season_export.py`, `src/drama_production_workbench.py`, `src/cli_workspace.py`, `src/paths.py`, `tests/test_drama_season_export.py`
- `expected_changes`: `src/drama_project_archive.py`, `src/drama_production_workbench.py`, `main.py`, `tests/test_drama_project_archive.py`, `tests/test_drama_compose_web.py`, `tests/_drama_shot_image_base.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_148_drama_portable_project_archive.md`, `docs/iterations/README.md`
- `do_not_touch`: `.env*`、`data/`、`logs/`、`outputs/`、`workspaces/`、`小说txt/`、私有样本与真实 provider/TTS；归档不得包含原文、完整 prompt、review 自由文本、provider raw body、signed URL、credential/account fingerprint 或可重放的付费授权

1. 新增 strict archive schema 与确定性 ZIP builder；manifest 记录 archive/project/season/episode identity、creative/render/timeline/QA fingerprints 及每个成员的受控相对路径、分区、size、SHA-256、MIME 和 schema label。
2. export 只从 strict current inspectors/manifests 枚举允许成员；selected/referenced assets、timeline 依赖、exact delivery 与脱敏 evidence 可包含，原文/prompt/provider 原始响应/凭据/paid authorization 默认永不包含。
3. import preflight 在写入前拒绝未知 schema/version、绝对或穿越路径、反斜线、重复/case-fold 冲突 member、symlink/特殊文件属性、压缩比/成员数/单件/总解压上限、坏 size/hash/MIME、manifest 外成员与不允许目标路径。
4. 导入只能创建新的 drama workspace；用私有 staging 写入并 fsync，最后 no-overwrite commit，中断/失败不留可见 partial target。export→import→re-export 保持成员 hash、selected/render/timeline/QA/MP4 identity。
5. 提供明确 CLI export/import/preflight 入口，默认零网络/provider；本轮不把 archive 按钮或 upload transport 塞入 I1 GET 页面。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 export 成员从 current authoritative manifests 确定枚举、排序与字节稳定，import preflight 先于写入，新 workspace round-trip 保持 selection/render/timeline/QA/MP4 identity，失败无 partial target
- `security_boundary`: 核对 zip-slip/绝对路径/反斜线/重复与 case-fold 冲突、zip bomb/属性/MIME/hash/size/schema 与 no-follow/no-overwrite，确认不收纳原文、prompt、provider raw/signed URL/credential/paid authorization
- `extra_risk_view`: archive/migration：核对跨 workspace identity 改写、staging/fsync/commit 中断窗口、再导出确定性与非合作写者残余风险

- A148-01：strict/bounded manifest 与确定性 ZIP 只收纳 allowlisted current 成员，每件 path/partition/size/hash/MIME/schema 可重算，不含私有/付费原始状态。
- A148-02：import preflight 在零写入时拒绝未知 schema、zip-slip、重复/case collision、属性异常、超数/超大/高压缩比、额外 member、坏 size/hash/MIME 和非 allowlist 目标。
- A148-03：导入仅 no-overwrite 创建新 drama workspace，staging 失败/中断不留 partial target；round-trip 的成员 SHA、selection/render/timeline/QA/MP4 identity 一致，CLI 入口默认零网络/provider。
- A148-04：聚焦测试、语法、harness、diff check 通过；correctness、security/boundary、archive/migration 三个独立只读审查无未处理有效 finding。
- A148-05：implementation commit 后最终仅一次 `bash scripts/verify.sh` 通过并记 `mock-functional`；synthetic export/import/re-export 记 `local-e2e`，不声称 provider validation。

## Implementation Notes

- 新增 `drama-project-archive export/preflight/import` CLI 与 v1 strict manifest。ZIP 成员顺序、timestamp、JSON 编码和 fingerprint 确定性固定；压缩包 256 MiB、解压总量 512 MiB、单件 64 MiB、1024 members、manifest 2 MiB、压缩比 100 为硬上限。
- creative 不复制 canonical episode 的开放 dict，而是经 strict portable allowlist schema 重建；meta 清空 review。RenderPlan 因含完整 prompt 不入包，只保留 original canonical episode SHA、plan fingerprint 和安全计数。
- selection evidence 使用 strict typed schema，记录 exact asset version/revision/status 与 shot candidate/binding/request/revision/artifact。所有 artifact 同时绑定 owner 的 canonical prefix/path、MIME 和 schema，不能把角色图换接为镜头图或把任意 media 换接为 selected video。
- 静态 reference 当前仅支持真实 PNG。归档边界复用完整 PNG 结构/解压校验，只允许 `IHDR/PLTE/IDAT/IEND`，任何 ancillary/private chunk 都 safe-blocked；其他图片格式本轮不支持。
- semantic preflight 交叉核对 portable/source episode SHA、render source、typed selection、timeline 与全部 source bytes、strict QA report、MP4 SHA，并从 timeline 逐字节重建 SRT/ASS/edit 核验；单纯重算 ZIP/manifest hash 不能绕过这些领域绑定。
- export 在合作式 workspace lock 中完成全快照；import 逐路径分量 `O_NOFOLLOW` 读取 archive，在私有 staging 写入/fsync，再用 macOS `renamex_np(RENAME_EXCL)` 或 Linux `renameat2(RENAME_NOREPLACE)` 原子 no-overwrite commit。rename 后父目录 fsync 失败返回已提交的 `commit_uncertain`，不谎报 import failure。
- import 落地 receipt 驱动的交付快照，支持原字节 re-export；它不是可继续 provider 任务的 raw workspace，不保留 attempt ledger、完整 prompt 或 paid authorization。
- 聚焦回归暴露 iter147 `WorkbenchQaSummary` 丢失 `duration_ms/export_fingerprint` 会把完整 QA 投影判 invalid；本轮仅扩展这两个 strict allowlisted 字段，并纳入 workbench 回归。
- 三路独立只读审查发现并关闭：exact selection 证据不足、shared member 冲突、rename/fsync 语义、archive 输入父路径 symlink、target TOCTOU、creative 开放 dict 泄漏、render source/QA 断链、fake PNG/octet-stream/custom ancillary 泄漏、selection artifact owner 换接、非合作 writer 快照窗口与 optional filename 误分类。
- 已知 residual risk：archive 无签名/MAC，不证明外部 provenance；崩溃可留隐藏 staging；`commit_uncertain` 不承诺掉电耐久；无原子 no-replace libc 的平台 safe-block；PNG 像素层隐写无法由格式校验排除；hostile non-cooperating local writer 不在信任边界内。

## Acceptance Result

- `A148-01` 通过：v1 manifest 的 member path/partition/size/SHA-256/MIME/schema 可重算，ZIP 字节确定；portable creative、typed selection、selected/reference PNG、timeline/source/delivery 与脱敏 evidence 均从 current authority 明确枚举。
- `A148-02` 通过：zip-slip、绝对/反斜线、duplicate/case collision、symlink/特殊属性、bomb/上限、未登记 member、坏 size/hash/MIME/schema、伪 PNG/私有 chunk、重算后 selection/delivery/owner 换接均在 target 写入前拒绝。
- `A148-03` 通过：export→preflight→import→re-export 保持 member/project/archive、selection、render、timeline、strict QA 和 MP4 identity；import 只原子 no-overwrite 创建新 workspace，并如实区分 `confirmed/commit_uncertain`。CLI 与聚焦验证均零 provider/network。
- `A148-04` 通过：语法、harness、diff check 与 31 项聚焦回归通过。correctness、security/boundary、archive/migration 三路独立只读审查关闭全部 findings，最终无 P0-P3。
- `A148-05` 通过：implementation commit `62f4f7ac9f6f11508e8b7504e18208686c011eb7` 上只运行一次 `bash scripts/verify.sh`，2863 tests、15 steps、440 秒、exit 0；run `48433ccc61784cb189a952c2d2bebd97`，tree `d62ed3f9c7ec8dd0fdb67b4ae4e363756d9a93d0`，`tracked_scope_clean=true`，标准结论 `mock-functional` / `canonical-mock-offline`。archive synthetic round-trip 属 `local-e2e`，`provider_validated=false`。
- 真模型验证：`safe-blocked`。本地 `key.rtf` 仍只含脱敏占位而非可用 secret，且 iter147 已在同 endpoint 得到两次 401/0 model response；本轮不重复发送注定无效的请求。新增 0 HTTP/model call、0 图、0 TTS，无新增 token 或已知费用；未找到用户指向的 `sd_real_max.md`，因此不声称任何真 provider 结论。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: archive 的便携语义、默认隐私边界、strict preflight 与“快照非 runnable raw backup”是阶段 I 后仍需长期维护的 SOP，不应只留在轮次日志。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_project_archive.py` | 新增确定性 archive export/preflight/import、strict schema/语义核验、有上限 ZIP 与原子 no-overwrite import |
| `main.py` | 新增 `drama-project-archive` 三个 CLI 子命令 |
| `src/drama_production_workbench.py` | 补全 strict QA 投影的 duration/export fingerprint |
| `tests/test_drama_project_archive.py` | 新增确定性、边界、破坏 ZIP、symlink、race、durability、隐私与 CLI 回归 |
| `tests/test_drama_compose_web.py` | 新增 timeline/source/QA/MP4/assets round-trip、selection identity、字幕和 artifact owner 换接负测 |
| `tests/_drama_shot_image_base.py` | 共享 synthetic 资产改用结构正确的确定性 PNG |
| `docs/product/short_drama_module.md` | 升级 I2 实现状态与归档/导入长期 SOP |
| `docs/iterations/README.md` | 追加 iter148 索引 |
| 本文档 | 记录实现、审查、验收与残余风险 |

## 不在本轮范围

I1 画布可写 mutation/通用操作按钮、archive Web upload/download UI、增量/差分/加密归档、hostile 本地 writer 防篡改、真 provider/billing/图片/视频/TTS 与平台发布。

## Notes

计划提交信息：`docs(iter148): 迭代计划 148 立项（短剧可移植项目归档与安全导入）`。实施完成后使用 `iter-finish`收官并按事实同步 README SOP、handoff 与 PROJECT_HISTORY。
