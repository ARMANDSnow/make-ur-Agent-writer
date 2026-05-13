# Iteration 001 - Observability Guards

## Context

这是最近一次 Codex 主导、曾尝试调度 Claude Code 的迭代。Claude Code 可启动，但在窄任务上开始过度探索仓库，最终由 Codex 中断 Claude 会话并本地完成实现。

## Plan

- 增加生成报告快照校验，防止 `chapter_manifest.md` 与 `review_summary.md` 漂移。
- 增加章节 manifest 结构校验，提前暴露重复章节、行号重叠、缺失 normalized 文件等硬错误。
- 把新校验纳入固定验收脚本。

## Implementation

- 新增 `python3 main.py check-reports`。
- 新增 `python3 main.py check-reports --update`。
- 新增 `python3 main.py check-manifest`。
- `scripts/verify.sh` 纳入 `check-manifest` 与 `check-reports`。
- README 与交接文档补充对应说明。

## Acceptance

通过：

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
bash scripts/verify.sh
```

当时测试数：45。

## Notes

`check-manifest` 当前对短章只给 warning，不阻塞验收。人工确认 101 章合理，本轮没有加入 splitter confidence 字段。
