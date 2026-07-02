"""
Data mining module: time-series forecast, association rules, clustering, anomaly detection.
"""

import json
import logging
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.holtwinters import Holt

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"

RANK_WEIGHTS = {
    "yuepiao": 1.0, "hotsales": 0.95, "readindex": 0.85,
    "recom": 0.8, "collect": 0.75, "signnewbook": 0.7, "newfans": 0.6, "vipup": 0.5,
}
RANK_TYPES = list(RANK_WEIGHTS.keys())

# ── Shared helpers ──

def _rank_score(rank: int, weight: float) -> float:
    return weight / math.sqrt(max(rank, 1))


def _compute_heat(books: list[dict]) -> float:
    """Aggregate weighted heat score for a list of books."""
    scored = defaultdict(float)
    for b in books:
        w = RANK_WEIGHTS.get(b.get("rank_type", ""), 0.5)
        scored[(b["title"], b["author"])] += _rank_score(b.get("rank", 200), w)
    return sum(scored.values())


def _load_all_weeks(data_dir: Path) -> list[dict]:
    """Load index.json and all week JSON files, return sorted list."""
    index_path = data_dir / "index.json"
    if not index_path.exists():
        logger.warning("index.json not found at %s", index_path)
        return []
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    weeks = []
    for w in index.get("weeks", []):
        if w.get("total", 0) < 1000:  # skip placeholder weeks (W20-W21)
            continue
        week_path = data_dir / w["file"]
        if week_path.exists():
            with open(week_path, encoding="utf-8") as f:
                data = json.load(f)
            weeks.append(data)
    weeks.sort(key=lambda w: w["week"])
    return weeks


def _get_latest_week(data_dir: Path, week_label: str = None) -> dict:
    """Return the latest (or specified) week data."""
    if week_label:
        path = data_dir / f"{week_label}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        raise FileNotFoundError(f"Week file not found: {path}")

    weeks = _load_all_weeks(data_dir)
    if not weeks:
        raise ValueError("No week data available")
    return weeks[-1]


# ── 3.1 Time-series forecast ──

def forecast_categories(data_dir: Path = None) -> dict:
    """Holt double-exponential smoothing per category, forecast 1-2 weeks ahead."""
    if data_dir is None:
        data_dir = DATA_DIR

    weeks = _load_all_weeks(data_dir)
    if len(weeks) < 4:
        logger.warning("Need >=4 weeks for forecast, got %d", len(weeks))
        return {"error": "insufficient_data", "n_weeks": len(weeks), "categories": {}}

    # Aggregate heat per category per week
    cat_series = defaultdict(list)
    week_labels = []
    for w in weeks:
        week_labels.append(w["week"])
        cat_heat = defaultdict(float)
        for b in w["books"]:
            if b.get("category"):
                wgt = RANK_WEIGHTS.get(b.get("rank_type", ""), 0.5)
                cat_heat[b["category"]] += _rank_score(b.get("rank", 200), wgt)
        for cat, heat in cat_heat.items():
            cat_series[cat].append(round(heat, 2))
        # fill 0 for categories not present in this week
        for cat in cat_series:
            if len(cat_series[cat]) < len(week_labels):
                cat_series[cat].append(0.0)

    result = {"updated_at": datetime.now().isoformat(), "n_weeks": len(weeks),
              "week_labels": week_labels, "categories": {}}

    for cat, series in cat_series.items():
        if len([v for v in series if v > 0]) < 3:
            continue  # skip sparse categories

        history = [{"week": week_labels[i], "heat": series[i]} for i in range(len(series))]

        # Fit Holt model (double exponential smoothing, trend only)
        try:
            model = Holt(series, initialization_method="estimated")
            fitted = model.fit()
            forecast_vals = fitted.forecast(2)
            # Compute residuals for CI
            fitted_vals = fitted.fittedvalues
            residuals = [series[i] - fitted_vals[i] for i in range(len(series)) if not np.isnan(fitted_vals[i])]
            residual_std = np.std(residuals) if len(residuals) > 1 else 0

            result["categories"][cat] = {
                "history": history,
                "trend": [round(v, 2) if not np.isnan(v) else None for v in fitted_vals.tolist()],
                "forecast": round(forecast_vals[0], 2),
                "forecast_w2": round(forecast_vals[1], 2) if len(forecast_vals) > 1 else None,
                "ci_upper": round(forecast_vals[0] + 1.96 * residual_std, 2),
                "ci_lower": round(max(0, forecast_vals[0] - 1.96 * residual_std), 2),
                "trend_direction": "up" if forecast_vals[0] > series[-1] else "down",
            }
        except Exception as e:
            logger.warning("Forecast failed for %s: %s", cat, e)
            continue

    output_path = ANALYSIS_DIR / "forecast.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Forecast written: %d categories", len(result["categories"]))

    return {"n_categories_forecast": len(result["categories"]), "n_weeks": len(weeks)}


