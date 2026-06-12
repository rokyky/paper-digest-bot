"""Semantic Scholar API 论文抓取"""

import logging
import time
from typing import Optional

import requests

from sources.base import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarSource:
    """从 Semantic Scholar Recommendations API 获取推荐论文"""

    def __init__(self, config: dict):
        self.seed_paper_ids = config.get("seed_paper_ids", [])
        self.limit = config.get("limit", 50)
        self.api_key = config.get("api_key", "")
        self.timeout = config.get("timeout", 30)

    def _headers(self) -> dict:
        headers = {"User-Agent": "PaperDigestBot/1.0"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def fetch_recommendations_from_seed(self, paper_id: str) -> list[Paper]:
        """从单篇种子论文获取推荐"""
        url = f"{BASE_URL}/recommendations/papers"
        params = {
            "paper_id": paper_id,
            "limit": min(self.limit, 100),
            "fields": "title,authors,abstract,externalIds,url,publicationDate,citationCount",
        }

        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            papers = []
            for item in data.get("recommendedPapers", []):
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)
            return papers

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning("Semantic Scholar rate limited, waiting...")
                time.sleep(60)
                return []
            logger.error("Semantic Scholar HTTP error: %s", e)
            return []
        except requests.exceptions.RequestException as e:
            logger.error("Semantic Scholar request failed: %s", e)
            return []

    def _parse_item(self, item: dict) -> Optional[Paper]:
        """解析 Semantic Scholar API 返回的论文项"""
        try:
            ext_ids = item.get("externalIds", {})
            paper_id = ext_ids.get("ArXiv") or ext_ids.get("CorpusId") or item.get("paperId", "")

            authors = []
            for a in item.get("authors", []):
                if isinstance(a, dict) and "name" in a:
                    authors.append(a["name"])

            return Paper(
                external_id=f"SemScholar:{paper_id}",
                title=item.get("title", "").strip(),
                authors=authors,
                abstract=(item.get("abstract") or "").strip(),
                source="semantic_scholar",
                url=item.get("url", ""),
                published_date=item.get("publicationDate", ""),
                is_engineering=False,
                extra={"citation_count": item.get("citationCount", 0), "paper_id": item.get("paperId", "")},
            )
        except Exception as e:
            logger.warning("Failed to parse Semantic Scholar item: %s", e)
            return None

    def fetch(self) -> list[Paper]:
        """抓取所有种子论文的推荐"""
        if not self.seed_paper_ids:
            logger.info("Semantic Scholar: no seed papers configured, skipping")
            return []

        all_papers = []
        seen_ids = set()

        for seed_id in self.seed_paper_ids:
            logger.info("Fetching Semantic Scholar recommendations from seed: %s", seed_id)
            papers = self.fetch_recommendations_from_seed(seed_id)

            for p in papers:
                if p.external_id not in seen_ids:
                    seen_ids.add(p.external_id)
                    all_papers.append(p)

            time.sleep(1)  # 请求间隔

        logger.info(
            "Semantic Scholar: fetched %d unique papers from %d seeds",
            len(all_papers), len(self.seed_paper_ids),
        )
        return all_papers
