"""
Text mining module: jieba segmentation, TF-IDF analysis, genre tag extraction.
"""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"

# ── Web novel domain dictionary ──

WEB_NOVEL_TERMS = [
    # 流派/题材
    "穿越", "重生", "系统流", "无限流", "洪荒流", "凡人流", "苟道流",
    "种田", "修真", "修仙", "修魔", "末世", "废土", "星际", "机甲",
    "诸天", "轮回", "快穿", "穿书", "系统", "签到", "抽奖", "模拟器",
    # 金手指/能力
    "金手指", "系统商城", "血脉", "传承", "奇遇", "老爷爷",
    # 主角人设
    "扮猪吃虎", "废柴", "逆袭", "打脸", "爽文", "杀伐果断",
    "苟道", "稳健", "腹黑", "无敌流", "天才流",
    # 世界观元素
    "炼丹", "炼器", "阵法", "符箓", "法宝", "功法", "灵石",
    "宗门", "家族", "散修", "魔道", "仙门", "秘境",
    "气运", "天劫", "元婴", "金丹", "筑基", "渡劫", "飞升",
    "长生", "不朽", "仙界", "凡间", "灵根",
    # 现代/都市
    "校花", "兵王", "神医", "鉴宝", "商战", "娱乐圈",
    "直播", "电竞", "灵气复苏", "异能",
    # 历史
    "宫斗", "权谋", "争霸", "科举", "朝堂", "藩王",
    # 游戏
    "全息", "虚拟现实", "网游", "副本", "boss", "主神空间",
]

# ── Chinese stop words ──

STOP_WORDS = set([
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "所", "为", "所以", "因为", "但是", "然而", "虽然", "可以", "这个",
    "那个", "什么", "怎么", "如何", "哪里", "还是", "只是", "而且",
    "如果", "的话", "吧", "吗", "呢", "啊", "哦", "嗯", "哈", "呀", "啦",
    "便", "则", "与", "之", "其", "或", "但", "而", "且", "被", "把",
    "让", "从", "对", "向", "往", "朝", "当", "以", "可", "能", "会",
    "着", "过", "得", "地", "的", "中", "里", "外", "后", "前", "时",
    "更", "最", "很", "太", "极", "较", "才", "又", "再", "还", "只",
    "没", "不", "非", "无", "未", "别", "勿", "莫", "休", "各", "每",
    "某", "本", "该", "此", "这", "那", "哪", "谁", "何", "怎", "啥",
    "大", "小", "多", "少", "高", "低", "长", "短", "新", "旧", "老",
    "男", "女", "子", "儿", "头", "手", "心", "意", "事", "物", "道",
    "世界", "故事", "小说", "本书", "作品", "读者", "作者", "主角",
    "少年", "青年", "少年", "少女", "人们", "他们", "她们", "它们",
    "开始", "成为", "发现", "来到", "到了", "看着", "说道", "觉得",
    "就是", "获得", "什么", "怎么", "没有", "可以", "只是", "知道",
    "已经", "一切", "一天", "一个", "一种", "一位", "一样", "一般",
    "一直", "一起", "一定", "一下", "一点", "一番", "一场", "一阵",
    "莫名", "带着", "发生", "整个", "两个", "这次", "那个",
    "这个", "这些", "那些", "各种", "其中", "之间", "之后", "之前",
    "不过", "不可", "不仅", "不觉", "不再", "不知", "不止", "不同",
    "从未", "从前", "从来", "从而", "存在", "当中", "当然", "当时",
    "的话", "的话", "而是", "而且", "而言", "而已", "否则", "还是",
    "还有", "或者", "几乎", "即将", "既然", "尽管", "进而", "居然",
    "据说", "看来", "可能", "可是", "可以", "来自", "另外", "没有",
    "每个", "每天", "那些", "那样", "能否", "你们", "其中", "起来",
    "确实", "然后", "然而", "然后", "如今", "如同", "甚至", "是否",
    "首先", "所以", "所有", "所谓", "同样", "为此", "为了", "为什么",
    "无论", "许多", "也是", "也许", "一般", "一边", "一点", "一方面",
    "一起", "一切", "一下", "一样", "一直", "已经", "以后", "以前",
    "以上", "以下", "以及", "以来", "以内", "以外", "以为", "以往",
    "因而", "因为", "应该", "拥有", "由于", "于是", "原来", "原因",
    "再则", "在此", "怎么", "怎么", "怎样", "之后", "之前", "之中",
    "只是", "只要", "只有", "至今", "至于", "逐渐", "准备", "最后",
    "终于", "重要", "主要", "自身", "总共", "总之", "最好", "最后",
    "作出", "做出", "作为", "作用", "作者",
])

# ── Genre tag patterns ──

