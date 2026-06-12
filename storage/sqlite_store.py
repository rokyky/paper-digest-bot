"""SQLite 存储：去重 + 历史记录"""

import sqlite3
import os
import hashlib
import json
import logging
from typing import Optional
from datetime import datetime

from sources.base import Paper, Digest

logger = logging.getLogger(__name__)


class SQLiteStore:
    """SQLite 存储管理，负责去重和推送历史"""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """连接数据库，自动建表"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """初始化表结构"""
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                authors TEXT DEFAULT '[]',
                abstract TEXT DEFAULT '',
                source TEXT NOT NULL,
                url TEXT DEFAULT '',
                published_date TEXT DEFAULT '',
                is_engineering INTEGER DEFAULT 0,
                extra TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id INTEGER NOT NULL REFERENCES papers(id),
                one_liner TEXT DEFAULT '',
                chinese_overview TEXT DEFAULT '',
                problem TEXT DEFAULT '',
                method TEXT DEFAULT '',
                diff_from_prior TEXT DEFAULT '',
                metrics TEXT DEFAULT '',
                engineering_insight TEXT DEFAULT '',
                deployment TEXT DEFAULT '',
                limitations TEXT DEFAULT '',
                target_audience TEXT DEFAULT '',
                raw_digest TEXT DEFAULT '',
                relevance_score REAL DEFAULT 0.0,
                pushed_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_papers_external_id ON papers(external_id);
            CREATE INDEX IF NOT EXISTS idx_digests_pushed_date ON digests(pushed_date);
            CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
        """)
        self.conn.commit()

    def _gen_external_id(self, paper: Paper) -> str:
        """如果没有 external_id，用 URL 或 title 生成唯一键"""
        if paper.external_id:
            return paper.external_id
        if paper.url:
            return hashlib.sha256(paper.url.encode()).hexdigest()[:32]
        return hashlib.sha256(paper.title.encode()).hexdigest()[:32]

    def is_duplicate(self, paper: Paper) -> bool:
        """检查论文是否已在库中"""
        eid = self._gen_external_id(paper)
        cursor = self.conn.execute(
            "SELECT 1 FROM papers WHERE external_id = ? LIMIT 1", (eid,)
        )
        return cursor.fetchone() is not None

    def insert_paper(self, paper: Paper) -> Optional[int]:
        """插入论文，返回 paper_id；如果已存在则返回 None"""
        eid = self._gen_external_id(paper)
        if self.is_duplicate(paper):
            # 返回已存在的 paper_id
            row = self.conn.execute(
                "SELECT id FROM papers WHERE external_id = ?", (eid,)
            ).fetchone()
            return row["id"] if row else None

        cursor = self.conn.execute(
            """INSERT INTO papers (external_id, title, authors, abstract, source, url,
                                   published_date, is_engineering, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                paper.title,
                json.dumps(paper.authors, ensure_ascii=False),
                paper.abstract,
                paper.source,
                paper.url,
                paper.published_date or "",
                1 if paper.is_engineering else 0,
                json.dumps(paper.extra, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        logger.info("Inserted paper: %s (%s)", paper.title[:60], paper.source)
        return cursor.lastrowid

    def get_existing_external_ids(self) -> set[str]:
        """批量获取所有已存在的 external_id，用于内存中去重"""
        rows = self.conn.execute("SELECT external_id FROM papers").fetchall()
        return {row["external_id"] for row in rows}

    def insert_digest(self, digest: Digest, paper_id: int, pushed_date: str = None):
        """记录推送历史"""
        if pushed_date is None:
            pushed_date = datetime.now().strftime("%Y-%m-%d")
        self.conn.execute(
            """INSERT INTO digests (paper_id, one_liner, chinese_overview, problem, method, diff_from_prior,
                                    metrics, engineering_insight, deployment, limitations,
                                    target_audience, raw_digest, relevance_score, pushed_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                paper_id,
                digest.one_liner,
                digest.chinese_overview,
                digest.problem,
                digest.method,
                digest.diff_from_prior,
                digest.metrics,
                digest.engineering_insight,
                digest.deployment,
                digest.limitations,
                digest.target_audience,
                digest.raw_digest,
                digest.relevance_score,
                pushed_date,
            ),
        )
        self.conn.commit()
        logger.info("Recorded digest for paper_id=%s on %s", paper_id, pushed_date)

    def get_pushed_paper_ids(self) -> set[int]:
        """获取所有已推送的 paper_id"""
        rows = self.conn.execute("SELECT DISTINCT paper_id FROM digests").fetchall()
        return {row["paper_id"] for row in rows}

    def was_pushed(self, paper_id: int) -> bool:
        """检查某篇论文是否已经被推送过"""
        cursor = self.conn.execute(
            "SELECT 1 FROM digests WHERE paper_id = ? LIMIT 1", (paper_id,)
        )
        return cursor.fetchone() is not None

    def get_today_digest_count(self) -> int:
        """获取今天已经推送了多少篇论文"""
        from datetime import date
        today = date.today().isoformat()
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM digests WHERE pushed_date = ?", (today,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
