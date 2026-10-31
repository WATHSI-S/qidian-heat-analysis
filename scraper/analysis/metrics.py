"""Deterministic metrics consumed by pages, reports and agent tools."""
import json
import math
from collections import Counter, defaultdict

from domain import DATA_DIR, RANK_LABELS, RANK_WEIGHTS, adjacent_weeks, book_key, comparable, deduplicate, load_week, load_weeks
from analysis.results import write_result


def key_string(book):
    return json.dumps(book_key(book), ensure_ascii=False, separators=(",", ":"))


def rank_quality(rank, depth):
    if depth <= 1:
        return 1. if depth == rank == 1 else 0.
    return max(0., min(1., (depth - rank) / (depth - 1)))


def heat_scores(books):
    scored = {}
    for b in books:
        key = book_key(b)
        if key not in scored:
            scored[key] = {**b, "score": 0., "ranks": [], "bestRank": b["rank"], "bestRankType": b["rank_type"]}
        item = scored[key]
        weight = RANK_WEIGHTS[b["rank_type"]]
        item["score"] += weight / math.sqrt(b["rank"])
        item["ranks"].append({"type": b["rank_type"], "rank": b["rank"], "weight": weight})
        if b["rank"] < item["bestRank"]:
            item["bestRank"], item["bestRankType"] = b["rank"], b["rank_type"]
    for b in scored.values():
        b.update(score=round(b["score"], 6), listCount=len(b["ranks"]),
                 bestRankLabel=f'{b["bestRank"]} {RANK_LABELS[b["bestRankType"]]}')
    return sorted(scored.values(), key=lambda b: (-b["score"], b["title"], b["author"]))


def category_totals(books):
    result = defaultdict(lambda: {"heat": 0., "count": 0})
    for b in heat_scores(books):
        cat = result[b.get("category") or "未知"]
        cat["heat"] += b["score"]
        cat["count"] += 1
    return dict(result)


def compare_categories(current, previous):
    if not previous:
        return [], {}, {}, []
    old, new, depths = comparable(previous, current)
    if not depths:
        return [], {}, {}, []
    before, after = category_totals(old), category_totals(new)
    changes = []
    for cat in sorted(before.keys() | after.keys()):
        a, b = before.get(cat, {"heat": 0., "count": 0}), after.get(cat, {"heat": 0., "count": 0})
        hd = (b["heat"] / a["heat"] - 1) * 100 if a["heat"] else None
        cd = (b["count"] / a["count"] - 1) * 100 if a["count"] else None
        cmi = round(100 * (.6 * math.tanh(hd / 30) + .4 * math.tanh(cd / 20))) if hd is not None and cd is not None else None
        changes.append({"category": cat, "curTotalHeat": round(b["heat"], 2), "prevTotalHeat": round(a["heat"], 2),
                        "curCount": b["count"], "prevCount": a["count"], "heatDelta": round(hd, 1) if hd is not None else None,
                        "countDelta": round(cd, 1) if cd is not None else None, "cmiNorm": cmi})
    old_scored = {book_key(b): (i + 1, b) for i, b in enumerate(heat_scores(old))}
    momentum = {}
    for i, b in enumerate(heat_scores(new)):
        prior = old_scored.get(book_key(b))
        momentum[key_string(b)] = {"prevHeatRank": prior[0], "curHeatRank": i + 1,
                                   "heatDelta": prior[0] - i - 1} if prior else {"isNew": True}
    rank_changes = []
    lookup = {(*book_key(b), b["rank_type"]): b["rank"] for b in old}
    for b in new:
        prior = lookup.get((*book_key(b), b["rank_type"]))
        delta = prior - b["rank"] if prior is not None else None
        rank_changes.append({**b, "prevRank": prior, "delta": delta, "changeClass":
                             "new" if delta is None else "up" if delta > 0 else "down" if delta < 0 else "none"})
    changes.sort(key=lambda c: c["cmiNorm"] if c["cmiNorm"] is not None else -101, reverse=True)
    return changes, momentum, depths, rank_changes