# ── 3.2 Association rule mining ──

def mine_association_rules(data_dir: Path = None, week_label: str = None) -> dict:
    """Apriori on 8-rank presence/absence vectors for the target week."""
    try:
        from mlxtend.frequent_patterns import apriori, association_rules
    except ImportError:
        logger.error("mlxtend not installed; skipping association rules")
        return {"error": "mlxtend_not_installed"}

    if data_dir is None:
        data_dir = DATA_DIR

    week = _get_latest_week(data_dir, week_label)
    week_label = week["week"]

    # Build transaction matrix: each unique book = one row, columns = rank_type presence
    book_ranks = defaultdict(lambda: {r: 0 for r in RANK_TYPES})
    for b in week["books"]:
        rt = b.get("rank_type", "")
        if rt in book_ranks[(b["title"], b["author"])]:
            book_ranks[(b["title"], b["author"])][rt] = 1

    if len(book_ranks) < 10:
        logger.warning("Too few books for association mining: %d", len(book_ranks))
        return {"error": "insufficient_data", "n_books": len(book_ranks)}

    df = pd.DataFrame(list(book_ranks.values()))
    df = df.astype(bool)

    # Apriori with min_support
    frequent = apriori(df, min_support=0.05, use_colnames=True, max_len=2)
    if frequent.empty:
        logger.info("No frequent itemsets found")
        result = {"rules": [], "n_transactions": len(df), "week": week_label,
                  "updated_at": datetime.now().isoformat()}
    else:
        rules = association_rules(frequent, metric="confidence", min_threshold=0.5)
        rules_list = []
        for _, row in rules.iterrows():
            ant = list(row["antecedents"])
            con = list(row["consequents"])
            if len(ant) == 1 and len(con) == 1:
                rules_list.append({
                    "antecedent": ant[0],
                    "consequent": con[0],
                    "support": round(row["support"], 4),
                    "confidence": round(row["confidence"], 4),
                    "lift": round(row["lift"], 4),
                })
        rules_list.sort(key=lambda r: r["lift"], reverse=True)
        result = {"rules": rules_list[:20], "n_transactions": len(df), "week": week_label,
                  "updated_at": datetime.now().isoformat()}

    output_path = ANALYSIS_DIR / "association_rules.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Association rules written: %d rules", len(result.get("rules", [])))

    return {"n_rules": len(result.get("rules", [])), "n_transactions": result["n_transactions"]}


# ── 3.3 K-means clustering ──

def cluster_books(data_dir: Path = None, week_label: str = None) -> dict:
    """K-means clustering of books by cross-rank performance, PCA visualization."""

    if data_dir is None:
        data_dir = DATA_DIR

    week = _get_latest_week(data_dir, week_label)
    week_label = week["week"]

    # Build feature vectors per book
    books_index = {}
    for b in week["books"]:
        key = (b["title"], b["author"])
        if key not in books_index:
            books_index[key] = {r: 0 for r in RANK_TYPES}
            books_index[key]["_category"] = b.get("category", "")
            books_index[key]["_status"] = b.get("status", "")
        rt = b.get("rank_type", "")
        if rt in books_index[key]:
            # Normalize rank: 1→1.0, 200→0.0
            rank = b.get("rank", 200)
            normalized = max(0, 1 - (rank - 1) / 199)
            books_index[key][rt] = max(books_index[key][rt], normalized)

    if len(books_index) < 20:
        logger.warning("Too few books for clustering: %d", len(books_index))
        return {"error": "insufficient_data", "n_books": len(books_index)}

    # Build matrix
    keys = list(books_index.keys())
    X = np.array([[books_index[k][r] for r in RANK_TYPES] for k in keys])

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # K-means (k=4)
    k = min(4, len(keys) // 5)
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=20)
    labels = kmeans.fit_predict(X_scaled)

    # PCA for 2D visualization
    pca = PCA(n_components=2)
    coords = pca.fit_transform(X_scaled)

    # Interpret clusters: label by dominant feature
    centroids = kmeans.cluster_centers_
    cluster_labels = []
    rank_labels = ["月票", "畅销", "阅读", "推荐", "收藏", "新书", "书友", "更新"]
    for i in range(k):
        top_idx = np.argmax(centroids[i])
        cluster_labels.append(f"{rank_labels[top_idx]}型")

    clusters = []
    for i in range(k):
        mask = labels == i
        cluster_books_list = []
        for j in np.where(mask)[0][:10]:  # top 10 per cluster
            cluster_books_list.append({
                "title": keys[j][0], "author": keys[j][1],
                "category": books_index[keys[j]]["_category"],
                "coords": [round(float(coord), 4) for coord in coords[j]],
            })
        clusters.append({
            "id": i, "label": cluster_labels[i], "size": int(mask.sum()),
            "centroid": [round(float(v), 4) for v in centroids[i].tolist()],
            "books": cluster_books_list,
        })

    result = {
        "k": k, "clusters": clusters,
        "pca_variance": [round(float(v), 4) for v in pca.explained_variance_ratio_],
        "week": week_label, "updated_at": datetime.now().isoformat(),
    }

    output_path = ANALYSIS_DIR / "clusters.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Clusters written: k=%d, n=%d", k, len(keys))

    return {"k": k, "n_books": len(keys), "clusters": [{"id": c["id"], "label": c["label"], "size": c["size"]} for c in clusters]}


