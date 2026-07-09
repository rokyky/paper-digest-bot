## 1. 配置更新

- [ ] 1.1 更新 `config.yaml`：DBLP venues 去掉 2024，只保留 2025/2026
- [ ] 1.2 清空 `digest_queue.json`（设为 `[]`）以解除 pipeline 阻塞
- [ ] 1.3 添加 `topic.min_year`（默认 2026）到 `config.yaml`

## 2. 校验阶段（year-abstract-filter）

- [ ] 2.1 在 Pipeline 类中新增 `_stage_validate()` 方法：解析 `published_date` 前 4 位与 `min_year` 比较，<2026 的论文过滤掉
- [ ] 2.2 在 `_stage_validate()` 中加入空摘要检查：`abstract` 为空或仅有空白时过滤（排除 `source="classic"` 的论文）
- [ ] 2.3 在 `_run_collect()` 的 Stage 2（去重）和 Stage 3（LLM 筛选）之间插入 Stage 2.5 调用 `_stage_validate()`
- [ ] 2.4 更新 Stats 字典和 `_print_summary()` 方法：增加 `after_validate` 统计项

## 3. 本地持久化（local-paper-export）

- [ ] 3.1 在 Pipeline 类中新增 `_export_local_digest()` 方法：将已推论文保存到 `storage/pushed/<year>/<month>/<external_id>.md`
- [ ] 3.2 支持的字段：标题、作者、来源、链接、one_liner、analogy、problem、method_comparison、core_method、results、limitations、chinese_overview
- [ ] 3.3 在 `_run_push()` 推送成功后调用 `_export_local_digest(digest)`
- [ ] 3.4 从 config.yaml 读取 `push.local_export_dir` 覆盖默认输出目录

## 4. 历史导出脚本（history-export-script）

- [ ] 4.1 创建 `scripts/export_pushed_papers.py`：从 `digest_queue.json` + `pushed_ids.json` 读取历史记录
- [ ] 4.2 支持 `--outdir` 参数自定义输出目录
- [ ] 4.3 生成 INDEX.md 索引文件（表格格式：序号、标题、日期、来源、链接）
