#!/usr/bin/env python3
"""搜广推论文日报机器人 — 主入口

Usage:
    python main.py                          # 完整运行（抓取→筛选→解读→推送）
    python main.py --dry-run                # 不推送，只打印结果
    python main.py --skip-fetch             # 跳过抓取（测试用）
    python main.py --max-papers 3           # 覆盖 config 中的 max_items
"""

import argparse
import dataclasses
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# 确保项目根路径在 sys.path 中
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

# 加载 .env 文件（在 import 模块之前）
load_dotenv(ROOT_DIR / ".env")

from sources.base import Paper, Digest
from sources.aggregator import fetch_all
from storage.sqlite_store import SQLiteStore
from llm.client import LLMClient
from llm.filter import LLMFilter
from llm.summarize import LLMSummarizer
from push.feishu import FeishuPusher

# ── 日志配置 ─────────────────────────────────────────────
def setup_logging(config: dict):
    log_dir = ROOT_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    level = getattr(logging, config.get("logging", {}).get("level", "INFO").upper(), logging.INFO)

    # StreamHandler：使用 utf-8 编码 + errors=replace 防止 GBK 终端因 emoji 崩溃
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass  # 某些环境不支持 reconfigure

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)

    file_handler = logging.FileHandler(
        log_dir / f"pipeline-{datetime.now().strftime('%Y%m%d')}.log",
        encoding="utf-8",
    )
    file_handler.setLevel(level)

    handlers = [stream_handler, file_handler]

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

    return logging.getLogger(__name__)


# ── 配置加载 ─────────────────────────────────────────────
def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = ROOT_DIR / "config.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 环境变量插值（替换 ${VAR_NAME}）
    config_str = yaml.dump(config)
    import re
    config_str = re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.getenv(m.group(1), m.group(0)),
        config_str,
    )
    config = yaml.safe_load(config_str)

    return config


def resolve_api_key(config: dict, provider: str) -> str:
    """根据 provider 获取对应的 API Key"""
    key_map = {
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "QWEN_API_KEY",
    }
    env_var = key_map.get(provider.lower())
    if not env_var:
        return ""
    return os.getenv(env_var, "")


