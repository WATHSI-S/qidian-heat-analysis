#!/usr/bin/env python3
"""Generate sample data for frontend testing."""

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Realistic Qidian-style data pools
TITLES = [
    "大奉打更人", "灵境行者", "夜的命名术", "深空彼岸", "光阴之外",
    "剑来", "诡秘之主", "牧神记", "大王饶命", "全球高武",
    "星门", "万族之劫", "超神机械师", "全职高手", "斗罗大陆",
    "完美世界", "遮天", "凡人修仙传", "仙逆", "求魔",
    "我欲封天", "一念永恒", "三寸人间", "修真聊天群", "星辰变",
    "盘龙", "神墓", "长生界", "圣墟", "帝霸",
    "太初", "九星霸体诀", "万古神帝", "修罗武神", "绝世武神",
    "最强弃少", "特种兵王", "最强神医", "都市极品仙帝", "重生都市修仙",
    "轮回乐园", "惊悚乐园", "网游之天谴修罗", "刀剑神皇", "剑道独尊",
    "儒道至圣", "唐砖", "赘婿", "一世之尊", "武道宗师",
    "诡秘地海", "明克街13号", "长夜余火", "黎明之剑", "异常生物见闻录",
] * 3  # pad to ~150 unique entries

AUTHORS = [
    "卖报小郎君", "会说话的肘子", "老鹰吃小鸡", "辰东", "耳根",
    "烽火戏诸侯", "爱潜水的乌贼", "宅猪", "唐家三少", "天蚕土豆",
    "猫腻", "月关", "我吃西红柿", "血红", "萧鼎",
    "江南", "烟雨江南", "骷髅精灵", "苍天白鹤", "跃千愁",
    "七十二编", "愤怒的香蕉", "横扫天涯", "净无痕", "方想",
    "卧牛真人", "古羲", "青衫取醉", "黑山老鬼", "雾外江山",
    "八宝饭", "石三", "逆苍天", "忘语", "滚开",
    "荆轲守", "误道者", "文抄公", "齐佩甲", "远瞳",
]

CATEGORIES = ["玄幻", "仙侠", "都市", "历史", "科幻", "游戏", "悬疑", "轻小说"]
STATUSES = ["连载", "完结"]

RANK_TYPES = ["yuepiao", "hotsales", "readindex", "recom", "collect", "newfans", "vipup", "signnewbook"]


def generate_week(week_label: str, books_per_rank: int = 160) -> dict:
    """Generate one week of sample data with some continuity."""
    books = []
    for rt in RANK_TYPES:
        # Shuffle so each ranking type has a different ordering
        pool = list(range(len(TITLES)))
        random.shuffle(pool)
        for rank, idx in enumerate(pool[:books_per_rank], 1):
            books.append({
                "rank": rank,
                "title": TITLES[idx] + (f"·续" if random.random() < 0.05 else ""),
                "author": random.choice(AUTHORS),
                "category": random.choice(CATEGORIES),
                "status": random.choice(STATUSES),
                "intro": f"这是一部关于{TITLES[idx][:2]}的精彩小说...",
                "url": f"https://www.qidian.com/book/{1000000 + idx}/",
                "rank_type": rt,
            })
    # Add some week-to-week ranking perturbation
    random.shuffle(books)
    return {
        "week": week_label,
        "scraped_at": f"{week_label}T08:00:00",
        "total": len(books),
        "books": books,
    }


def main():
    weeks = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    today = date.today()

    for i in range(weeks):
        dt = today - timedelta(weeks=weeks - 1 - i)
        iso = dt.isocalendar()
        label = f"{iso[0]}-W{iso[1]:02d}"
        data = generate_week(label)
        fpath = DATA_DIR / f"{label}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Generated {fpath} ({data['total']} books)")

    # Build index
    weeks_list = []
    all_titles = set()
    all_authors = set()
    cats = {}
    for fp in sorted(DATA_DIR.glob("20*.json")):
        with open(fp, "r", encoding="utf-8") as f:
            snap = json.load(f)
        weeks_list.append({
            "week": snap["week"],
            "scraped_at": snap["scraped_at"],
            "total": snap["total"],
            "file": fp.name,
        })
        for b in snap.get("books", []):
            all_titles.add(b.get("title", ""))
            all_authors.add(b.get("author", ""))
            c = b.get("category", "未知")
            cats[c] = cats.get(c, 0) + 1

    index = {
        "updated_at": date.today().isoformat(),
        "weeks": weeks_list,
        "total_weeks": len(weeks_list),
        "unique_titles": len(all_titles),
        "unique_authors": len(all_authors),
        "categories": cats,
    }
    idx_path = DATA_DIR / "index.json"
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"Index written: {idx_path} ({len(weeks_list)} weeks)")


if __name__ == "__main__":
    main()
