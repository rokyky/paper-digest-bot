"""工程博客 RSS/Atom 文章抓取"""

import logging
import time
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import requests

from sources.base import Paper

logger = logging.getLogger(__name__)


class EngineeringBlogSource:
    """从 RSS/Atom feed 抓取工程博客文章"""

    def __init__(self, config: dict):
        blogs = config.get("blogs", [])
        self.blogs = blogs if isinstance(blogs, list) else []
        self.lookback_hours = config.get("lookback_hours", 72)
        self.timeout = config.get("timeout", 20)

    def fetch_feed(self, blog: dict) -> list[Paper]:
        """抓取单个博客的 RSS feed"""
        name = blog.get("name", "Unknown")
        url = blog.get("url", "")
        if not url:
            logger.warning("Engineering blog '%s' has no URL, skipping", name)
            return []

        try:
            logger.info("Fetching RSS feed: %s (%s)", name, url)
            resp = requests.get(url, timeout=self.timeout, headers={"User-Agent": "PaperDigestBot/1.0"})
            resp.raise_for_status()

            # 检测编码
            if resp.encoding and resp.encoding.lower() != "utf-8":
                resp.encoding = resp.encoding
            content = resp.content

            feed = feedparser.parse(content)
            papers = []

            cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)

            for entry in feed.entries:
                published = self._parse_date(entry)
                if published and published < cutoff:
                    continue

                paper = self._parse_entry(entry, name, published)
                if paper:
                    papers.append(paper)

            logger.info("Blog '%s': got %d recent articles", name, len(papers))
            return papers

        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch blog '%s': %s", name, e)
            return []

    def _parse_date(self, entry) -> Optional[datetime]:
        """解析 feed entry 的发布日期"""
        for field in ["published_parsed", "updated_parsed"]:
            parsed = getattr(entry, field, None)
            if parsed:
                try:
                    from time import mktime
                    from datetime import timezone as dt_tz
                    return datetime.fromtimestamp(mktime(parsed), tz=dt_tz.utc)
                except Exception:
                    pass
        return None

    def _parse_entry(self, entry, blog_name: str, published: Optional[datetime]) -> Optional[Paper]:
        """解析 RSS entry 为 Paper"""
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            summary = entry.get("summary", "") or entry.get("description", "") or ""

            # 清理 HTML 标签
            summary = re.sub(r"<[^>]+>", "", summary)
            summary = summary.strip()

            # 用 link 或 title hash 作为唯一 ID
            url_hash = Paper.__hash__
            external_id = f"blog:{hash(link) % 10**12}" if link else f"blog:{hash(title) % 10**12}"

            authors = []
            if hasattr(entry, "author") and entry.author:
                authors = [entry.author]

            published_str = published.strftime("%Y-%m-%d") if published else ""

            return Paper(
                external_id=f"Blog:{link.split('/')[-1][:30] if link else title[:30]}",
                title=title,
                authors=authors,
                abstract=summary[:2000],  # 只取前 2000 字符作为摘要
                source=f"blog:{blog_name}",
                url=link,
                published_date=published_str,
                is_engineering=True,
                extra={"blog_name": blog_name, "summary_full": summary},
            )
        except Exception as e:
            logger.warning("Failed to parse RSS entry: %s", e)
            return None

    def fetch(self) -> list[Paper]:
        """抓取所有配置的博客"""
        if not self.blogs:
            logger.info("Engineering blogs: no blogs configured, skipping")
            return []

        all_papers = []
        seen_ids = set()

        for blog in self.blogs:
            papers = self.fetch_feed(blog)
            for p in papers:
                if p.external_id not in seen_ids:
                    seen_ids.add(p.external_id)
                    all_papers.append(p)
            time.sleep(1)  # 请求间隔

        logger.info("Engineering blogs: total %d unique articles", len(all_papers))
        return all_papers
