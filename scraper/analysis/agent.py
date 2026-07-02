"""
ReAct Agent module: autonomous data analysis agent with tool calling,
FAQ generation, and structured report output.
"""

import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_ROUNDS = 8

SYSTEM_PROMPT = """你是"天机"，起点中文网的数据分析 Agent。你的任务是自主探索本周排行榜数据，撰写一份深度的网文创作风向分析报告。

## 可用工具
你可以调用以下工具来获取数据：
- `get_weekly_stats(week)` — 获取指定周的总览统计（总书籍数、独立作者数、品类数、各榜书籍分布）
- `get_category_trend(category)` — 获取某个品类的多周热度趋势（历史周热度值序列）
- `get_top_books(week, rank_type, n)` — 获取某榜 Top N 书籍列表（书名、作者、品类、排名）
- `get_keywords(week)` — 获取该周 TF-IDF 关键词 Top 20
- `get_genre_distribution(week)` — 获取该周流派标签分布（标签名 + 频次）
- `compare_weeks(week1, week2)` — 对比两周的变化（新增/消失的书籍、各品类热度变化）

## 工作流程
1. 首先获取数据总览，了解数据规模和结构
2. 探索品类趋势，发现热门品类和增长品类
3. 分析关键词和流派分布，识别写作风向
4. 对比周与周之间的变化，捕捉市场动态
5. 基于以上分析，撰写报告

## 报告要求
完成数据探索后，请撰写一份完整的分析报告，使用以下格式：

### 报告格式
使用 Markdown，结构如下：

## 本周概览
数据概况 + 整体市场情绪（2-3 段）

## 题材风向
热门品类变化 + 新兴题材趋势 + 值得关注的品类（3-4 段）

## 关键词与流派洞察
TF-IDF 关键词反映的创作热点 + 流派标签的分布变化（2-3 段）

## 创作建议
基于以上数据，给出 3-4 条具体的网文创作方向建议

## FAQ
基于你的分析，生成 10-15 个创作者可能关心的问题及其答案。格式：
**Q: 问题内容**
A: 答案内容

请在报告开头用 `<REPORT>` 标记，结尾用 `</REPORT>` 标记。FAQ 部分放在报告内部。
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weekly_stats",
            "description": "获取指定周的总览统计：总书籍数、独立作者数、品类数、各榜书籍分布",
            "parameters": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "周标签，如 2026-W27；不传则使用最新周"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_trend",
            "description": "获取某个品类的多周热度趋势数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "品类名称，如 玄幻、都市、仙侠"}
                },
                "required": ["category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_books",
            "description": "获取某榜 Top N 书籍列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "周标签，不传则使用最新周"},
                    "rank_type": {
                        "type": "string",
                        "description": "榜单类型：yuepiao/hotsales/readindex/recom/collect/signnewbook/newfans/vipup",
                        "enum": ["yuepiao", "hotsales", "readindex", "recom", "collect", "signnewbook", "newfans", "vipup"]
                    },
                    "n": {"type": "integer", "description": "返回前 N 本，默认 10，最大 20"}
                },
                "required": ["rank_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_keywords",
            "description": "获取该周 TF-IDF 关键词 Top 20，含分词权重",
            "parameters": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "周标签，不传则使用最新周"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_genre_distribution",
            "description": "获取该周流派标签分布（标签名 + 频次 + 共现关系）",
            "parameters": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "周标签，不传则使用最新周"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_weeks",
            "description": "对比两周的数据变化：新增/消失的书籍数、各品类热度变化幅度",
            "parameters": {
                "type": "object",
                "properties": {
                    "week1": {"type": "string", "description": "基准周标签，如 2026-W26"},
                    "week2": {"type": "string", "description": "对比周标签，如 2026-W27"}
                },
                "required": ["week1", "week2"]
            }
        }
    },
]

RANK_LABELS = {
    "yuepiao": "月票榜", "hotsales": "畅销榜", "readindex": "阅读指数榜",
    "recom": "推荐榜", "collect": "收藏榜", "signnewbook": "签约新书榜",
    "newfans": "书友榜", "vipup": "更新榜",
}

RANK_WEIGHTS = {
    "yuepiao": 1.0, "hotsales": 0.95, "readindex": 0.85,
    "recom": 0.8, "collect": 0.75, "signnewbook": 0.7, "newfans": 0.6, "vipup": 0.5,
}


def _get_client():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def _load_week(data_dir: Path, week_label: str = None) -> dict:
    """Load a specific week or the latest week."""
    if week_label:
        path = data_dir / f"{week_label}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return None

    weeks_files = sorted(
        [f for f in data_dir.glob("*.json") if f.name != "index.json"],
        key=lambda f: f.name
    )
    for fpath in reversed(weeks_files):
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("total", 0) >= 1000:
            return data
    return None


def _load_all_weeks(data_dir: Path) -> list[dict]:
    idx_path = data_dir / "index.json"
    if not idx_path.exists():
        return []
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    weeks = []
    for w in idx.get("weeks", []):
        if w.get("total", 0) < 1000:
            continue
        fpath = data_dir / w["file"]
        if fpath.exists():
            with open(fpath, encoding="utf-8") as f:
                weeks.append(json.load(f))
    weeks.sort(key=lambda w: w["week"])
    return weeks


def _load_analysis_file(data_dir: Path, filename: str) -> dict:
    path = data_dir / "analysis" / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ── Tool implementations ──

def _tool_get_weekly_stats(week: str = None) -> str:
    data = _load_week(DATA_DIR, week)
    if not data:
        return json.dumps({"error": "周数据不可用"}, ensure_ascii=False)

    authors = set()
    categories = Counter()
    rank_counts = Counter()
    for b in data["books"]:
        authors.add(b.get("author", ""))
        cat = b.get("category", "")
        if cat:
            categories[cat] += 1
        rt = b.get("rank_type", "")
        if rt:
            rank_counts[rt] += 1

    return json.dumps({
        "week": data["week"],
        "total_books": len(data["books"]),
        "unique_titles": len(set(b["title"] for b in data["books"])),
        "unique_authors": len(authors),
        "n_categories": len(categories),
        "top_categories": categories.most_common(10),
        "rank_type_distribution": {RANK_LABELS.get(k, k): v for k, v in rank_counts.most_common()},
    }, ensure_ascii=False)


def _tool_get_category_trend(category: str) -> str:
    weeks = _load_all_weeks(DATA_DIR)
    if len(weeks) < 2:
        return json.dumps({"error": "数据不足，至少需要 2 周"}, ensure_ascii=False)

    trend = []
    for w in weeks:
        cat_books = [b for b in w["books"] if b.get("category") == category]
        heat = 0.0
        for b in cat_books:
            wgt = RANK_WEIGHTS.get(b.get("rank_type", ""), 0.5)
            import math
            heat += wgt / math.sqrt(max(b.get("rank", 200), 1))
        trend.append({
            "week": w["week"],
            "book_count": len(cat_books),
            "heat": round(heat, 2),
        })

    return json.dumps({"category": category, "trend": trend, "n_weeks": len(trend)}, ensure_ascii=False)


def _tool_get_top_books(week: str = None, rank_type: str = "yuepiao", n: int = 10) -> str:
    data = _load_week(DATA_DIR, week)
    if not data:
        return json.dumps({"error": "周数据不可用"}, ensure_ascii=False)

    n = min(n, 20)
    matched = [b for b in data["books"] if b.get("rank_type") == rank_type]
    matched.sort(key=lambda b: b.get("rank", 200))

    books = []
    for b in matched[:n]:
        books.append({
            "rank": b["rank"],
            "title": b["title"],
            "author": b["author"],
            "category": b.get("category", ""),
            "status": b.get("status", ""),
        })

    return json.dumps({
        "week": data["week"],
        "rank_type": RANK_LABELS.get(rank_type, rank_type),
        "n": len(books),
        "books": books,
    }, ensure_ascii=False)


def _tool_get_keywords(week: str = None) -> str:
    kw = _load_analysis_file(DATA_DIR, "keywords.json")
    if not kw or not kw.get("top"):
        all_kw = _load_analysis_file(DATA_DIR, "keywords.json")
        return json.dumps(
            kw.get("top", [])[:20] if kw else {"message": "关键词数据暂不可用"},
            ensure_ascii=False
        )
    return json.dumps(kw.get("top", [])[:20], ensure_ascii=False)


def _tool_get_genre_distribution(week: str = None) -> str:
    gt = _load_analysis_file(DATA_DIR, "genre_tags.json")
    if not gt:
        return json.dumps({"message": "流派标签数据暂不可用"}, ensure_ascii=False)

    return json.dumps({
        "total_books": gt.get("total_books", 0),
        "books_with_tags": gt.get("books_with_tags", 0),
        "top_tags": gt.get("global", [])[:20],
        "top_cooccurrences": gt.get("cooccurrences", [])[:15],
    }, ensure_ascii=False)


def _tool_compare_weeks(week1: str, week2: str) -> str:
    w1 = _load_week(DATA_DIR, week1)
    w2 = _load_week(DATA_DIR, week2)
    if not w1 or not w2:
        return json.dumps({"error": "两周数据不完整"}, ensure_ascii=False)

    keys1 = set((b["title"], b["author"]) for b in w1["books"])
    keys2 = set((b["title"], b["author"]) for b in w2["books"])

    new_books = keys2 - keys1
    gone_books = keys1 - keys2
    common = keys1 & keys2

    # Category heat changes
    cat_heat1 = Counter()
    cat_heat2 = Counter()
    import math
    for b in w1["books"]:
        if b.get("category"):
            wgt = RANK_WEIGHTS.get(b.get("rank_type", ""), 0.5)
            cat_heat1[b["category"]] += wgt / math.sqrt(max(b.get("rank", 200), 1))
    for b in w2["books"]:
        if b.get("category"):
            wgt = RANK_WEIGHTS.get(b.get("rank_type", ""), 0.5)
            cat_heat2[b["category"]] += wgt / math.sqrt(max(b.get("rank", 200), 1))

    changes = []
    all_cats = set(list(cat_heat1.keys()) + list(cat_heat2.keys()))
    for cat in all_cats:
        d = round(cat_heat2.get(cat, 0) - cat_heat1.get(cat, 0), 2)
        if abs(d) > 0.1:
            changes.append({"category": cat, "heat_change": d, "prev": round(cat_heat1.get(cat, 0), 2), "cur": round(cat_heat2.get(cat, 0), 2)})
    changes.sort(key=lambda x: x["heat_change"], reverse=True)

    return json.dumps({
        "week1": w1["week"], "week2": w2["week"],
        "common_books": len(common),
        "new_books": len(new_books),
        "gone_books": len(gone_books),
        "churn_rate": round((len(new_books) + len(gone_books)) / max(len(keys1), 1) * 100, 1),
        "category_changes": changes[:15],
    }, ensure_ascii=False)


TOOL_EXECUTORS = {
    "get_weekly_stats": _tool_get_weekly_stats,
    "get_category_trend": _tool_get_category_trend,
    "get_top_books": _tool_get_top_books,
    "get_keywords": _tool_get_keywords,
    "get_genre_distribution": _tool_get_genre_distribution,
    "compare_weeks": _tool_compare_weeks,
}


def _run_react_loop(client, week_label: str) -> tuple[str, list[dict]]:
    """Run the ReAct loop. Returns (report_text, tool_call_log)."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"请分析本周（{week_label}）的起点中文网排行榜数据。先获取总览，然后探索品类趋势、关键词和流派分布，对比上一周的变化，最后给出完整的分析报告。"},
    ]

    tool_call_log = []

    for round_num in range(1, MAX_ROUNDS + 1):
        logger.info("Agent round %d/%d", round_num, MAX_ROUNDS)

        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOLS,
                temperature=0.7,
                max_tokens=4096,
            )
        except Exception as e:
            logger.error("API call failed at round %d: %s", round_num, e)
            break

        msg = response.choices[0].message

        # If no tool calls, agent is done thinking — extract report
        if not msg.tool_calls:
            content = msg.content or ""
            report_match = re.search(r"<REPORT>([\s\S]*?)</REPORT>", content)
            if report_match:
                report = report_match.group(1).strip()
                logger.info("Agent produced report (%d chars)", len(report))
                return report, tool_call_log
            # Check if there's substantial content even without markers
            if len(content) > 200:
                logger.info("Agent finished without explicit markers (%d chars)", len(content))
                return content, tool_call_log
            # Otherwise continue
            messages.append({"role": "assistant", "content": content})
            continue

        # Process tool calls
        assistant_msg = {"role": "assistant", "content": msg.content or "", "tool_calls": []}

        for tc in msg.tool_calls:
            func_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            logger.info("Tool call: %s(%s)", func_name, json.dumps(args, ensure_ascii=False))

            executor = TOOL_EXECUTORS.get(func_name)
            if executor:
                try:
                    result = executor(**args)
                except Exception as e:
                    result = json.dumps({"error": str(e)}, ensure_ascii=False)
            else:
                result = json.dumps({"error": f"Unknown tool: {func_name}"}, ensure_ascii=False)

            tool_call_log.append({
                "round": round_num,
                "tool": func_name,
                "args": args,
                "result_preview": result[:200],
            })

            assistant_msg["tool_calls"].append({
                "id": tc.id,
                "type": "function",
                "function": {"name": func_name, "arguments": tc.function.arguments},
            })

            messages.append(assistant_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        time.sleep(0.3)  # Rate limiting

    # Max rounds reached — force a final report generation
    logger.info("Max rounds reached, forcing final report generation")
    messages.append({
        "role": "user",
        "content": "你已收集了足够的数据。现在请按照要求的格式撰写完整的分析报告。用 <REPORT> 和 </REPORT> 包裹报告内容。"
    })

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=4096,
        )
        content = response.choices[0].message.content or ""
        report_match = re.search(r"<REPORT>([\s\S]*?)</REPORT>", content)
        if report_match:
            return report_match.group(1).strip(), tool_call_log
        return content, tool_call_log
    except Exception as e:
        logger.error("Final report generation failed: %s", e)
        return f"## 本周概览\n\nAgent 分析过程中出现错误：{e}\n\n请稍后重试。", tool_call_log


