## Why

论文日报机器人流水线自 7 月 5 日代码重构后停止推送新内容。同时存在三个内容质量问题：推过与搜广推无关的文章（如音乐推荐 workshop）、推过 2024/2025 年的过时论文、已推送论文没有持久化到本地文档。需要修复和优化。

## What Changes

1. **修复流水线卡死** — 清空当前陈旧的 digest_queue（全为 DBLP 空摘要元数据），让 auto 模式在 8AM 能正常走 collect 流程
2. **增加质量校验阶段** — 在 LLM 筛选前新增 Stage 2.5，过滤掉 <2026 的旧论文（限只推 26 年新论文）
3. **增加空摘要过滤** — 排除 DBLP 返回的 `abstract=""` 论文（LLM 无法判断相关性），经典论文源不受此限制
4. **更新 DBLP 源配置** — 去掉 2024 年 venue，仅保留 2025/2026；2026 年前的顶会论文不会再被拉入
5. **推送本地持久化** — 推送成功后自动保存 markdown 文件到指定目录 `E:\my-projects\arxiv-paper\raw\`
6. **创建历史导出脚本** — `scripts/export_pushed_papers.py` 从 `digest_queue.json` + `pushed_ids.json` 导出所有已推送论文到本地文档

## Capabilities

### New Capabilities
- `year-abstract-filter`: 在 LLM 筛选前按年份(>=2026)和摘要完整性过滤论文
- `local-paper-export`: 推送成功后自动将解读内容保存为本地 markdown 文件
- `history-export-script`: 独立的可复用导出脚本，可从队列 + 去重文件导出全部历史推送

### Modified Capabilities
- (无 — 新项目尚无已有 specs)

## Impact

- `main.py` — Pipeline 类新增 `_stage_validate()` 和 `_export_local_digest()` 方法；`_run_collect()` 增加 Stage 2.5 调用；`_run_push()` 增加推送后本地导出调用；`_print_summary()` 增加校验通过统计
- `config.yaml` — DBLP venues 去掉 2024，增加 2026
- `digest_queue.json` — 清空为 `[]`
- `scripts/export_pushed_papers.py` — 新建导出脚本
