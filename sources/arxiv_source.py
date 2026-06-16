"""arXiv API 论文抓取"""

import logging
from typing import Optional

import arxiv

from sources.base import Paper

logger = logging.getLogger(__name__)


class ArxivSource:
    """从 arXiv API 按分类和日期抓取新论文"""

    def __init__(self, config: dict):
        self.categories = config.get("categories", ["cs.IR", "cs.LG"])
        self.lookback_hours = config.get("lookback_hours", 48)
        self.max_results = config.get("max_results", 200)
        self.retry_delay = config.get("retry_delay", 10)

    def _build_query(self) -> str:
        """构建 arXiv API 查询字符串"""
        cat_queries = [f"cat:{cat}" for cat in self.categories]
        return f"({' OR '.join(cat_queries)})"

    def _parse_arxiv_result(self, result) -> Optional[Paper]:
        """将 arXiv API 返回的结果转为 Paper"""
        try:
            paper_id = result.entry_id.split("/")[-1].split("v")[0]  # 去掉版本号
            published = result.published.strftime("%Y-%m-%d") if result.published else None

            return Paper(
                external_id=f"arXiv:{paper_id}",
                title=result.title.replace("\n", " ").strip(),
                authors=[a.name for a in result.authors],
                abstract=result.summary.replace("\n", " ").strip(),
                source="arxiv",
                url=result.entry_id,
                published_date=published,
                is_engineering=False,
                extra={"comment": result.comment or "", "primary_category": str(result.primary_category)},
            )
        except Exception as e:
            logger.warning("Failed to parse arXiv result: %s", e)
            return None

    def fetch(self) -> list[Paper]:
        """抓取 arXiv 论文"""
        query = self._build_query()
        logger.info(
            "Fetching arXiv: categories=%s, lookback=%sh, max=%s",
            self.categories, self.lookback_hours, self.max_results,
        )

        papers = []
        try:
            client = arxiv.Client(
                page_size=100,
                delay_seconds=3,
                num_retries=3,
            )
            search = arxiv.Search(
                query=query,
                max_results=self.max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=self.lookback_hours)

            for result in client.results(search):
                paper = self._parse_arxiv_result(result)
                if paper:
                    papers.append(paper)

            logger.info(
                "arXiv fetched %d results (no date filter)", len(papers),
            )
        except Exception as e:
            logger.error("arXiv fetch failed: %s", e)

        return papers