def _extract_faq_from_report(report: str) -> list[dict]:
    """Extract FAQ pairs from the report text."""
    faq = []
    # Match **Q: ...** A: ... pattern
    pattern = re.compile(r"\*\*Q:\s*(.+?)\*\*\s*\n\s*A:\s*(.+?)(?=\n\s*\*\*Q:|\n\s*##|\Z)", re.DOTALL)
    for match in pattern.finditer(report):
        q = match.group(1).strip()
        a = match.group(2).strip()
        # Simple keyword extraction for matching
        keywords = [w for w in re.findall(r"[一-鿿\w]+", q) if len(w) >= 2]
        faq.append({"q": q, "a": a, "keywords": keywords[:10]})

    # If no FAQ extracted from report, generate some generic ones from the report content
    if not faq:
        logger.info("No FAQ found in report, generating generic FAQs")
        # Extract sentences that look like insights
        insights = re.findall(r"[^。\n]*?(?:趋势|建议|热门|增长|下降|推荐|风向)[^。\n]*。[^。\n]*。", report)
        for i, insight in enumerate(insights[:15]):
            q = f"本周有什么值得关注的创作动向？" if i == 0 else f"关于网文创作，有什么具体建议？"
            if i > 0:
                q = f"你能详细说说第{i}点吗？"
            faq.append({"q": q, "a": insight.strip(), "keywords": ["创作", "方向", "建议"]})

    return faq