def opportunity_metrics(snapshot, cat_momentum):
    coverage = snapshot["quality"]["rankings"]
    # Incomplete rankings are unknown, rather than a zero-demand observation.
    required = ("signnewbook", "yuepiao", "hotsales")
    if any(coverage[rt]["status"] != "complete" for rt in required):
        return [], []
    eligible = [b for b in snapshot["books"] if coverage[b["rank_type"]]["status"] == "complete"]
    grouped = defaultdict(list)
    for b in heat_scores(eligible):
        grouped[b.get("category") or "未知"].append(b)
    momentum = {c["category"]: c for c in cat_momentum}
    entries, gaps = [], []
    for cat, books in grouped.items():
        heat = sum(b["score"] for b in books)
        cr3 = sum(b["score"] for b in books[:3]) / heat if heat else 0.
        new_count = sum(any(r["type"] == "signnewbook" for r in b["ranks"]) for b in books)
        density = new_count / len(books)
        access = sum(max(rank_quality(r["rank"], coverage[r["type"]]["depth"]) for r in b["ranks"]) for b in books) / len(books)
        entry_score = round(100 * (.45 * density + .30 * (1 - cr3) + .25 * access))
        entry = {"category": cat, "signnewCount": new_count, "signnewDensity": round(density * 100),
                 "concentration": round(cr3 * 100), "competitionSpread": round((1 - cr3) * 100),
                 "avgRank": round(sum(b["bestRank"] for b in books) / len(books)),
                 "accessibility": round(access * 100), "entryScore": entry_score, "sampleSize": len(books)}
        entries.append(entry)
        demand = [rank_quality(r["rank"], coverage[r["type"]]["depth"]) for b in books for r in b["ranks"] if r["type"] in ("yuepiao", "hotsales")]
        cmi = momentum.get(cat, {}).get("cmiNorm")
        if not demand or cmi is None:
            continue
        demand_score = sum(demand) / len(demand)
        growth = (cmi + 100) / 200
        gaps.append({**entry, "entryFriendliness": entry_score, "demandScore": round(demand_score * 100),
                     "growthSignal": round(growth * 100), "mgs": round(100 * (.35 * demand_score + .25 * (1 - cr3) + .25 * entry_score / 100 + .15 * growth)),
                     "totalHeat": round(heat, 2), "bookCount": len(books), "topBooks": books[:5]})
    return sorted(entries, key=lambda e: -e["entryScore"]), sorted(gaps, key=lambda e: -e["mgs"])


def build_summary(data_dir=DATA_DIR, week=None):
    current = load_week(data_dir, week)
    history = load_weeks(data_dir, current["week"])
    previous = history[-2] if len(history) > 1 else None
    if previous and not adjacent_weeks(previous["week"], current["week"]):
        previous = None
    scored = heat_scores(current["books"])
    cats = defaultdict(list)
    for b in scored:
        cats[b.get("category") or "未知"].append(b)
    cat_rankings = sorted([{"name": cat, "total": len(items), "totalHeat": round(sum(b["score"] for b in items), 2), "top5": items[:5]} for cat, items in cats.items()], key=lambda c: -c["totalHeat"])
    appearances, authors = {}, Counter()
    for snap in history:
        for b in deduplicate(snap["books"]):
            key = book_key(b)
            appearances.setdefault(key, {"title": b["title"], "author": b["author"], "category": b.get("category"), "weeks": 0})["weeks"] += 1
        authors.update(b["author"] for b in snap["books"])
    cat_momentum, momentum, depths, rank_changes = compare_categories(current, previous)
    entries, gaps = opportunity_metrics(current, cat_momentum)
    result = {"heatScores": scored, "catRankings": cat_rankings, "momentum": momentum,
              "appearances": sorted(appearances.values(), key=lambda b: -b["weeks"]),
              "authors": [{"author": a, "count": n} for a, n in authors.most_common(20)],
              "catMomentum": cat_momentum, "entryScores": entries, "marketGaps": gaps,
              "rankChanges": rank_changes, "comparison": {"previous_week": previous["week"] if previous else None, "depths": depths},
              "quality": current["quality"], "n_books": len(scored)}
    return write_result(data_dir, current["week"], "summary.json", result, [w["week"] for w in history])
