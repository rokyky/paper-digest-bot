#!/usr/bin/env python3
"""导出已推送论文到本地 markdown 文件

用法：
    python scripts/export_pushed_papers.py                          # 从队列+去重文件导出
    python scripts/export_pushed_papers.py --db data/papers.db      # 从 SQLite 导出（若存在）
    python scripts/export_pushed_papers.py --outdir docs/pushed     # 自定义输出目录

输出：
    <outdir>/<yyyy>/<mm>/<external_id>.md      — 每篇论文一个文件
    <outdir>/INDEX.md                          — 全部论文索引
"""

import argparse
import json
import sys
from pathlib import Path

# 确保项目根路径在 sys.path 中
ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

from sources.base import Paper, Digest


def _safe_filename(text: str) -> str:
    """将任意文本转为安全的文件名"""
    safe = ""
    for c in text:
        if c.isalnum() or c in "-_.":
            safe += c
        elif c in " /\\:()":
            safe += "_"
    return safe[:120].strip("_") or "paper"


def _digest_field_names(cls) -> set:
    return {f.name for f in cls.__dataclass_fields__.values()}


def export_from_queue_and_pushed_ids(root_dir: Path, outdir: Path):
    """从 digest_queue.json + pushed_ids.json 导出"""
    queue_file = root_dir / "digest_queue.json"
    dedup_file = root_dir / "pushed_ids.json"

    paper_fields = _digest_field_names(Paper)
    digest_fields = _digest_field_names(Digest)

    # 从队列中提取有完整 digest 的已推送论文
    pushed_digests = []
    if queue_file.exists():
        with open(queue_file, encoding="utf-8") as f:
            queue_entries = json.load(f)
        for entry in queue_entries:
            if entry.get("pushed"):
                paper_data = entry.get("paper", {})
                digest_data = entry.get("digest", {})
                try:
                    clean_paper = {k: v for k, v in paper_data.items() if k in paper_fields}
                    paper = Paper(**clean_paper)
                    clean_digest = {k: v for k, v in digest_data.items()
                                    if k in digest_fields and k != "paper"}
                    digest = Digest(paper=paper, **clean_digest)
                    pushed_digests.append(digest)
                except Exception as e:
                    print(f"  ⚠ 解析队列条目失败: {e}")

    # 从 pushed_ids.json 读取已推送 ID（仅用于统计，无完整内容）
    pushed_ids = set()
    if dedup_file.exists():
        with open(dedup_file, encoding="utf-8") as f:
            pushed_data = json.load(f)
            pushed_ids = set(pushed_data)
        print(f"  pushed_ids.json: {len(pushed_ids)} 个已推送论文 ID")

    print(f"  digest_queue.json: {len(pushed_digests)} 篇含完整解读的已推送论文")

    # 创建索引
    index_entries = []

    for digest in pushed_digests:
        paper = digest.paper
        eid = paper.external_id or paper.title[:30]
        safe_id = _safe_filename(eid)

        date_str = paper.published_date or "unknown"
        year = date_str[:4] if len(date_str) >= 4 else "unknown"
        month = date_str[5:7] if len(date_str) >= 7 else "00"

        file_path = outdir / year / month / f"{safe_id}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 写 md 文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {paper.title}\n\n")
            if paper.authors:
                f.write(f"**作者**: {', '.join(paper.authors[:5])}\n\n")
            f.write(f"**来源**: {paper.source} | **日期**: {paper.published_date or 'N/A'}\n\n")
            f.write(f"**原文链接**: [{paper.url}]({paper.url})\n\n")
            f.write("---\n\n")

            sections = [
                ("💡 一句话结论", digest.one_liner),
                ("🔥 30 秒类比", digest.analogy),
                ("🎯 要解决什么问题", digest.problem),
                ("⚖️ 已有方法对比", digest.method_comparison),
                ("🔬 核心方法拆解", digest.core_method),
                ("📊 实验结果", digest.results),
                ("⚠️ 局限性", digest.limitations),
                ("📖 中文精读", digest.chinese_overview),
            ]
            for icon_title, content in sections:
                if content and content.strip():
                    f.write(f"## {icon_title}\n\n{content.strip()}\n\n")

        index_entries.append({
            "title": paper.title[:80],
            "date": date_str,
            "source": paper.source,
            "url": paper.url,
            "path": str(file_path.relative_to(root_dir)),
        })

    # 写 INDEX.md
    index_path = outdir / "INDEX.md"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# 📚 已推送论文索引\n\n")
        f.write(f"> 共 {len(pushed_digests)} 篇论文\n\n")
        f.write("| # | 标题 | 日期 | 来源 | 链接 |\n")
        f.write("|---|------|------|------|------|\n")
        for i, entry in enumerate(index_entries, 1):
            title_link = f"[{entry['title']}]({entry['path']})"
            url_link = f"[原文]({entry['url']})" if entry["url"] else "-"
            f.write(f"| {i} | {title_link} | {entry['date']} | {entry['source']} | {url_link} |\n")

    print(f"\n✅ 导出完成: {len(pushed_digests)} 篇论文")
    print(f"   索引文件: {index_path}")
    print(f"   论文存储在: {outdir}/<year>/<month>/")

    if not pushed_digests and pushed_ids:
        print(f"\n⚠ 注意：当前队列中没有已推送论文的完整解读内容。")
        print(f"   有 {len(pushed_ids)} 个 ID 记录但无正文。")
        print(f"   请先运行 pipeline 推送论文后执行本脚本，或检查 digest_queue.json。")


def main():
    parser = argparse.ArgumentParser(description="导出已推论文到本地 markdown")
    parser.add_argument("--outdir", type=str, default=None,
                        help="输出目录（默认 storage/pushed/ 或配置的 local_export_dir）")
    args = parser.parse_args()

    # 优先从配置文件读取输出目录
    config_path = ROOT_DIR / "config.yaml"
    export_dir = None
    if config_path.exists():
        import yaml
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        export_dir = config.get("push", {}).get("local_export_dir", "")

    if args.outdir:
        outdir = Path(args.outdir)
    elif export_dir:
        outdir = Path(export_dir) if Path(export_dir).is_absolute() else (ROOT_DIR / export_dir)
    else:
        outdir = ROOT_DIR / "storage" / "pushed"

    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("📚 导出已推送论文到本地 markdown")
    print("=" * 60)
    export_from_queue_and_pushed_ids(ROOT_DIR, outdir)


if __name__ == "__main__":
    main()
