"""经典必读论文源：按预设 ID 列表从 arXiv 抓取"""

import logging
import json
import os
from pathlib import Path
from typing import Optional

import arxiv

from sources.base import Paper

logger = logging.getLogger(__name__)


class ClassicPaperSource:
    """读取 classic_papers.json 中的论文列表，从 arXiv 按 ID 抓取全文"""

    def __init__(self, config: dict):
        self.timeout = config.get("timeout", 30)

    def fetch(self) -> list[Paper]:
        """从 classic_papers.json 读取列表并按 arXiv ID 抓取"""
        json_path = Path(__file__).parent.parent / "classic_papers.json"
        if not json_path.exists():
            logger.warning("classic_papers.json 不存在，跳过经典论文源")
            return []

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        paper_list = data.get("papers", [])
        if not paper_list:
            logger.info("经典论文列表为空")
            return []

        # 收集所有 arXiv ID
        arxiv_ids = [p["arxiv_id"] for p in paper_list]
        logger.info("从 arXiv 抓取 %d 篇经典论文...", len(arxiv_ids))

        papers = []
        try:
            client = arxiv.Client(page_size=100, delay_seconds=1, num_retries=2)
            search = arxiv.Search(id_list=arxiv_ids, max_results=len(arxiv_ids))

            for result in client.results(search):
                paper = self._parse_result(result)
                if paper:
                    papers.append(paper)
                    logger.info("  已获取: %s", paper.title[:60])

        except Exception as e:
            logger.error("经典论文抓取失败: %s", e)

        logger.info("经典论文源: 成功获取 %d/%d 篇", len(papers), len(arxiv_ids))
        return papers

    def _parse_result(self, result) -> Optional[Paper]:
        """arXiv 结果转 Paper"""
        try:
            paper_id = result.entry_id.split("/")[-1].split("v")[0]
            published = result.published.strftime("%Y-%m-%d") if result.published else None

            return Paper(
                external_id=f"arXiv:{paper_id}",
                title=result.title.replace("\n", " ").strip(),
                authors=[a.name for a in result.authors],
                abstract=result.summary.replace("\n", " ").strip(),
                source="classic",
                url=result.entry_id,
                published_date=published,
                is_engineering=False,
                extra={"comment": result.comment or "", "primary_category": str(result.primary_category)},
            )
        except Exception as e:
            logger.warning("解析经典论文失败: %s", e)
            return None
