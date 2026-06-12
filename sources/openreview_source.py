"""OpenReview API 论文抓取"""

import logging
import time
from typing import Optional

import requests

from sources.base import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openreview.net"


class OpenReviewSource:
    """从 OpenReview API 抓取会议论文"""

    def __init__(self, config: dict):
        self.venues = config.get("venues", [])
        self.timeout = config.get("timeout", 30)

    def fetch_venue_notes(self, venue_id: str, limit: int = 100) -> list[dict]:
        """获取某个 venue 的所有论文"""
        url = f"{BASE_URL}/notes"
        params = {
            "invitation": f"{venue_id}/-/Blind_Submission",
            "limit": limit,
            "offset": 0,
        }

        all_notes = []
        while True:
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()

                notes = data.get("notes", [])
                all_notes.extend(notes)

                if len(notes) < limit:
                    break
                params["offset"] += limit
                time.sleep(0.5)

            except requests.exceptions.RequestException as e:
                logger.error("OpenReview fetch failed for venue %s: %s", venue_id, e)
                break

        return all_notes

    def _parse_note(self, note: dict) -> Optional[Paper]:
        """解析 OpenReview note 为 Paper"""
        try:
            content = note.get("content", {})
            # OpenReview 不同会议 content 格式不同
            title = content.get("title", {}).get("value", "") or content.get("title", "")
            abstract = content.get("abstract", {}).get("value", "") or content.get("abstract", "")
            authors = content.get("authors", {}).get("value", []) or content.get("authors", [])

            forum_id = note.get("forum", "")

            return Paper(
                external_id=f"OpenReview:{forum_id[:20]}",
                title=title.strip() if isinstance(title, str) else str(title).strip(),
                authors=authors if isinstance(authors, list) else [],
                abstract=abstract.strip() if isinstance(abstract, str) else str(abstract).strip(),
                source="openreview",
                url=f"https://openreview.net/forum?id={forum_id}",
                published_date=note.get("cdate", ""),
                is_engineering=False,
                extra={"forum_id": forum_id, "venue_id": note.get("invitation", "")},
            )
        except Exception as e:
            logger.warning("Failed to parse OpenReview note: %s", e)
            return None

    def fetch(self) -> list[Paper]:
        """抓取所有配置的 venue 的论文"""
        if not self.venues:
            logger.info("OpenReview: no venues configured, skipping")
            return []

        papers = []
        seen_ids = set()

        for venue in self.venues:
            logger.info("Fetching OpenReview venue: %s", venue)
            notes = self.fetch_venue_notes(venue)
            for note in notes:
                paper = self._parse_note(note)
                if paper and paper.external_id not in seen_ids:
                    seen_ids.add(paper.external_id)
                    papers.append(paper)

            logger.info("OpenReview: got %d papers from venue %s", len(notes), venue)
            time.sleep(1)

        logger.info("OpenReview: total %d unique papers", len(papers))
        return papers
