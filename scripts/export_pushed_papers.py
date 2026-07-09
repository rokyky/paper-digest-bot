#!/usr/bin/env python3
"""导出已推送论文到本地 markdown 文件（按分类归档）

用法：
    python scripts/export_pushed_papers.py --outdir E:/my-projects/arxiv-paper

输出：
    <outdir>/<分类>/<文件名>.md       — 每篇论文一个文件
    <outdir>/INDEX.md                 — 全部论文索引

分类：召回/排序/生成式推荐/LLM推荐/广告竞价/多模态/特征模型/其他
文件名：{方法缩写}_{5-10字中文描述}.md（参考 .提示词_论文精读写作规范.md）
"""

import argparse
import json
import sys
import re
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

from sources.base import Paper, Digest


# ── 分类词库（与 main.py 保持一致）──
CATEGORY_KEYWORDS = {
    "召回": [
        "retrieval", "recall", "candidate generation", "matching",
        "双塔", "two-tower", "embedding retrieval", "ANN",
        "dense retrieval", "semantic matching", "vector search",
        "hard negative", "negative sampling",
    ],
    "排序": [
        "ranking", "reranking", "CTR prediction", "CVR prediction",
        "learning to rank", "click-through rate", "conversion rate",
        "排序", "精排", "粗排", "pointwise", "pairwise", "listwise",
    ],
    "生成式推荐": [
        "generative recommendation", "generative retrieval",
        "generative ranking", "TIGER", "RQVAE", "semantic ID",
        "生成式推荐", "端到端生成",
    ],
    "LLM推荐": [
        "LLM for recommendation", "LLM for advertising", "LLM for search",
        "LLM4Rec", "reasoning for recommendation", "large language model",
        "agent", "recommendation", "llm-based", "prompt",
    ],
    "广告竞价": [
        "advertising", "bidding", "auction", "sponsored search",
        "budget", "marketplace", "ad targeting",
    ],
    "多模态": [
        "multimodal", "multi-modal", "vision", "visual", "image",
        "text and image", "cross-modal",
    ],
    "特征模型": [
        "feature interaction", "multi-task learning", "multi-goal",
        "cold start", "user modeling", "personalization",
        "序列推荐", "sequential recommendation", "graph",
    ],
}


def classify_paper(paper) -> str:
    """基于关键词分类"""
    text = (paper.title + " " + paper.abstract).lower()
    scores = Counter()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[cat] += 1
    if scores:
        return scores.most_common(1)[0][0]
    return "其他"