def _generate_faqs_from_data(data_dir: Path, week_label: str) -> list[dict]:
    """Generate structured FAQ pairs from data analysis results."""
    faq = []
    weeks = _load_all_weeks(data_dir)
    latest = weeks[-1] if weeks else None

    if not latest:
        return faq

    # FAQ 1: Overview
    n_books = len(set((b["title"], b["author"]) for b in latest["books"]))
    cats = Counter(b.get("category", "") for b in latest["books"])
    top_cats = [c for c, _ in cats.most_common(5)]
    faq.append({
        "q": "本周上榜书籍的整体情况如何？",
        "a": f"本周共有 {n_books} 本独立书籍上榜，覆盖 {len(cats)} 个品类。最热门的品类包括：{'、'.join(top_cats)}。整体市场活跃度较高，各品类竞争格局呈现差异化特征。",
        "keywords": ["本周", "整体", "情况", "上榜", "书籍", "品类"],
    })

    # FAQ 2: Hottest category
    if top_cats:
        faq.append({
            "q": f"本周最热门的品类是什么？",
            "a": f"从榜单覆盖度来看，{'、'.join(top_cats[:3])} 是本周最热门的品类。这些品类的头部作品在多个榜单上均有斩获，显示出较强的市场号召力和读者付费意愿。",
            "keywords": ["热门", "品类", top_cats[0] if top_cats else "玄幻"],
        })

    # FAQ 3-5: Genre tags
    genre_tags = _load_analysis_file(data_dir, "genre_tags.json")
    if genre_tags and genre_tags.get("global"):
        top3 = genre_tags["global"][:3]
        faq.append({
            "q": "当前网文创作最流行哪些流派和元素？",
            "a": "根据对书籍简介的文本分析，目前最流行的流派标签Top 3是：" + "、".join(t["tag"] + "(" + str(t["count"]) + "次)" for t in top3) + "。这说明读者对这些题材有持续的高需求，创作者可以考虑在这些方向上深耕或寻找差异化切入点。",
            "keywords": ["流行", "流派", "元素", "标签", "创作"],
        })

    # FAQ 4: Keywords
    keywords = _load_analysis_file(data_dir, "keywords.json")
    if keywords and keywords.get("top"):
        top_kw = keywords["top"][:5]
        kw_str = "、".join(f'{k["token"]}' for k in top_kw)
        faq.append({
            "q": "从关键词来看，本周网文创作的热点是什么？",
            "a": f"TF-IDF 关键词分析显示，本周高频关键词包括：{kw_str}。这些词汇反映了当前读者的阅读兴趣和创作热点，建议在创作中自然地融入这些热点元素，而非生硬堆砌。",
            "keywords": ["关键词", "热点", "TF-IDF", "创作"],
        })

    # FAQ 5-6: Trend questions
    if len(weeks) >= 2:
        prev = weeks[-2]
        common = set((b["title"], b["author"]) for b in latest["books"]) & set((b["title"], b["author"]) for b in prev["books"])
        retention = round(len(common) / max(len(set((b["title"], b["author"]) for b in prev["books"])), 1) * 100, 1)
        faq.append({
            "q": "与上周相比，本周榜单有哪些变化？",
            "a": f"本周书籍留存率约为 {retention}%。部分新面孔进入榜单说明市场对所有创作者仍有开放性，但头部作品的优势地位相对稳固。创作者应关注榜单变化中反映的读者口味迁移。",
            "keywords": ["对比", "变化", "上周", "留存", "榜单"],
        })

        faq.append({
            "q": "对于新人作者，应该选择什么品类入局？",
            "a": f"建议关注签约新书榜中表现较好的品类，以及竞争集中度相对较低的品类。当前热门品类如{'、'.join(top_cats[:2]) if top_cats else '玄幻'}虽然读者基数大但竞争激烈，可考虑选择增长中的细分品类作为切入点。",
            "keywords": ["新人", "作者", "入局", "选择", "品类", "签约"],
        })

    # FAQ 7-10: More specific insights
    faq.append({
        "q": "网文创作中如何选择金手指设定？",
        "a": "根据书籍简介分析，'系统流'和'重生/穿越'是最常见的金手指设定。创作者可以考虑在经典金手指基础上加入创新元素，或结合两种以上的设定来创造新鲜感。关键在于金手指要与主线剧情深度融合，而非仅仅作为开篇噱头。",
        "keywords": ["金手指", "设定", "系统", "重生", "穿越"],
    })

    faq.append({
        "q": "如何在热门品类中做出差异化？",
        "a": "在热门品类中脱颖而出的关键策略包括：① 找到品类内被忽略的子类型或交叉领域；② 在人物设定上做创新（如非常规主角身份）；③ 在叙事节奏上做差异化（快节奏打脸vs慢热布局）；④ 融合跨品类元素创造新鲜感。",
        "keywords": ["差异化", "热门", "品类", "创新", "策略"],
    })

    faq.append({
        "q": "当前网文市场的读者偏好有什么特征？",
        "a": "从数据来看，读者偏好呈现两极分化趋势：一边是'快节奏、强爽感'的作品持续走强；另一边是'世界观扎实、人物立体'的作品具备长尾生命力。创作者应根据自身优势选择合适的定位，而非盲目追热点。",
        "keywords": ["读者", "偏好", "市场", "特征", "趋势"],
    })

    faq.append({
        "q": "签约新书榜对创作者有什么指导意义？",
        "a": "签约新书榜反映了平台近期的签约偏好和扶持方向。该榜上榜书籍的主题和品类分布，代表了平台编辑对市场趋势的判断。创作者在开新书前，可以研究签约新书榜的品类构成，以此作为确定选题方向的参考依据之一。",
        "keywords": ["签约", "新书", "平台", "扶持", "选题"],
    })

    return faq