GENRE_PATTERNS = {
    "穿越": re.compile(r"穿越"),
    "重生": re.compile(r"重生"),
    "系统": re.compile(r"系统(?!文|小说|流)"),  # 系统 but not 系统文/系统小说/系统流
    "系统流": re.compile(r"系统[文流]"),
    "修炼": re.compile(r"修炼|修真|修仙|修魔|修道"),
    "末世": re.compile(r"末世|末日"),
    "废土": re.compile(r"废土"),
    "星际": re.compile(r"星际|太空|宇宙"),
    "机甲": re.compile(r"机甲"),
    "种田": re.compile(r"种田|种菜|种地|农耕"),
    "游戏": re.compile(r"游戏|网游|电竞|全息游戏"),
    "无限流": re.compile(r"无限流|主神|轮回者"),
    "快穿": re.compile(r"快穿|穿书"),
    "洪荒": re.compile(r"洪荒|封神|西游|山海经"),
    "凡人流": re.compile(r"凡人流|凡人修仙"),
    "苟道": re.compile(r"苟道|稳健|苟"),
    "灵气复苏": re.compile(r"灵气复苏|灵气"),
    "宫斗": re.compile(r"宫斗|后宫|宫廷"),
    "权谋": re.compile(r"权谋|谋略|争霸|朝堂"),
    "悬疑": re.compile(r"悬疑|推理|侦探|破案"),
    "灵异": re.compile(r"灵异|恐怖|惊悚|鬼|诡异"),
    "扮猪吃虎": re.compile(r"扮猪吃虎|扮猪吃老虎|低调|隐藏实力"),
    "打脸": re.compile(r"打脸|逆袭|复仇"),
    "无敌流": re.compile(r"无敌|碾压|横扫|秒杀"),
    "家族": re.compile(r"家族|宗门|氏族|部落"),
    "学院": re.compile(r"学院|学校|校园|大学"),
    "神医": re.compile(r"神医|医术|中医|妙手"),
    "鉴宝": re.compile(r"鉴宝|古董|捡漏|文物"),
    "兵王": re.compile(r"兵王|特种兵|退伍|雇佣兵"),
    "直播": re.compile(r"直播|网红|短视频"),
    "盗墓": re.compile(r"盗墓|古墓|探险|考古"),
}


def load_custom_dict() -> None:
    """Load web-novel domain terms into jieba."""
    for term in WEB_NOVEL_TERMS:
        jieba.add_word(term)
    logger.info("Loaded %d web-novel terms into jieba dictionary", len(WEB_NOVEL_TERMS))


def segment_intros(books: list[dict]) -> list[list[str]]:
    """Tokenize each book's intro with jieba, filtering stop words and short tokens."""
    tokens_list = []
    for book in books:
        intro = book.get("intro", "")
        if not intro:
            tokens_list.append([])
            continue
        tokens = []
        for token in jieba.cut(intro):
            token = token.strip()
            if len(token) >= 2 and token not in STOP_WORDS and not token.isdigit():
                tokens.append(token)
        tokens_list.append(tokens)
    return tokens_list


def compute_tfidf_global(books: list[dict], tokenized: list[list[str]], top_n: int = 100) -> dict:
    """Compute TF-IDF across all book intros. Returns top_n keywords with scores and frequencies."""
    # Build corpus: space-joined tokens per book
    corpus = [" ".join(tokens) for tokens in tokenized]
    non_empty = sum(1 for t in corpus if t)

    vectorizer = TfidfVectorizer(max_features=2000, token_pattern=r"(?u)\b\w+\b")
    try:
        tfidf_matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        logger.warning("TF-IDF: corpus too sparse or empty")
        return {"tokens": [], "scores": [], "n_books": len(books), "error": "corpus too sparse"}

    feature_names = vectorizer.get_feature_names_out()
    # Average TF-IDF score per token
    scores = tfidf_matrix.mean(axis=0).tolist()[0]

    # Token frequencies
    freq = Counter()
    for tokens in tokenized:
        freq.update(tokens)

    # Build scored list
    token_scores = [(name, scores[i], freq.get(name, 0)) for i, name in enumerate(feature_names)]
    token_scores.sort(key=lambda x: x[1], reverse=True)

    top = [
        {"token": t, "tfidf": round(s, 6), "frequency": f}
        for t, s, f in token_scores[:top_n]
    ]

    return {
        "n_books": len(books),
        "non_empty": non_empty,
        "tokens": [t for t, s, f in token_scores],
        "scores": [s for t, s, f in token_scores],
        "top": top,
    }


def compute_tfidf_per_category(
    books: list[dict], tokenized: list[list[str]], min_books: int = 10, top_n: int = 30
) -> dict:
    """Compute TF-IDF per category, using ALL intros as the background corpus."""
    categories: dict[str, list[str]] = defaultdict(list)

    for book, tokens in zip(books, tokenized):
        cat = book.get("category", "未知")
        if tokens:
            categories[cat].append(" ".join(tokens))

    result = {}
    all_corpus = [" ".join(t) if t else "" for t in tokenized]

    for cat, docs in sorted(categories.items()):
        if len(docs) < min_books:
            continue
        try:
            vectorizer = TfidfVectorizer(max_features=1000, token_pattern=r"(?u)\b\w+\b")
            vectorizer.fit(all_corpus)
            tfidf_matrix = vectorizer.transform(docs)
        except ValueError:
            continue

        scores = tfidf_matrix.mean(axis=0).tolist()[0]
        feature_names = vectorizer.get_feature_names_out()
        token_scores = [(feature_names[i], scores[i]) for i in range(len(feature_names))]
        token_scores.sort(key=lambda x: x[1], reverse=True)

        result[cat] = {
            "n_books": len(docs),
            "tokens": [t for t, s in token_scores],
            "scores": [s for t, s in token_scores],
            "top": [{"token": t, "tfidf": round(s, 6)} for t, s in token_scores[:top_n]],
        }

    return result


