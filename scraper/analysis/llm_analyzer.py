"""
LLM analysis module: DeepSeek API integration for book intro analysis and report generation.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_BATCH = 30
MAX_TOTAL_BOOKS = 120

EXTRACTION_PROMPT = """你是一位资深的网文编辑，擅长从小说简介中快速识别作品的核心要素。下面是一批起点中文网的小说简介，请你逐一分析每本书，提取以下信息并以 JSON 格式返回。

对于每本书返回一个 JSON 对象，包含这些字段：
- "title": 书名（原文保留）
- "genre_tags": 流派标签数组，例如 ["穿越", "系统流", "重生", "修炼", "种田", "末世", "星际", "机甲", "无限流", "洪荒", "凡人流", "快穿", "灵气复苏", "悬疑", "灵异", "宫斗", "权谋", "游戏", "盗墓", "神医", "兵王", "鉴宝", "直播", "校园", "家族"] 等，选最匹配的2-5个
- "protagonist_archetype": 主角人设，从以下选一个：废柴逆袭、天才流、扮猪吃虎、重生复仇、穿越者、普通人生存、无敌流、苟道稳健、其他
- "golden_finger": 金手指类型，从以下选一个：系统、传承/老爷爷、重生知识、特殊血脉/体质、签到/抽奖、无/未提及、其他
- "world_keywords": 世界观关键词数组，例如 ["修真", "宗门", "秘境", "天劫", "灵根", "金丹", "元婴", "全息游戏", "丧尸", "异能", "星际殖民", "宫墙", "朝堂"] 等，选2-5个最有辨识度的

返回格式：
```json
[
  {"title": "书名1", "genre_tags": ["标签1", "标签2"], "protagonist_archetype": "类型", "golden_finger": "金手指", "world_keywords": ["关键词1", "关键词2"]},
  ...
]
```

只返回 JSON 数组，不要包含任何解释文字。

以下是书籍列表（书名 + 分类 + 简介）："""


REPORT_PROMPT = """你是一位网文行业资深分析师，请根据以下数据分析结果，撰写一份本周网文市场分析报告。

报告要求：
1. 语言风格：专业但不失文学性，适合网文创作者阅读
2. 篇幅：800-1200字中文
3. 结构：
   - **## 本周概览**：数据概况（分析了多少本书、覆盖多少品类）、整体市场情绪
   - **## 题材风向**：热门流派标签排行、新兴题材趋势、值得关注的题材变化
   - **## 人设与金手指趋势**：主角人设分布、金手指类型变化规律
   - **## 创作建议**：基于数据给出2-3条具体的写作方向建议

请使用 Markdown 格式输出，二级标题用 ##，加粗用 **文本**。

以下是分析数据："""


def _get_client():
    """Create an OpenAI-compatible client pointing at DeepSeek."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")

    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def _build_extraction_prompt(books_batch: list[dict]) -> str:
    """Build a prompt for the extraction task."""
    lines = []
    for i, book in enumerate(books_batch, 1):
        lines.append(
            f"{i}. 《{book.get('title', '未知')}》"
            f" [{book.get('category', '未知')}]"
            f"\n   简介：{book.get('intro', '无')[:200]}"
        )
    return EXTRACTION_PROMPT + "\n\n" + "\n".join(lines)


def _parse_llm_response(text: str, books_batch: list[dict]) -> list[dict]:
    """Parse JSON from LLM response. Falls back to regex extraction on malformed JSON."""
    # Try to extract JSON from code block or raw text
    json_str = text
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_match:
        json_str = code_match.group(1)

    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: try to extract array with regex
    array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", json_str)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse LLM response as JSON, response length: %d", len(text))
    return []


def batch_analyze_books(books: list[dict]) -> list[dict]:
    """Analyze books in batches via DeepSeek API. Returns enriched book records."""
    client = _get_client()
    # Select top books by rank diversity for cost control
    sample = books[:MAX_TOTAL_BOOKS]
    results = []

    for batch_start in range(0, len(sample), MAX_BATCH):
        batch = sample[batch_start: batch_start + MAX_BATCH]
        prompt = _build_extraction_prompt(batch)

        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": "你是一个精确的 JSON 输出机器。只返回 JSON 数组，不要包含任何解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=4096,
                )
                text = response.choices[0].message.content or ""
                parsed = _parse_llm_response(text, batch)
                if parsed:
                    results.extend(parsed)
                    logger.info("Batch %d-%d: extracted %d books", batch_start + 1, batch_start + len(batch), len(parsed))
                else:
                    logger.warning("Batch %d-%d: empty parse, retrying...", batch_start + 1, batch_start + len(batch))
                    continue
                break
            except Exception as e:
                logger.warning("Batch %d-%d attempt %d failed: %s", batch_start + 1, batch_start + len(batch), attempt + 1, e)
                if attempt < 2:
                    time.sleep(2)
        else:
            logger.error("Batch %d-%d: all retries exhausted", batch_start + 1, batch_start + len(batch))

        time.sleep(0.5)  # Rate limiting

    return results


