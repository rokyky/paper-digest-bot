"""多源聚合：并发抓取所有源并合并结果"""

import logging
import concurrent.futures
from typing import Callable

from sources.base import Paper
from sources.arxiv_source import ArxivSource
from sources.semantic_scholar_source import SemanticScholarSource
from sources.openreview_source import OpenReviewSource
from sources.engineering_blog_source import EngineeringBlogSource

logger = logging.getLogger(__name__)


def fetch_all(config: dict) -> list[Paper]:
    """并发抓取所有已启用的源，返回去重后的论文列表"""
    sources_config = config.get("sources", {})
    fetchers: list[tuple[str, Callable[[], list[Paper]]]] = []

    # 注册已启用的数据源
    if sources_config.get("arxiv", {}).get("enabled", True):
        src = ArxivSource(sources_config["arxiv"])
        fetchers.append(("arxiv", src.fetch))

    if sources_config.get("semantic_scholar", {}).get("enabled", True):
        src = SemanticScholarSource(sources_config["semantic_scholar"])
        fetchers.append(("semantic_scholar", src.fetch))

    if sources_config.get("openreview", {}).get("enabled", True):
        src = OpenReviewSource(sources_config["openreview"])
        fetchers.append(("openreview", src.fetch))

    if sources_config.get("engineering_blog", {}).get("enabled", True):
        src = EngineeringBlogSource(sources_config["engineering_blog"])
        fetchers.append(("engineering_blogs", src.fetch))

    if not fetchers:
        logger.warning("No sources enabled in config")
        return []

    # 并发抓取
    all_papers: list[Paper] = []
    seen_ids: set[str] = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
        future_map = {executor.submit(fn): name for name, fn in fetchers}

        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                papers = future.result()
                for p in papers:
                    if p.external_id not in seen_ids:
                        seen_ids.add(p.external_id)
                        all_papers.append(p)
                logger.info("Source '%s': %d new papers after dedup", name, len(papers))
            except Exception as e:
                logger.error("Source '%s' failed with exception: %s", name, e)

    logger.info("Aggregator: total %d unique papers from all sources", len(all_papers))
    return all_papers
