"""DBLP API 论文抓取（顶会论文）"""

import logging
import time
from typing import Optional

import requests

from sources.base import Paper

logger = logging.getLogger(__name__)

DBLP_SEARCH_URL = "https://dblp.org/search/publ/api"


class DBLPSource:
    """从 DBLP 按会议和年份抓取论文"""

    def __init__(self, config: dict):
        self.venues = config.get("venues", [])
        self.max_results = config.get("max_results", 50)
        self.timeout = config.get("timeout", 20)

    def fetch(self) -> list[Paper]:
        if not self.venues:
            logger.info("DBLP: no venues configured")
            return []
        papers = []
        seen_titles = set()
        for venue in self.venues:
            for p in self._search_venue(venue):
                key = p.title[:80].lower()
                if key not in seen_titles:
                    seen_titles.add(key)
                    papers.append(p)
            time.sleep(1)
        logger.info("DBLP: %d papers from %d venues", len(papers), len(self.venues))
        return papers

    def _search_venue(self, venue: str) -> list[Paper]:
        params = {"q": venue, "format": "json", "h": min(self.max_results, 100)}
        try:
            resp = requests.get(
                DBLP_SEARCH_URL, params=params, timeout=self.timeout,
                headers={"User-Agent": "PaperDigestBot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
        except Exception as e:
            logger.error("DBLP search '%s' failed: %s", venue, e)
            return []

        papers = []
        for hit in hits:
            try:
                info = hit.get("info", {})
                title = info.get("title", "").strip()
                if not title:
                    continue

                authors = []
                authors_data = info.get("authors", {}).get("author", [])
                if isinstance(authors_data, list):
                    authors = [a.get("text", "") for a in authors_data if isinstance(a, dict)]
                elif isinstance(authors_data, dict):
                    authors = [authors_data.get("text", "")]

                url = info.get("ee", "") or info.get("url", "")
                year = info.get("year", "")
                venue_name = info.get("venue", venue)

                external_id = f"DBLP:{venue}:{title[:40].replace(' ', '_')}"

                paper = Paper(
                    external_id=external_id,
                    title=title,
                    authors=authors,
                    abstract="",
                    source="dblp",
                    url=url,
                    published_date=str(year) if year else "",
                    is_engineering=False,
                    extra={"venue": venue_name, "type": info.get("type", "")},
                )
                papers.append(paper)
            except Exception as e:
                logger.warning("DBLP parse error: %s", e)
                continue

        return papers