# ── 3.4 Anomaly detection ──

def detect_anomalies(data_dir: Path = None, week_label: str = None) -> dict:
    """Z-score based anomaly detection on week-over-week ranking changes."""

    if data_dir is None:
        data_dir = DATA_DIR

    cur_week = _get_latest_week(data_dir, week_label)
    cur_label = cur_week["week"]

    # Find previous week
    weeks = _load_all_weeks(data_dir)
    prev_week = None
    for i, w in enumerate(weeks):
        if w["week"] == cur_label and i > 0:
            prev_week = weeks[i - 1]
            break
    if prev_week is None:
        logger.warning("No previous week for anomaly detection")
        return {"error": "no_previous_week", "anomalies": []}

    # Build lookup: (title, author, rank_type) → rank
    prev_lookup = {}
    for b in prev_week["books"]:
        prev_lookup[(b["title"], b["author"], b.get("rank_type", ""))] = b.get("rank", 200)

    # Compute rank changes per category
    cat_deltas = defaultdict(list)
    entries = []
    for b in cur_week["books"]:
        key = (b["title"], b["author"], b.get("rank_type", ""))
        prev_rank = prev_lookup.get(key)
        cur_rank = b.get("rank", 200)
        if prev_rank is not None:
            delta = prev_rank - cur_rank  # positive = improved
            cat = b.get("category", "未知")
            cat_deltas[cat].append(delta)
            entries.append({
                "title": b["title"], "author": b["author"],
                "category": cat, "rank_type": b.get("rank_type", ""),
                "prev_rank": prev_rank, "cur_rank": cur_rank, "delta": delta,
            })

    if not entries:
        return {"error": "no_overlapping_books", "anomalies": []}

    # Compute Z-score per category
    anomalies = []
    for cat, deltas in cat_deltas.items():
        if len(deltas) < 5:
            continue
        mean_d = np.mean(deltas)
        std_d = np.std(deltas)
        if std_d < 0.5:
            continue

        cat_entries = [e for e in entries if e["category"] == cat]
        for e in cat_entries:
            z = (e["delta"] - mean_d) / std_d
            if abs(z) > 2.5:
                anomalies.append({
                    "title": e["title"], "author": e["author"],
                    "category": e["category"], "rank_type": e["rank_type"],
                    "prev_rank": e["prev_rank"], "cur_rank": e["cur_rank"],
                    "z_score": round(float(z), 2),
                    "direction": "up" if z > 0 else "down",
                })

    anomalies.sort(key=lambda a: abs(a["z_score"]), reverse=True)
    result = {
        "anomalies": anomalies[:50],
        "n_anomalies": len(anomalies),
        "week": cur_label, "updated_at": datetime.now().isoformat(),
    }

    output_path = ANALYSIS_DIR / "anomalies.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Anomalies written: %d total", len(anomalies))

    return {"n_anomalies": len(anomalies)}


# ── Orchestrator ──

def run_data_mining(data_dir: Path = None, week_label: str = None) -> dict:
    """Run all data mining analyses and return summary."""
    if data_dir is None:
        data_dir = DATA_DIR

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=== Data Mining Pipeline ===")

    summary = {}

    try:
        fc = forecast_categories(data_dir)
        summary["forecast"] = fc
        logger.info("Forecast: %s", fc)
    except Exception as e:
        logger.error("Forecast failed: %s", e)
        summary["forecast"] = {"error": str(e)}

    try:
        ar = mine_association_rules(data_dir, week_label)
        summary["association_rules"] = ar
        logger.info("Association rules: %s", ar)
    except Exception as e:
        logger.error("Association rules failed: %s", e)
        summary["association_rules"] = {"error": str(e)}

    try:
        cl = cluster_books(data_dir, week_label)
        summary["clusters"] = cl
        logger.info("Clusters: %s", cl)
    except Exception as e:
        logger.error("Clustering failed: %s", e)
        summary["clusters"] = {"error": str(e)}

    try:
        an = detect_anomalies(data_dir, week_label)
        summary["anomalies"] = an
        logger.info("Anomalies: %s", an)
    except Exception as e:
        logger.error("Anomaly detection failed: %s", e)
        summary["anomalies"] = {"error": str(e)}

    return summary
