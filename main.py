#!/usr/bin/env python3
"""搜广推论文日报机器人 — 主入口

Usage:
    python main.py                          # 完整运行（抓取→筛选→解读→推送）
    python main.py --dry-run                # 不推送，只打印结果
    python main.py --skip-fetch             # 跳过抓取（测试用）
    python main.py --max-papers 3           # 覆盖 config 中的 max_items
"""

import argparse
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

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

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / f"pipeline-{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
    ]

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

    def __init__(self, config: dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.logger = logging.getLogger("pipeline")

        # Stats
        self.stats = {
            "total_fetched": 0,
            "after_dedup": 0,
            "relevant": 0,
            "selected": 0,
            "digested": 0,
            "pushed": 0,
        }

    def run(self):
        """执行完整 Pipeline"""
        self.logger.info("=" * 60)
        self.logger.info("搜广推日报 Pipeline 启动 (dry_run=%s)", self.dry_run)
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

        # ── Stage 2: 去重 ──
        self.logger.info("[Stage 2/5] 去重...")
        new_papers = self._stage_dedup(all_papers)
        self.stats["after_dedup"] = len(new_papers)
        if not new_papers:
            self.logger.warning("所有论文都已推送过，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 3: 相关性筛选 + 排序 ──
        self.logger.info("[Stage 3/5] LLM 相关性筛选 + 排序...")
        selected = self._stage_filter(new_papers)
        self.stats["selected"] = len(selected)
        if not selected:
            self.logger.warning("没有筛选到相关论文，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 4: 深度解读 ──
        self.logger.info("[Stage 4/5] LLM 深度解读...")
        digests = self._stage_summarize(selected)
        self.stats["digested"] = len(digests)
        if not digests:
            self.logger.warning("解读生成失败，提前终止")
            self._print_summary(start_time)
            return

        # ── Stage 5: 推送 ──
        self.logger.info("[Stage 5/5] 飞书推送...")
        if self.dry_run:
            self._print_dry_run(digests)
        else:
            pushed = self._stage_push(digests, len(all_papers))
            self.stats["pushed"] = pushed

        # ── 完成 ──
        self._print_summary(start_time)

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
    logger.info("配置加载完成: %s", args.config)

    # 运行 Pipeline
    pipeline = Pipeline(config, dry_run=args.dry_run)
    pipeline.run()


if __name__ == "__main__":
    main()
