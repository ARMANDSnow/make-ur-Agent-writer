# 短剧体检遗留 backlog（2026-08）

## 边界

本文仅汇总九份每日体检报告中仍属于冻结短剧基线 `codex/short-drama@35c97cc` 的未处理项。iter168 只修改 `main` 小说续写模块，未切换、运行、测试或修改短剧分支；因此本文是 backlog，不是修复或验收声明。

## 已去重的短剧 findings

1. legacy 非成功任务在缺少 episode 证据时仍猜测为 episode 1，使恢复入口可能指向错误集数。
2. Local Demo 非成功任务仍公开未存在的 target workspace，并在任务页产生无法到达的 CTA。
3. Local Demo 仅预留 source workspace，未在完整 creative + A–F 链路期间以固定锁序同时预留 future target，存在 target 并发写入窗口。

## 需在短剧分支重新核验的 shared 安全修复

iter168 在 `main` 中闭合的以下四类 shared 边界，仍需在 `codex/short-drama` 上根据该分支的独立代码和测试重新核验，必要时手工移植：

- Web mutation 的单一策略表、framing / Content-Type / same-origin / intent 守门与付费动作逐次授权；
- provider 终态异常的 typed、metadata-only 安全投影与全 sink 禁止 raw message；
- 多章/多集完成态对当前权威 plan 和逐项 fingerprint 的 freshness 校验；
- Web 日志与 preflight 共用的 no-follow、regular-file、TOCTOU 身份复核和有界 JSONL reader。

未在短剧分支上重放这些项目前，不得声称短剧已获得 iter168 的共享修复。