def make_paper_filename(paper) -> str:
    """按规范生成文件名：{缩写}_{5-10字描述}.md"""
    title = paper.title
    title_lower = title.lower()

    # 前半段：提取缩写
    prefix = ""
    m = re.match(r'^([A-Z][A-Za-z0-9_-]{1,20})[:\s]', title)
    if m:
        prefix = m.group(1)
    else:
        m = re.search(r'\b([A-Z]{2,10})\b', title)
        if m:
            prefix = m.group(1)
        else:
            first_word = title.split()[0] if title.split() else ""
            prefix = first_word[:15] if first_word else "paper"

    # 后半段：中文描述
    abstract_lower = paper.abstract.lower()[:200]
    description = ""
    cat_keywords = {
        "检索": ["retrieval", "recall", "召回", "dense retrieval", "matching", "向量检索"],
        "排序": ["ranking", "reranking", "排序", "CTR", "learning to rank"],
        "推荐": ["recommendation", "recommender", "推荐", "generative"],
        "多任务": ["multi-task", "multi-goal", "多任务", "多目标"],
        "多模态": ["multimodal", "multi-modal", "多模态"],
        "序列": ["sequential", "sequence", "序列"],
        "冷启动": ["cold start", "冷启动"],
        "蒸馏": ["distillation", "蒸馏", "压缩"],
        "广告": ["advertising", "bidding", "广告"],
        "跨域": ["cross-domain", "跨域"],
        "图": ["graph", "图神经", "GNN"],
    }
    for desc, kws in cat_keywords.items():
        for kw in kws:
            if kw in title_lower or kw in abstract_lower:
                description = desc
                break
        if description:
            break

    if not description:
        description = "论文精读"

    safe_prefix = "".join(c if c.isalnum() or c in "-_" else "_" for c in prefix)[:20]
    return f"{safe_prefix}_{description}.md"


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
                    print(f"  ! 解析队列条目失败: {e}")

    # 统计
    pushed_ids = set()
    if dedup_file.exists():
        with open(dedup_file, encoding="utf-8") as f:
            pushed_ids = set(json.load(f))

    print(f"  pushed_ids.json: {len(pushed_ids)} 个已推送论文 ID")
    print(f"  digest_queue.json: {len(pushed_digests)} 篇含完整解读的已推送论文")

    # 导出
    index_entries = []
    for digest in pushed_digests:
        paper = digest.paper
        category = classify_paper(paper)
        filename = make_paper_filename(paper)

        file_path = outdir / category / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 如果已存在则跳过
        if file_path.exists():
            print(f"  跳过（已存在）: {category}/{filename}")
            index_entries.append({
                "title": paper.title[:80],
                "date": paper.published_date or "",
                "source": paper.source,
                "url": paper.url,
                "path": str(file_path.relative_to(root_dir)),
            })
            continue

        # 写文件
        author_str = ", ".join(paper.authors[:8])
        if len(paper.authors) > 8:
            author_str += " et al."
        venue_info = paper.published_date or ""
        if paper.extra and isinstance(paper.extra, dict):
            if "comment" in paper.extra and paper.extra["comment"]:
                venue_info = paper.extra["comment"]
            elif "venue" in paper.extra:
                venue_info = str(paper.extra.get("venue", ""))

        title_clean = paper.title.replace("**", "").replace("$$", "")
        one_liner = digest.one_liner or "（待补充）"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {title_clean} — {one_liner}\n\n")
            f.write(f"> 论文：**{title_clean}**\n")
            if author_str:
                f.write(f"> 作者：{author_str}\n")
            f.write(f"> 发表：{venue_info}\n")
            f.write(f"> 原文链接：<{paper.url}>\n\n")
            f.write("---\n\n")

            if digest.analogy and digest.analogy.strip():
                f.write("## 30 秒类比\n\n")
                f.write(digest.analogy.strip())
                f.write("\n\n---\n\n")
            if digest.problem and digest.problem.strip():
                f.write("## 一、要解决什么问题\n\n")
                f.write(digest.problem.strip())
                f.write("\n\n---\n\n")
            if digest.method_comparison and digest.method_comparison.strip():
                f.write("## 二、已有方法对比\n\n")
                f.write(digest.method_comparison.strip())
                f.write("\n\n---\n\n")
            if digest.core_method and digest.core_method.strip():
                f.write("## 三、核心方法拆解\n\n")
                f.write(digest.core_method.strip())
                f.write("\n\n---\n\n")
            if digest.results and digest.results.strip():
                f.write("## 四、实验结果\n\n")
                f.write(digest.results.strip())
                f.write("\n\n---\n\n")
            f.write("## 五、对搜广推项目的参考\n\n")
            f.write("> 自动生成解读尚未包含完整的项目结合分析。\n")
            f.write("> 后续可通过 LLM 补充生成此章节。\n")
            f.write("\n---\n\n")
            if digest.limitations and digest.limitations.strip():
                f.write("## 六、局限性\n\n")
                f.write(digest.limitations.strip())
                f.write("\n\n---\n\n")
            if digest.one_liner and digest.one_liner.strip():
                f.write("## 七、面试一句话\n\n")
                f.write(f"> {digest.one_liner.strip()}\n\n")

            from datetime import datetime
            f.write("---\n")
            f.write(f"*本文由 paper-digest-bot 于 {datetime.now().strftime('%Y-%m-%d %H:%M')} 自动生成，基于 arXiv/DBLP 数据*\n")

        index_entries.append({
            "title": paper.title[:80],
            "date": paper.published_date or "",
            "source": paper.source,
            "url": paper.url,
            "path": str(file_path.relative_to(root_dir)),
        })

        print(f"  已导出: {category}/{filename}")

    # 写 INDEX.md
    index_path = outdir / "INDEX.md"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# 论文索引\n\n")
        f.write(f"> 共 {len(pushed_digests)} 篇论文\n\n")

        # 按分类分组
        from collections import defaultdict
        by_cat = defaultdict(list)
        for entry in index_entries:
            rel = entry["path"]
            cat = rel.split("/")[0] if "/" in rel else "其他"
            by_cat[cat].append(entry)

        for cat in sorted(by_cat.keys()):
            entries = by_cat[cat]
            f.write(f"## {cat} ({len(entries)} 篇)\n\n")
            f.write("| # | 标题 | 日期 | 来源 |\n")
            f.write("|---|------|------|------|\n")
            for i, entry in enumerate(entries, 1):
                title_link = f"[{entry['title']}]({entry['path']})"
                f.write(f"| {i} | {title_link} | {entry['date']} | {entry['source']} |\n")
            f.write("\n")

    print(f"\n  索引文件: {index_path}")
    if not pushed_digests:
        print("  注意：队列中没有已推送论文的完整解读内容。")


def main():
    parser = argparse.ArgumentParser(description="导出已推论文到本地（按分类归档）")
    parser.add_argument("--outdir", type=str, default=None,
                        help="输出根目录（默认 config.yaml 中的 local_export_dir 或 storage/pushed/）")
    args = parser.parse_args()

    # 从配置文件读取输出目录
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
    print("导出已推送论文到本地 markdown（按分类归档）")
    print("=" * 60)
    export_from_queue_and_pushed_ids(ROOT_DIR, outdir)


if __name__ == "__main__":
    main()