def extract_genre_tags(books: list[dict]) -> dict:
    """Extract genre tags from intros using regex patterns. Returns per-tag frequency and co-occurrence."""
    tag_counter: Counter[str] = Counter()
    cat_tag_counter: dict[str, Counter[str]] = defaultdict(Counter)
    cooccur: Counter[tuple[str, str]] = Counter()
    books_with_tags = 0

    for book in books:
        intro = book.get("intro", "")
        cat = book.get("category", "未知")
        matched = []
        for tag, pattern in GENRE_PATTERNS.items():
            if pattern.search(intro):
                matched.append(tag)
                tag_counter[tag] += 1
                cat_tag_counter[cat][tag] += 1

        if matched:
            books_with_tags += 1
            for i in range(len(matched)):
                for j in range(i + 1, len(matched)):
                    pair = tuple(sorted([matched[i], matched[j]]))
                    cooccur[pair] += 1

    # Build per-tag frequency list
    global_tags = [{"tag": tag, "count": count} for tag, count in tag_counter.most_common()]
    by_category = {
        cat: [{"tag": tag, "count": count} for tag, count in counter.most_common()]
        for cat, counter in sorted(cat_tag_counter.items())
    }
    cooccurrences = [
        {"tags": list(pair), "count": count}
        for pair, count in cooccur.most_common(50)
    ]

    return {
        "total_books": len(books),
        "books_with_tags": books_with_tags,
        "global": global_tags,
        "by_category": by_category,
        "cooccurrences": cooccurrences,
    }


def _load_and_deduplicate(data_dir: Path) -> list[dict]:
    """Load all weekly JSON files, deduplicate books by (title, author)."""
    seen: set[tuple[str, str]] = set()
    books = []

    for fpath in sorted(data_dir.glob("*.json")):
        if fpath.name == "index.json":
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except (json.JSONDecodeError, KeyError):
            continue

        # Exclude placeholder data (W20-W21 have fake intros)
        if snap.get("total", 0) < 1000:
            logger.info("Skipping %s (total=%d, likely placeholder data)", fpath.name, snap.get("total", 0))
            continue

        for book in snap.get("books", []):
            key = (book.get("title", ""), book.get("author", ""))
            if key not in seen:
                seen.add(key)
                books.append(book)

    logger.info("Loaded %d unique books from %s", len(books), data_dir)
    return books


def run_text_mining(data_dir: Path = None, week_label: str = None) -> dict:
    """Run all text mining analyses and save results to data/analysis/."""
    if data_dir is None:
        data_dir = DATA_DIR

    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    load_custom_dict()

    # Load and deduplicate
    books = _load_and_deduplicate(data_dir)
    logger.info("Text mining on %d unique books", len(books))

    # Segment
    tokenized = segment_intros(books)
    non_empty = sum(1 for t in tokenized if t)
    logger.info("Tokenized: %d/%d non-empty", non_empty, len(books))

    # TF-IDF global
    logger.info("Computing global TF-IDF...")
    keywords = compute_tfidf_global(books, tokenized)
    keywords["updated_at"] = datetime.now().isoformat()
    with open(analysis_dir / "keywords.json", "w", encoding="utf-8") as f:
        json.dump(keywords, f, ensure_ascii=False, indent=2)
    logger.info("Saved keywords.json (%d tokens)", len(keywords.get("tokens", [])))

    # TF-IDF per category
    logger.info("Computing per-category TF-IDF...")
    cat_keywords = compute_tfidf_per_category(books, tokenized)
    cat_output = {"updated_at": datetime.now().isoformat(), "categories": cat_keywords}
    with open(analysis_dir / "category_keywords.json", "w", encoding="utf-8") as f:
        json.dump(cat_output, f, ensure_ascii=False, indent=2)
    logger.info("Saved category_keywords.json (%d categories)", len(cat_keywords))

    # Genre tags
    logger.info("Extracting genre tags...")
    genre_tags = extract_genre_tags(books)
    genre_tags["updated_at"] = datetime.now().isoformat()
    with open(analysis_dir / "genre_tags.json", "w", encoding="utf-8") as f:
        json.dump(genre_tags, f, ensure_ascii=False, indent=2)
    logger.info("Saved genre_tags.json (%d tags)", len(genre_tags.get("global", [])))

    return {
        "n_books": len(books),
        "n_keywords": len(keywords.get("tokens", [])),
        "n_genre_tags": len(genre_tags.get("global", [])),
        "n_categories": len(cat_keywords),
    }
