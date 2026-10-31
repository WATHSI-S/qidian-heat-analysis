"""
ReAct Agent module: autonomous data analysis agent with tool calling,
FAQ generation, and structured report output.
"""

import json
import logging
import os
import re
import time
from collections import Counter
from contextvars import ContextVar

from domain import DATA_DIR, RANK_LABELS, book_key, comparable, load_week, load_weeks
from analysis.ai_client import AIClient, MODEL
from analysis.metrics import category_totals, compare_categories
from analysis.results import read_result, record_failure, write_result

logger = logging.getLogger(__name__)

MAX_ROUNDS = 8
_CONTEXT = ContextVar("agent_context", default=(DATA_DIR, None))

SYSTEM_PROMPT = """你是"天机"，起点中文网的数据分析 Agent。你的任务是自主探索指定周及更早的排行榜数据，撰写创作观察报告。缺榜与缺失值必须标为未知，不得当作零。只依据工具返回的数据，区分观察、推测与通用建议，不推断平台偏好或写作成功率。

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
                        "enum": list(RANK_LABELS)
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

def _get_client():
    return AIClient(max_calls=MAX_ROUNDS + 1)


def _load_week(data_dir, week_label=None):
    bound_dir, target = _CONTEXT.get()
    requested = week_label or target
    if target and requested > target:
        raise ValueError("Agent cannot read weeks after the target week")
    return load_week(bound_dir, requested)


def _load_all_weeks(data_dir):
    bound_dir, target = _CONTEXT.get()
    return load_weeks(bound_dir, target)


def _load_analysis_file(data_dir, filename, week=None):
    bound_dir, target = _CONTEXT.get()
    requested = week or target or load_week(bound_dir)["week"]
    if target and requested > target:
        raise ValueError("Agent cannot read future analysis")
    return read_result(bound_dir, requested, filename)


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
        "total_entries": len(data["books"]),
        "total_books": len({book_key(b) for b in data["books"]}),
        "quality": data["quality"],
        "unique_titles": len(set(b["title"] for b in data["books"])),
        "unique_authors": len(authors),
        "n_categories": len(categories),
        "top_categories": categories.most_common(10),
        "rank_type_distribution": {RANK_LABELS.get(k, k): v for k, v in rank_counts.most_common()},
    }, ensure_ascii=False)


def _tool_get_category_trend(category):
    weeks = _load_all_weeks(DATA_DIR)
    complete = [w for w in weeks if w["quality"]["status"] == "complete"]
    depths = {rt: min(w["quality"]["rankings"][rt]["depth"] for w in complete) for rt in RANK_LABELS} if complete else {}
    trend = []
    for w in weeks:
        totals = category_totals([b for b in w["books"] if b["rank_type"] in depths and b["rank"] <= depths[b["rank_type"]]]) if w in complete else None
        trend.append({"week": w["week"], "heat": totals.get(category, {}).get("heat", 0) if totals is not None else None,
                      "status": w["quality"]["status"]})
    return json.dumps({"category": category, "trend": trend, "comparison_depths": depths}, ensure_ascii=False)


def _tool_get_top_books(week: str = None, rank_type: str = "yuepiao", n: int = 10) -> str:
    data = _load_week(DATA_DIR, week)
    if not data:
        return json.dumps({"error": "周数据不可用"}, ensure_ascii=False)

    n = max(1, min(n, 20))
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


def _tool_get_keywords(week=None):
    kw = _load_analysis_file(DATA_DIR, "keywords.json", week)
    return json.dumps({"week": kw.get("week"), "top": kw.get("top", [])[:20], "status": kw.get("status", "unavailable")}, ensure_ascii=False)


def _tool_get_genre_distribution(week: str = None) -> str:
    gt = _load_analysis_file(DATA_DIR, "genre_tags.json", week)
    if not gt:
        return json.dumps({"message": "流派标签数据暂不可用"}, ensure_ascii=False)

    return json.dumps({
        "total_books": gt.get("total_books", 0),
        "books_with_tags": gt.get("books_with_tags", 0),
        "top_tags": gt.get("global", [])[:20],
        "top_cooccurrences": gt.get("cooccurrences", [])[:15],
    }, ensure_ascii=False)


def _tool_compare_weeks(week1, week2):
    previous, current = _load_week(DATA_DIR, week1), _load_week(DATA_DIR, week2)
    old, new, depths = comparable(previous, current)
    a, b = {book_key(x) for x in old}, {book_key(x) for x in new}
    changes, _, _, _ = compare_categories(current, previous)
    return json.dumps({"week1": week1, "week2": week2, "comparison_depths": depths,
                       "common_books": len(a & b), "new_books": len(b - a), "gone_books": len(a - b),
                       "churn_rate": round((1 - len(a & b) / len(a | b)) * 100, 1) if a | b else None,
                       "category_changes": changes}, ensure_ascii=False)


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
            response = client.complete(
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

        # Process tool calls: collect results first, then push one assistant_msg + N tool messages
        tool_results = []

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

            tool_results.append({
                "id": tc.id,
                "function": {"name": func_name, "arguments": tc.function.arguments},
                "result": result,
            })

        # Push one assistant message with all tool_calls
        assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{
                "id": tr["id"],
                "type": "function",
                "function": tr["function"],
            } for tr in tool_results],
        }
        messages.append(assistant_msg)

        # Push one tool message per result
        for tr in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tr["id"],
                "content": tr["result"],
            })

        time.sleep(0.3)  # Rate limiting

    # Max rounds reached — force a final report generation
    logger.info("Max rounds reached, forcing final report generation")
    messages.append({
        "role": "user",
        "content": "你已收集了足够的数据。现在请按照要求的格式撰写完整的分析报告。用 <REPORT> 和 </REPORT> 包裹报告内容。"
    })

    try:
        response = client.complete(
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
        raise RuntimeError("Agent report generation failed") from e


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


def run_agent_analysis(data_dir=None, week_label=None):
    data_dir = data_dir or DATA_DIR
    week = load_week(data_dir, week_label)["week"]
    token = _CONTEXT.set((data_dir, week))
    try:
        client = _get_client()
        report, tool_log = _run_react_loop(client, week)
        if not report.strip():
            raise ValueError("Empty agent report")
        return write_result(data_dir, week, "agent_insights.json", {
            "model": MODEL, "report": report, "tool_calls_log": tool_log,
            "n_tool_calls": len(tool_log), "faq": _extract_faq_from_report(report),
            "mode": "manual_exploration"}, [w["week"] for w in load_weeks(data_dir, week)])
    except Exception as error:
        logger.exception("Optional agent exploration failed")
        return record_failure(data_dir, week, "agent_insights.json", type(error).__name__,
                              "unavailable" if not os.environ.get("OPENAI_API_KEY") else "error")
    finally:
        _CONTEXT.reset(token)