def run_agent_analysis(data_dir: Path = None, week_label: str = None) -> dict:
    """Run ReAct Agent analysis and generate report + FAQ."""
    if data_dir is None:
        data_dir = DATA_DIR

    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        error_data = {"error": "API key not configured", "updated_at": datetime.now().isoformat()}
        with open(analysis_dir / "agent_insights.json", "w", encoding="utf-8") as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)
        with open(analysis_dir / "agent_report.md", "w", encoding="utf-8") as f:
            f.write("## AI Agent 分析暂不可用\n\nDeepSeek API Key 未配置，请设置 `OPENAI_API_KEY` 环境变量后重新运行。\n")
        logger.warning("OPENAI_API_KEY not set, skipping agent analysis")
        return error_data

    # Determine week label
    if not week_label:
        latest = _load_week(data_dir)
        if latest:
            week_label = latest["week"]
        else:
            week_label = "未知周"

    logger.info("=== Agent Analysis for %s ===", week_label)

    try:
        client = _get_client()
        report, tool_log = _run_react_loop(client, week_label)
    except Exception as e:
        logger.error("Agent analysis failed: %s", e)
        error_data = {"error": str(e), "updated_at": datetime.now().isoformat()}
        with open(analysis_dir / "agent_insights.json", "w", encoding="utf-8") as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)
        with open(analysis_dir / "agent_report.md", "w", encoding="utf-8") as f:
            f.write(f"## AI Agent 分析失败\n\n错误信息：{e}\n\n请稍后重试。\n")
        return error_data

    # Extract FAQ from report or generate from data
    faq_from_report = _extract_faq_from_report(report)
    faq_from_data = _generate_faqs_from_data(data_dir, week_label)

    # Merge FAQs: prefer report-extracted ones, fill with data-generated ones
    faq = faq_from_report
    existing_qs = {f["q"] for f in faq}
    for f in faq_from_data:
        if f["q"] not in existing_qs and len(faq) < 40:
            faq.append(f)
            existing_qs.add(f["q"])

    # Save agent report
    with open(analysis_dir / "agent_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    logger.info("Saved agent_report.md (%d chars)", len(report))

    # Save agent insights
    insights = {
        "updated_at": datetime.now().isoformat(),
        "model": DEEPSEEK_MODEL,
        "week": week_label,
        "report": report,
        "tool_calls_log": tool_log,
        "n_tool_calls": len(tool_log),
        "faq": faq,
    }
    with open(analysis_dir / "agent_insights.json", "w", encoding="utf-8") as f:
        json.dump(insights, f, ensure_ascii=False, indent=2)
    logger.info("Saved agent_insights.json (%d FAQ items)", len(faq))

    return {"n_tool_calls": len(tool_log), "n_faq": len(faq), "report_length": len(report)}