def _build_aggregations(insights: list[dict]) -> dict:
    """Compute aggregated statistics from LLM insights."""
    from collections import Counter
    tag_counter = Counter()
    archetype_counter = Counter()
    golden_finger_counter = Counter()
    world_kw_counter = Counter()

    for item in insights:
        for tag in item.get("genre_tags", []):
            tag_counter[tag] += 1
        arch = item.get("protagonist_archetype", "其他")
        archetype_counter[arch] += 1
        gf = item.get("golden_finger", "其他")
        golden_finger_counter[gf] += 1
        for kw in item.get("world_keywords", []):
            world_kw_counter[kw] += 1

    return {
        "top_genre_tags": [{"tag": t, "count": c} for t, c in tag_counter.most_common(30)],
        "archetype_distribution": [{"type": t, "count": c} for t, c in archetype_counter.most_common()],
        "golden_finger_distribution": [{"type": t, "count": c} for t, c in golden_finger_counter.most_common()],
        "top_world_keywords": [{"keyword": k, "count": c} for k, c in world_kw_counter.most_common(30)],
    }


def generate_market_report(insights: list[dict], aggregations: dict, keywords: dict, genre_tags: dict) -> str:
    """Generate a natural language weekly market report using DeepSeek."""
    client = _get_client()

    # Build a compact data summary for the prompt
    data_summary = f"""
**数据概况**
- 分析书籍数：{len(insights)} 本
- TF-IDF 关键词提取数：{len(keywords.get('tokens', []))} 个
- 流派标签覆盖数：{genre_tags.get('books_with_tags', 0)} 本

**热门流派标签 Top 10**
{json.dumps(aggregations.get('top_genre_tags', [])[:10], ensure_ascii=False)}

**主角人设分布**
{json.dumps(aggregations.get('archetype_distribution', []), ensure_ascii=False)}

**金手指类型分布**
{json.dumps(aggregations.get('golden_finger_distribution', []), ensure_ascii=False)}

**热门世界观关键词 Top 15**
{json.dumps(aggregations.get('top_world_keywords', [])[:15], ensure_ascii=False)}

**全站 TF-IDF 关键词 Top 10**
{json.dumps(keywords.get('top', [])[:10], ensure_ascii=False)}

**Top 流派标签共现**
{json.dumps(genre_tags.get('cooccurrences', [])[:10], ensure_ascii=False)}
"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是网文行业资深分析师，擅长用数据洞察写作趋势，文风专业优雅。"},
                {"role": "user", "content": REPORT_PROMPT + "\n\n" + data_summary},
            ],
            temperature=0.7,
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error("Failed to generate market report: %s", e)
        return f"## 本周概览\n\n报告生成失败：{e}\n\n请稍后重试。"


def run_llm_analysis(data_dir: Path = None, week_label: str = None) -> dict:
    """Run LLM analysis: extract insights from intros and generate weekly report."""
    if data_dir is None:
        data_dir = DATA_DIR

    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        error_data = {"error": "API key not configured", "updated_at": datetime.now().isoformat()}
        with open(analysis_dir / "llm_insights.json", "w", encoding="utf-8") as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)
        with open(analysis_dir / "weekly_report.md", "w", encoding="utf-8") as f:
            f.write("## AI 分析暂不可用\n\nDeepSeek API Key 未配置，请设置 `OPENAI_API_KEY` 环境变量后重新运行。\n")
        logger.warning("OPENAI_API_KEY not set, skipping LLM analysis")
        return error_data

    # Load latest week data
    if week_label:
        week_path = data_dir / f"{week_label}.json"
        with open(week_path, "r", encoding="utf-8") as f:
            week_data = json.load(f)
        books = week_data.get("books", [])
    else:
        # Use latest week
        books = _load_latest_books(data_dir)

    if not books:
        logger.error("No books found for LLM analysis")
        return {"error": "No books found"}

    # Deduplicate by (title, author)
    seen = set()
    deduped = []
    for b in books:
        key = (b.get("title", ""), b.get("author", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(b)
    books = deduped

    logger.info("LLM analysis on %d unique books (from %d total)", len(books), len(books))

    # Batch analyze
    insights = batch_analyze_books(books)
    logger.info("LLM extracted insights for %d books", len(insights))

    # Aggregate
    aggregations = _build_aggregations(insights)

    # Load text mining results for report context
    keywords = {}
    genre_tags = {}
    try:
        with open(analysis_dir / "keywords.json", "r", encoding="utf-8") as f:
            keywords = json.load(f)
    except Exception:
        pass
    try:
        with open(analysis_dir / "genre_tags.json", "r", encoding="utf-8") as f:
            genre_tags = json.load(f)
    except Exception:
        pass

    # Generate report
    report = generate_market_report(insights, aggregations, keywords, genre_tags)

    # Save outputs
    llm_output = {
        "updated_at": datetime.now().isoformat(),
        "model": DEEPSEEK_MODEL,
        "n_books": len(insights),
        "books": insights,
        "aggregations": aggregations,
    }
    with open(analysis_dir / "llm_insights.json", "w", encoding="utf-8") as f:
        json.dump(llm_output, f, ensure_ascii=False, indent=2)
    logger.info("Saved llm_insights.json (%d books)", len(insights))

    with open(analysis_dir / "weekly_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    logger.info("Saved weekly_report.md (%d chars)", len(report))

    return {"n_books": len(insights), "report_length": len(report)}


def _load_latest_books(data_dir: Path) -> list[dict]:
    """Load books from the most recent valid week file."""
    week_files = sorted(
        [f for f in data_dir.glob("*.json") if f.name != "index.json"],
        key=lambda f: f.name,
        reverse=True,
    )
    for fpath in week_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if snap.get("total", 0) >= 1000:
                logger.info("Loading books from %s (%d books)", fpath.name, snap.get("total", 0))
                return snap.get("books", [])
        except Exception:
            continue
    return []