# ── Pipeline ─────────────────────────────────────────────
class Pipeline:
    """日报生成 Pipeline"""

    def __init__(self, config: dict, dry_run: bool = False, mode: str = "auto"):
        self.config = config
        self.dry_run = dry_run
        self.mode = mode
        self.logger = logging.getLogger("pipeline")

        # Stats
        self.stats = {
            "total_fetched": 0,
            "after_dedup": 0,
            "after_validate": 0,
            "relevant": 0,
            "selected": 0,
            "digested": 0,
            "pushed": 0,
            "queued": 0,
        }

    def run(self):
        """执行 Pipeline（根据模式走不同路径）"""
        # auto 模式：8 点走 collect，其他小时走 push
        mode = self.mode
        if mode == "auto":
            hour = datetime.now().hour
            if hour == 8:
                # 检查队列是否有未推送内容（经典论文优先）
                import json as _json
                _qf = ROOT_DIR / "digest_queue.json"
                _has_unpushed = False
                if _qf.exists():
                    _data = _json.loads(_qf.read_text(encoding="utf-8"))
                    _has_unpushed = any(not e["pushed"] for e in _data)
                if _has_unpushed:
                    self.logger.info("队列有未推送内容，跳过 collect 直接 push")
                    self._run_push()
                else:
                    self.logger.info("Auto 模式: hour=%d → collect + push", hour)
                    self._run_collect()
                    if not self.dry_run:
                        self._run_push()
                return

            mode = "push"
            self.logger.info("Auto 模式: hour=%d → mode=%s", hour, mode)

        if mode == "classics":
            self._run_classics()
        elif mode == "collect":
            self._run_collect()
        else:
            self._run_push()

    def _run_classics(self):
        """Classics 模式：经典论文抓取→解读→入队列"""
        self.logger.info("=" * 60)
        self.logger.info("📚 Classics 模式：经典必读论文生成")
        self.logger.info("=" * 60)
        start_time = datetime.now()

        from sources.classic_source import ClassicPaperSource
        src = ClassicPaperSource({})
        papers = src.fetch()
        self.stats["total_fetched"] = len(papers)
        if not papers:
            self.logger.warning("没有获取到经典论文")
            return

        new_papers = self._stage_dedup(papers)
        self.stats["after_dedup"] = len(new_papers)
        if not new_papers:
            self.logger.warning("所有经典论文都已推送过")
            return

        selected = new_papers
        self.stats["selected"] = len(selected)
        self.config.setdefault("topic", {})["max_items"] = len(selected)
        digests = self._stage_summarize(selected)
        self.stats["digested"] = len(digests)
        if not digests:
            return

        if not self.dry_run:
            self._stage_enqueue(digests)
        self._print_summary(start_time)

    def _run_collect(self):
        """Collect 模式：抓取→筛选→解读→入库队列"""
        self.logger.info("=" * 60)
        self.logger.info("📦 Collect 模式：批量生成今日解读队列")
        self.logger.info("=" * 60)
        start_time = datetime.now()

        # ── Stage 1: 抓取 ──
        self.logger.info("[Stage 1/5] 多源抓取...")
        all_papers = self._stage_fetch()
        self.stats["total_fetched"] = len(all_papers)
        if not all_papers:
            self.logger.warning("没有抓取到任何论文，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 2: 去重（检查 paper 表和 pushed_ids.json）──
        self.logger.info("[Stage 2/6] 去重...")
        new_papers = self._stage_dedup(all_papers)
        self.stats["after_dedup"] = len(new_papers)
        if not new_papers:
            self.logger.warning("所有论文都已推送过，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 2.5: 质量校验（年份 + 摘要）──
        self.logger.info("[Stage 2.5/6] 质量校验...")
        validated_papers = self._stage_validate(new_papers)
        self.stats["after_validate"] = len(validated_papers)
        if not validated_papers:
            self.logger.warning("没有通过质量校验的论文，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 3: LLM 筛选 + 排序 ──
        self.logger.info("[Stage 3/6] LLM 相关性筛选 + 排序...")
        # Collect 模式需要生成足够篇数填满当天推送时间槽
        # 8 点 collect 后立即 push，10/12/14/16/18/20/22 点继续 push，共 8 篇
        self.config.setdefault("topic", {})["max_items"] = 8
        selected = self._stage_filter(validated_papers)
        self.stats["selected"] = len(selected)
        if not selected:
            self.logger.warning("没有筛选到相关论文，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 4: 深度解读 ──
        self.logger.info("[Stage 4/5] LLM 深度解读（生成全部入队列）...")
        digests = self._stage_summarize(selected)
        self.stats["digested"] = len(digests)
        if not digests:
            self.logger.warning("解读生成失败，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 5: 全部入队列 ──
        self.logger.info("[Stage 5/5] 存入队列...")
        if not self.dry_run:
            self._stage_enqueue(digests)

        self._print_summary(start_time)

    def _run_push(self):
        """Push 模式：从队列取一篇推送"""
        self.logger.info("=" * 60)
        self.logger.info("📤 Push 模式：从队列取一篇推送")
        self.logger.info("=" * 60)
        start_time = datetime.now()

        # 计算当前是今日第几篇（基于当前小时在时间表中的位置）
        schedule_hours = [8, 10, 12, 14, 16, 18, 20, 22]
        current_hour = datetime.now().hour
        positions = {h: i+1 for i, h in enumerate(schedule_hours)}
        target_pos = positions.get(current_hour, 1)

        # 从队列文件取一篇
        digest, entry = self._dequeue_from_file(target_pos)
        if not digest:
            # 回退：取第一个未推送的
            for pos in range(1, 8):
                digest, entry = self._dequeue_from_file(pos)
                if digest:
                    self.logger.info("回退到位置 %d", pos)
                    break

        if not digest:
            self.logger.warning("队列为空，跳过推送")
            self._print_summary(start_time)
            return

        self.stats["digested"] = 1

        # ── 推送 ──
        self.logger.info("[Push] 飞书推送...")
        if self.dry_run:
            self._print_dry_run([digest])
        else:
            # 先查今天已推了多少篇（用于卡片编号）
            db_path = ROOT_DIR / self.config.get("storage", {}).get("database", "data/papers.db")
            with SQLiteStore(str(db_path)) as store:
                today_count = store.get_today_digest_count()

            push_config = self.config.get("push", {}).get("feishu", {})
            topic_name = self.config.get("topic", {}).get("name", "搜广推前沿论文速报")
            pusher = FeishuPusher(push_config)
            success = pusher.push_digest(
                digests=[digest],
                topic_name=topic_name,
                total_candidates=self.stats["total_fetched"] or 1,
                daily_seq_start=today_count + 1,
            )
            self.stats["pushed"] = success

            if success > 0:
                self._mark_queue_entry_pushed(entry)
                self._record_pushed_digest(digest)
                self._sync_dedup_file()
                self._export_local_digest(digest)
            else:
                self.logger.error("推送失败，队列条目保持未推送状态")

        self._print_summary(start_time)

    def _stage_enqueue(self, digests: list[Digest]):
        """将解读存入队列文件（JSON，跟随 git 提交永久持久化）"""
        import json
        queue_file = ROOT_DIR / "digest_queue.json"
        queue = []
        for i, digest in enumerate(digests):
            entry = {
                "position": i + 1,
                "pushed": False,
                "paper": self._paper_to_dict(digest.paper),
                "digest": self._digest_to_dict(digest),
            }
            queue.append(entry)
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        self.stats["queued"] = len(queue)
        self.logger.info("已存入 %d 篇解读到队列文件", len(queue))

    def _dequeue_from_file(self, position: int) -> tuple[Optional[Digest], Optional[dict]]:
        """从队列文件中读取指定位置的未推送篇。

        注意：这里只读取，不标记 pushed。只有飞书推送成功后才落盘更新队列。
        """
        import json
        queue_file = ROOT_DIR / "digest_queue.json"
        if not queue_file.exists():
            return None, None
        with open(queue_file, encoding="utf-8") as f:
            queue = json.load(f)
        for entry in queue:
            if entry["position"] == position and not entry["pushed"]:
                paper = self._paper_from_dict(entry.get("paper", {}))
                digest = self._digest_from_dict(paper, entry.get("digest", {}))
                return digest, entry
        return None, None

    def _paper_to_dict(self, paper: Paper) -> dict:
        return dataclasses.asdict(paper)

    def _digest_to_dict(self, digest: Digest) -> dict:
        data = dataclasses.asdict(digest)
        data.pop("paper", None)
        return data

    def _paper_from_dict(self, data: dict) -> Paper:
        valid = {field.name for field in dataclasses.fields(Paper)}
        clean = {k: v for k, v in data.items() if k in valid}
        return Paper(**clean)

    def _digest_from_dict(self, paper: Paper, data: dict) -> Digest:
        valid = {field.name for field in dataclasses.fields(Digest)}
        clean = {k: v for k, v in data.items() if k in valid and k != "paper"}
        return Digest(paper=paper, **clean)

    def _mark_queue_entry_pushed(self, target_entry: dict):
        """将已成功推送的队列条目标记为 pushed。"""
        import json
        queue_file = ROOT_DIR / "digest_queue.json"
        if not queue_file.exists():
            self.logger.warning("队列文件不存在，无法标记 pushed")
            return
        with open(queue_file, encoding="utf-8") as f:
            queue = json.load(f)

        target_position = target_entry.get("position")
        target_external_id = target_entry.get("paper", {}).get("external_id")
        for entry in queue:
            if (
                entry.get("position") == target_position
                and entry.get("paper", {}).get("external_id") == target_external_id
            ):
                entry["pushed"] = True
                break
        else:
            self.logger.warning("未找到队列条目，无法标记 pushed: position=%s id=%s",
                                target_position, target_external_id)
            return

        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        self.logger.info("队列条目已标记 pushed: position=%s id=%s",
                         target_position, target_external_id)

    def _record_pushed_digest(self, digest: Digest):
        """记录成功推送历史到 SQLite。"""
        db_path = ROOT_DIR / self.config.get("storage", {}).get("database", "data/papers.db")
        with SQLiteStore(str(db_path)) as store:
            paper_id = store.insert_paper(digest.paper)
            if paper_id:
                store.insert_digest(digest, paper_id)

    def _sync_dedup_file(self):
        """同步去重记录到 pushed_ids.json"""
        import json
        queue_file = ROOT_DIR / "digest_queue.json"
        dedup_file = ROOT_DIR / "pushed_ids.json"
        try:
            pushed_ids = set()
            if dedup_file.exists():
                with open(dedup_file, encoding="utf-8") as f:
                    pushed_ids.update(json.load(f))

            if queue_file.exists():
                with open(queue_file, encoding="utf-8") as f:
                    queue = json.load(f)
                for entry in queue:
                    if entry.get("pushed"):
                        external_id = entry.get("paper", {}).get("external_id")
                        if external_id:
                            pushed_ids.add(external_id)

            with open(dedup_file, "w", encoding="utf-8") as f:
                json.dump(sorted(pushed_ids), f, ensure_ascii=False)
            self.logger.info("去重文件已同步: %d 条", len(pushed_ids))
        except Exception as e:
            self.logger.warning("去重文件同步失败: %s", e)

    # ── 论文分类词库 ───────────────────────────────────────
    _CATEGORY_KEYWORDS = {
        "召回": [
            "retrieval", "recall", "candidate generation", "matching",
            "双塔", "two-tower", "embedding retrieval", "ANN",
            "dense retrieval", "semantic matching", "vector search",
            "hard negative", "negative sampling",
        ],
        "排序": [
            "ranking", "reranking", "CTR prediction", "CVR prediction",
            "learning to rank", "click-through rate", "conversion rate",
            "排序", "精排", "粗排", "pointwise", "pairwise", "listwise",
        ],
        "生成式推荐": [
            "generative recommendation", "generative retrieval",
            "generative ranking", "TIGER", "RQVAE", "semantic ID",
            "生成式推荐", "端到端生成",
        ],
        "LLM推荐": [
            "LLM for recommendation", "LLM for advertising", "LLM for search",
            "LLM4Rec", "reasoning for recommendation", "large language model",
            "agent", "recommendation", "llm-based", "prompt",
        ],
        "广告竞价": [
            "advertising", "bidding", "auction", "sponsored search",
            "budget", "marketplace", "ad targeting",
        ],
        "多模态": [
            "multimodal", "multi-modal", "vision", "visual", "image",
            "text and image", "cross-modal",
        ],
        "特征模型": [
            "feature interaction", "multi-task learning", "multi-goal",
            "cold start", "user modeling", "personalization",
            "序列推荐", "sequential recommendation", "graph",
        ],
    }

    @staticmethod
    def _classify_paper(paper) -> str:
        """基于关键词将论文分类

        匹配规则：标题和摘要中命中最多的类别即为论文分类。
        如果全部未命中，归为"其他"。
        """
        from collections import Counter
        text = (paper.title + " " + paper.abstract).lower()
        scores = Counter()
        for cat, keywords in Pipeline._CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    scores[cat] += 1
        if scores:
            return scores.most_common(1)[0][0]
        return "其他"

    @staticmethod
    def _make_paper_filename(paper) -> str:
        """按规范生成文件名：{缩写}_{5-10字描述}.md

        规则参考：.提示词_论文精读写作规范.md
        - 前半段：从标题提取方法/模型缩写（第一个大写缩写、或竞赛名）
        - 后半段：5-10 字中文描述
        - 不包含论文全称、作者、年份、arXiv ID
        """
        title = paper.title
        title_lower = title.lower()

        # --- 前半段：提取缩写 ---
        prefix = ""
        # 优先提取括号内的模型名，如 "Sortify: ..." "LUCID: ..."
        import re
        m = re.match(r'^([A-Z][A-Za-z0-9_-]{1,20})[:\s]', title)
        if m:
            prefix = m.group(1)
        else:
            # 提取全大写的缩写词（如 LLMCluster, RQVAE, TIGER）
            m = re.search(r'\b([A-Z]{2,10})\b', title)
            if m:
                prefix = m.group(1)
            else:
                # 首单词
                first_word = title.split()[0] if title.split() else ""
                prefix = first_word[:15] if first_word else "paper"

        # --- 后半段：生成 5-10 字中文描述 ---
        # 从 keywords 中找匹配的中文
        description = ""
        cat_keywords = {
            "检索": ["retrieval", "recall", "召回", "dense retrieval", "matching", "向量检索"],
            "排序": ["ranking", "reranking", "排序", "CTR", "learning to rank"],
            "推荐": ["recommendation", "recommender", "推荐", "generative"],
            "多任务": ["multi-task", "multi-goal", "多任务", "多目标"],
            "多模态": ["multimodal", "multi-modal", "多模态", "cross-modal", "vision"],
            "序列": ["sequential", "sequence", "序列", "session"],
            "冷启动": ["cold start", "冷启动"],
            "蒸馏": ["distillation", "蒸馏", "压缩"],
            "广告": ["advertising", "bidding", "广告", "竞价", "出价"],
            "跨域": ["cross-domain", "跨域", "transfer"],
            "图": ["graph", "图神经", "GNN"],
        }
        for desc, kws in cat_keywords.items():
            for kw in kws:
                if kw in title_lower or kw in paper.abstract.lower()[:200]:
                    description = desc
                    break
            if description:
                break
        if not description and paper.extra.get("type"):
            description = paper.extra["type"]
        if not description:
            description = "论文精读"

        # 拼接
        safe_prefix = "".join(c if c.isalnum() or c in "-_" else "_" for c in prefix)[:20]
        filename = f"{safe_prefix}_{description}.md"
        return filename

    def _export_local_digest(self, digest):
        """推送成功后，将解读保存为本地 markdown 文件

        保存到：{local_export_dir}/{分类}/{文件名}.md
        文件名格式：{方法缩写}_{5-10字中文描述}.md（参考 .提示词_论文精读写作规范.md）
        分类：基于关键词自动归类到 召回/排序/生成式推荐/LLM推荐/广告竞价/多模态/特征模型/其他
        """
        try:
            from pathlib import Path

            paper = digest.paper

            # ── 1. 分类 ──
            category = self._classify_paper(paper)

            # ── 2. 生成文件名 ──
            filename = self._make_paper_filename(paper)

            # ── 3. 输出目录 ──
            export_dir = self.config.get("push", {}).get("local_export_dir", "")
            if export_dir:
                p = Path(export_dir)
                out_root = p if p.is_absolute() else (ROOT_DIR / p)
            else:
                out_root = ROOT_DIR / "storage" / "pushed"

            out_dir = out_root / category
            out_dir.mkdir(parents=True, exist_ok=True)
            md_path = out_dir / filename

            # 已存在则跳过（避免重复写入）
            if md_path.exists():
                self.logger.info("本地文档已存在，跳过: %s", md_path)
                return

            # ── 4. 提取关键信息 ──
            # 作者字符串
            author_str = ", ".join(paper.authors[:8])
            if len(paper.authors) > 8:
                author_str += " et al."

            # arXiv ID 和会议信息
            arxiv_id = ""
            venue_info = paper.published_date or ""
            if paper.extra:
                if isinstance(paper.extra, dict):
                    arxiv_id = paper.external_id.replace("arXiv:", "") if paper.external_id else ""
                    if "comment" in paper.extra and paper.extra["comment"]:
                        venue_info = paper.extra["comment"]
                    elif "venue" in paper.extra:
                        venue_info = str(paper.extra.get("venue", ""))

            # ── 5. 写文件（参考 .提示词_论文精读写作规范.md 格式）──
            title_clean = paper.title.replace("**", "").replace("$$", "")

            with open(md_path, "w", encoding="utf-8") as f:
                # -- 头部 --
                one_liner = digest.one_liner or "（待补充）"
                f.write(f"# {title_clean} — {one_liner}\n\n")

                f.write(f"> 论文：**{title_clean}**\n")
                if author_str:
                    f.write(f"> 作者：{author_str}\n")
                f.write(f"> 发表：{venue_info}\n")
                f.write(f"> 原文链接：<{paper.url}>\n\n")

                f.write("---\n\n")

                # -- 30秒类比 --
                if digest.analogy and digest.analogy.strip():
                    f.write("## 30 秒类比\n\n")
                    f.write(digest.analogy.strip())
                    f.write("\n\n---\n\n")

                # -- 要解决什么问题 --
                if digest.problem and digest.problem.strip():
                    f.write("## 一、要解决什么问题\n\n")
                    f.write(digest.problem.strip())
                    f.write("\n\n---\n\n")

                # -- 已有方法对比 --
                if digest.method_comparison and digest.method_comparison.strip():
                    f.write("## 二、已有方法对比\n\n")
                    f.write(digest.method_comparison.strip())
                    f.write("\n\n---\n\n")

                # -- 核心方法拆解 --
                if digest.core_method and digest.core_method.strip():
                    f.write("## 三、核心方法拆解\n\n")
                    f.write(digest.core_method.strip())
                    f.write("\n\n---\n\n")

                # -- 实验结果 --
                if digest.results and digest.results.strip():
                    f.write("## 四、实验结果\n\n")
                    f.write(digest.results.strip())
                    f.write("\n\n---\n\n")

                # -- 项目结合（占位，因为我们没有这个字段） --
                f.write("## 五、对搜广推项目的参考\n\n")
                f.write("> 自动生成解读尚未包含完整的项目结合分析。\n")
                f.write("> 后续可通过 LLM 补充生成此章节。\n")
                f.write("\n---\n\n")

                # -- 局限性 --
                if digest.limitations and digest.limitations.strip():
                    f.write("## 六、局限性\n\n")
                    f.write(digest.limitations.strip())
                    f.write("\n\n---\n\n")

                # -- 面试一句话 --
                if digest.one_liner and digest.one_liner.strip():
                    f.write(f"## 七、面试一句话\n\n> {digest.one_liner.strip()}\n\n")

                # -- 验证标注 --
                f.write("---\n\n")
                f.write(f"*本文由 paper-digest-bot 于 {datetime.now().strftime('%Y-%m-%d %H:%M')} 自动生成，基于 arXiv/DBLP 数据*\n")

            self.logger.info("本地文档已保存: %s （分类: %s）", md_path, category)
        except Exception as e:
            self.logger.warning("本地文档保存失败: %s", e)

    def _stage_fetch(self) -> list[Paper]:
        """Stage 1: 从所有源抓取"""
        self.logger.info("正在并发抓取论文/文章...")
        papers = fetch_all(self.config)

        if papers:
            # 按来源统计
            source_counts = {}
            for p in papers:
                source_counts[p.source] = source_counts.get(p.source, 0) + 1
            for src, cnt in sorted(source_counts.items()):
                self.logger.info("  %s: %d 篇", src, cnt)

        return papers

    def _stage_validate(self, papers: list[Paper]) -> list[Paper]:
        """Stage 2.5: 质量校验（年份 + 摘要完整性）

        确保：
        1. 论文发表日期 >= 2026（用户要求只推 26 年新论文）
        2. 有摘要内容（LLM 需要摘要判断相关性，DBLP 源返回空摘要）
        """
        min_year = self.config.get("topic", {}).get("min_year", 2026)
        validated = []
        rejected_reasons = {"old": 0, "no_abstract": 0}

        for p in papers:
            # -- 年份检查 --
            year_str = p.published_date
            year = None
            if year_str:
                try:
                    year = int(year_str[:4])  # "2026-06-01" → 2026, "2026" → 2026
                except (ValueError, TypeError):
                    pass

            if year is not None and year < min_year:
                rejected_reasons["old"] += 1
                continue

            # -- 摘要检查（DBLP 返回空 abstract，LLM 无法判断相关性）--
            if not p.abstract or p.abstract.strip() == "":
                # 允许经典论文源（classic_papers.json）不受此限制
                if p.source != "classic":
                    rejected_reasons["no_abstract"] += 1
                    continue

            validated.append(p)

        if rejected_reasons["old"] > 0:
            self.logger.info("  年份过滤: 剔除 %d 篇 < %d 年的旧论文", rejected_reasons["old"], min_year)
        if rejected_reasons["no_abstract"] > 0:
            self.logger.info("  摘要过滤: 剔除 %d 篇空摘要论文（通常为 DBLP 元数据）", rejected_reasons["no_abstract"])
        self.logger.info("  校验通过: %d / %d 篇", len(validated), len(papers))
        return validated

    def _stage_dedup(self, papers: list[Paper]) -> list[Paper]:
        """Stage 2: 去重（双重保障：SQLite + JSON 文件）"""
        db_path = ROOT_DIR / self.config.get("storage", {}).get("database", "data/papers.db")
        dedup_file = ROOT_DIR / "pushed_ids.json"  # 放在根目录，可以提交到 git

        # 收集已推送的 ID
        existing_ids: set[str] = set()

        # 第一层：SQLite
        db_ok = False
        try:
            with SQLiteStore(str(db_path)) as store:
                existing_ids = store.get_existing_external_ids()
                db_ok = True
        except Exception as e:
            self.logger.warning("SQLite 读取失败，回退到文件去重: %s", e)

        # 第二层：JSON 文件（Actions cache 更稳定）
        if not db_ok or not existing_ids:
            try:
                if dedup_file.exists():
                    import json
                    with open(dedup_file, encoding="utf-8") as f:
                        file_ids = set(json.load(f))
                    if file_ids:
                        existing_ids = file_ids
                        self.logger.info("从 JSON 文件恢复 %d 条去重记录", len(file_ids))
            except Exception as e:
                self.logger.warning("文件去重读取失败: %s", e)

        new_papers = [p for p in papers if p.external_id not in existing_ids]
        self.logger.info("去重前: %d 篇, 去重后: %d 篇（已推送 %d 篇, DB=%s）",
                         len(papers), len(new_papers), len(papers) - len(new_papers), db_ok)
        return new_papers

    def _stage_filter(self, papers: list[Paper]) -> list[Paper]:
        """Stage 3: LLM 相关性筛选 + 排序"""
        llm_config = self.config.get("llm", {})
        topic_config = self.config.get("topic", {})

        filter_config = llm_config.get("filter", {})
        api_key = resolve_api_key(self.config, filter_config.get("provider", "openai"))

        client = LLMClient(
            provider=filter_config.get("provider", "openai"),
            model=filter_config.get("model", "gpt-4o-mini"),
            api_key=api_key,
            max_tokens=filter_config.get("max_tokens", 500),
            temperature=filter_config.get("temperature", 0.1),
            base_url=filter_config.get("base_url"),
        )

        filter_ = LLMFilter(
            llm_client=client,
            config={
                "keywords": topic_config.get("keywords", []),
                "max_items": topic_config.get("max_items", 5),
                "relevance_threshold": topic_config.get("relevance_threshold", 0.5),
            },
        )

        # 初筛
        self.logger.info("初筛 %d 篇论文...", len(papers))
        relevant = filter_.filter_relevant(papers)
        self.stats["relevant"] = len(relevant)

        # 排序取 Top N
        self.logger.info("从 %d 篇相关论文中排序取 Top %d...",
                         len(relevant), topic_config.get("max_items", 5))
        selected = filter_.rank_top_n(relevant)

        for i, p in enumerate(selected):
            self.logger.info("  #%d: %s (%.2f)", i + 1, p.title[:60],
                             next((s for _, s, _ in relevant if _ == p), 0))

        return selected

    def _stage_summarize(self, papers: list[Paper]) -> list[Digest]:
        """Stage 4: LLM 深度解读"""
        llm_config = self.config.get("llm", {})
        digest_config = llm_config.get("digest", {})
        api_key = resolve_api_key(self.config, digest_config.get("provider", "openai"))

        client = LLMClient(
            provider=digest_config.get("provider", "openai"),
            model=digest_config.get("model", "gpt-4o"),
            api_key=api_key,
            max_tokens=digest_config.get("max_tokens", 4000),
            temperature=digest_config.get("temperature", 0.3),
            base_url=digest_config.get("base_url"),
        )

        summarizer = LLMSummarizer(llm_client=client)

        digests = []
        for i, paper in enumerate(papers):
            self.logger.info("[%d/%d] 解读: %s", i + 1, len(papers), paper.title[:60])
            digest = summarizer.generate_digest(paper)
            if digest:
                digests.append(digest)
            else:
                self.logger.warning("  解读失败，跳过: %s", paper.title[:40])

        return digests

    def _stage_push(self, digests: list[Digest], total_candidates: int) -> int:
        """Stage 5: 飞书推送"""
        push_config = self.config.get("push", {}).get("feishu", {})
        topic_name = self.config.get("topic", {}).get("name", "搜广推前沿日报")

        # 查今天已推送篇数，用于卡片编号（推送前查，当前这批还没入库）
        db_path = ROOT_DIR / self.config.get("storage", {}).get("database", "data/papers.db")
        with SQLiteStore(str(db_path)) as store:
            today_count = store.get_today_digest_count()
        daily_seq_start = today_count + 1

        pusher = FeishuPusher(push_config)
        success = pusher.push_digest(
            digests=digests,
            topic_name=topic_name,
            total_candidates=total_candidates,
            daily_seq_start=daily_seq_start,
        )

        if success > 0:
            self.logger.info("✅ 成功推送到 %d 个飞书 webhook", success)
        else:
            self.logger.error("❌ 推送失败（0 个 webhook 成功）")

        # 记录推送历史（SQLite + JSON 双重保险）
        pushed_ids_from_db: set[str] = set()
        with SQLiteStore(str(db_path)) as store:
            for digest in digests:
                paper_id = store.insert_paper(digest.paper)
                if paper_id:
                    store.insert_digest(digest, paper_id)
                    pushed_ids_from_db.add(digest.paper.external_id)

        # 同步写入 JSON 文件（Actions cache 更可靠）
        dedup_file = ROOT_DIR / "pushed_ids.json"
        try:
            import json
            existing = set()
            if dedup_file.exists():
                with open(dedup_file, encoding="utf-8") as f:
                    existing = set(json.load(f))
            existing.update(pushed_ids_from_db)
            with open(dedup_file, "w", encoding="utf-8") as f:
                json.dump(sorted(existing), f, ensure_ascii=False)
            self.logger.info("已写入去重文件: %d 条记录", len(existing))
        except Exception as e:
            self.logger.warning("写入去重文件失败: %s", e)

        return success

    def _print_dry_run(self, digests: list[Digest]):
        """Dry-run 模式：打印解读结果"""
        print("\n" + "=" * 60)
        print("🟡 DRY RUN MODE — 以下内容将推送到飞书")
        print("=" * 60)

        from datetime import datetime
        date_label = datetime.now().strftime("%y-%m-%d")
        for i, d in enumerate(digests):
            seq = i + 1
            print(f"\n{'─' * 60}")
            print(f"📄 {date_label}({seq}): {d.paper.title}")
            print(f"🔗 {d.paper.url}")
            print(f"{'─' * 60}")

            sections = [
                ("📖 中文精读", d.chinese_overview),
                ("💡 一句话结论", d.one_liner),
                ("🎯 解决了什么问题", d.problem),
                ("🔬 核心方法", d.method),
                ("⚡ 和已有方法的区别", d.diff_from_prior),
                ("📊 实验/业务指标", d.metrics),
                ("🛠️ 对搜广推工程的启发", d.engineering_insight),
                ("🚀 可能的落地方式", d.deployment),
                ("⚠️ 局限性/坑", d.limitations),
            ]

            for icon_title, content in sections:
                if content:
                    print(f"\n{icon_title}:")
                    print(f"  {content.strip()[:500]}")

    def _print_summary(self, start_time):
        """打印运行摘要"""
        elapsed = (datetime.now() - start_time).total_seconds()
        stats = self.stats

        print("\n" + "=" * 60)
        print("📊 运行摘要")
        print("=" * 60)
        print(f"  抓取论文:      {stats['total_fetched']:>4} 篇")
        print(f"  去重后:        {stats['after_dedup']:>4} 篇")
        print(f"  校验通过:      {stats['after_validate']:>4} 篇")
        print(f"  相关论文:      {stats['relevant']:>4} 篇")
        print(f"  最终入选:      {stats['selected']:>4} 篇")
        print(f"  解读成功:      {stats['digested']:>4} 篇")
        if not self.dry_run:
            print(f"  推送成功:      {stats['pushed']:>4} 个 webhook")
        else:
            print(f"  推送:          DRY RUN (未实际推送)")
        print(f"  耗时:          {elapsed:.0f} 秒")
        print("=" * 60)


# ── 入口 ─────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="搜广推论文日报机器人")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不推送，只打印结果",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="跳过抓取阶段（用于测试下游流程）",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=None,
        help="覆盖配置中的每日最大论文数",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "collect", "push", "classics"],
        help="运行模式: auto/collect/push/classics(经典必读论文)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(ROOT_DIR / "config.yaml"),
        help="配置文件路径",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    # 覆盖配置
    if args.max_papers is not None:
        config.setdefault("topic", {})["max_items"] = args.max_papers

    # 日志
    logger = setup_logging(config)
    logger.info("配置加载完成: %s | mode=%s", args.config, args.mode)

    # 运行 Pipeline
    pipeline = Pipeline(config, dry_run=args.dry_run, mode=args.mode)
    pipeline.run()


if __name__ == "__main__":
    main()
