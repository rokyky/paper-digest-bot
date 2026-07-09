## Context

`paper-digest-bot` 是一个搜广推论文日报机器人，通过 GitHub Actions 定时抓取 arXiv / DBLP / OpenReview 等源的论文，经 LLM 筛选和解读后推送到飞书群。

当前问题：
- **流水线卡死**：`digest_queue.json` 残留 6 条未推送的 DBLP 元数据（全为空摘要），auto 模式在 8AM 检测到"有未推送内容"后跳过 collect 步骤，导致新论文无法被抓取和解读。同时 7 月 5 日代码重构更改了 Digest 类的字段结构，旧队列数据与新格式部分不兼容。
- **内容质量**：DBLP 源返回 `abstract=""`，LLM 筛选阶段无法判断相关性，导致 workshop 元数据（如音乐推荐、论文集 editorship）通过筛选。config.yaml 中 DBLP venues 配置了 2024 年会议，拉入过时论文。
- **本地持久化缺失**：已推送论文只有 `pushed_ids.json` 记录 ID，没有完整内容的本地存档。

## Goals / Non-Goals

**Goals:**
- 流水线恢复：清空陈旧队列后，auto 模式能正常每天 8AM 走 collect → push 流程
- 只推 2026+ 论文：在 pipeline 中增加年份校验，低于 2026 年的论文提前过滤
- 排除空摘要论文：DBLP 元数据（abstract=""）在 LLM 筛选前被过滤，经典论文源不受限
- DBLP 配置更新：去掉 2024 venue，只保留 2025/2026
- 推送本地存档：每篇成功推送的论文自动保存到 `E:\my-projects\arxiv-paper\raw\`
- 历史导出脚本：提供一个可复用的脚本来导出所有已推论文到本地

**Non-Goals:**
- 不重构 DBLP Source 去获取摘要（DBLP API 不提供，需要外部服务）
- 不改飞书推送逻辑或卡片模板
- 不改 LLM 筛选/解读的 prompt
- 不改 GitHub Actions 调度时间

## Decisions

### 1. 过滤位置：新增独立 Stage 2.5，而非修改现有 Stage
- **选择**：在 `_run_collect()` 的 Stage 2（去重）和 Stage 3（LLM 筛选）之间新增 `_stage_validate()` 
- **理由**：保持单一职责，去重和过滤逻辑分离；方便后续调整过滤规则而不影响去重
- **替代方案**：在 `_stage_dedup` 末尾追加过滤 → 不行，破坏去重的职责边界

### 2. 年份解析策略：从 `published_date` 解析前 4 位
- **选择**：`int(published_date[:4])`，支持 `"2026"` 和 `"2026-06-01"` 两种格式
- **理由**：宽容处理，arXiv 返回 ISO 日期，DBLP 返回纯年份字符串，classic_papers 无日期
- **例外**：无 `published_date` 的论文（None/空字符串）不触发年份过滤

### 3. 空摘要过滤范围：排除非 classic 源的空摘要
- **选择**：只有 `p.source != "classic"` 时才过滤空摘要
- **理由**：经典论文源手工维护在 `classic_papers.json`，明确是搜广推经典必读论文，不应因无摘要被过滤

### 4. 本地持久化路径与格式
- **选择**：每次推送成功后自动写入 `E:\my-projects\arxiv-paper\raw\<year>\<month>\<external_id>.md`
- **理由**：按年/月组织便于浏览；使用 GitHub Actions ubuntu 环境也能写，或在本地手动运行导出脚本
- **文件格式**：标准 markdown，保持与飞书推送一致的分段结构

### 5. 队列清空策略
- **选择**：直接清空 `digest_queue.json` 为 `[]`，`pushed_ids.json` 保留
- **理由**：`pushed_ids.json` 记录已推送 ID 用于去重，不应丢失；队列中的低质量 DBLP 条目没有保留价值

## Risks / Trade-offs

- **[丢失旧队列内容]** 清空队列会丢失 6 条未推送的解读内容 → 这些解读质量低（空摘要 DBLP 元数据），不值得保留；`pushed_ids.json` 保留已推送 ID 确保去重不受影响
- **[2025 论文也被过滤]** 如果用户想保留部分 2025 论文，当前硬编码 `min_year=2026` 太严格 → 配置化：在 `config.yaml` 的 `topic.min_year` 设置，默认 2026，可调整
- **[DBLP 2026 论文可能太少]** 2026 年的学术会议大多尚未召开，DBLP 源可能返回零结果 → 这是预期行为，主要依赖 arXiv（每日有 cs.IR/cs.LG 新论文）和 OpenReview（ICLR 2026）作为主要源
- **[导出脚本重复写入]** `_export_local_digest` 在每次推送后触发，同一个 paper_id 不会重复（`if md_path.exists(): return`）
- **[本地目录不存在]** `E:\my-projects\arxiv-paper\raw\` 可能不存在 → 代码中用 `Path.mkdir(parents=True, exist_ok=True)` 自动创建
