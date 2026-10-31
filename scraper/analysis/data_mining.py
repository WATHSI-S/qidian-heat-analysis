"""Week-scoped forecast, exact pair associations, clustering and anomalies."""
import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from itertools import permutations
from pathlib import Path
from statistics import mean, pstdev

from domain import DATA_DIR, RANK_LABELS, adjacent_weeks, book_key, comparable, load_week, load_weeks
from analysis.metrics import category_totals, rank_quality
from analysis.results import record_failure, write_result

logger = logging.getLogger(__name__)
RANK_TYPES = list(RANK_LABELS)


def _holt_predict(values):
    from statsmodels.tsa.holtwinters import Holt
    fitted = Holt(values, initialization_method="estimated").fit()
    values = [float(v) for v in fitted.forecast(2)]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Non-finite Holt forecast")
    return [max(0., value) for value in values]


def forecast_series(values, predict=None):
    """Validate both forecast horizons on at least four rolling origins."""
    predict = predict or _holt_predict
    if len(values) < 9 or sum(v > 0 for v in values) < 3:
        return {"forecast": None, "forecast_w2": None, "reason": "insufficient_backtests", "backtest_origins": 0}
    model_errors, baseline_errors = [], []
    origins = 0
    for end in range(4, len(values) - 1):
        predicted = predict(values[:end])
        if len(predicted) != 2 or not all(math.isfinite(v) for v in predicted):
            raise ValueError("Non-finite forecast")
        for horizon in range(2):
            model_errors.append(abs(predicted[horizon] - values[end + horizon]))
            baseline_errors.append(abs(values[end - 1] - values[end + horizon]))
        origins += 1
    model_mae, baseline_mae = mean(model_errors), mean(baseline_errors)
    validated = origins >= 4 and model_mae < baseline_mae
    fc = predict(values) if validated else [None, None]
    if validated and not all(math.isfinite(v) for v in fc):
        raise ValueError("Non-finite forecast")
    return {"forecast": round(max(0, fc[0]), 2) if validated else None,
            "forecast_w2": round(max(0, fc[1]), 2) if validated else None,
            "backtest_origins": origins, "model_mae": model_mae, "baseline_mae": baseline_mae,
            "reason": "validated" if validated else "baseline_not_beaten"}


def forecast_categories(data_dir=DATA_DIR, week_label=None):
    current = load_week(data_dir, week_label)
    weeks = load_weeks(data_dir, current["week"])
    definitions = {rt: q.get("definition_id") for rt, q in current["quality"]["rankings"].items()}
    weeks = [w for w in weeks if all(q.get("definition_id") == definitions[rt] for rt, q in w["quality"]["rankings"].items())]
    complete = []
    # Do not compress missing/partial weeks into an apparently regular time series.
    following = None
    for snap in reversed(weeks):
        monday = date.fromisocalendar(int(snap["week"][:4]), int(snap["week"][-2:]), 1)
        if snap["quality"]["status"] != "complete" or (following and following - monday != timedelta(weeks=1)):
            break
        complete.append(snap)
        following = monday
    complete.reverse()
    eligible = [w for w in weeks if w["quality"]["status"] == "complete"]
    depths = {rt: min(w["quality"]["rankings"][rt]["depth"] for w in eligible) for rt in RANK_TYPES} if eligible else {}
    totals = [category_totals([b for b in w["books"] if b["rank"] <= depths[b["rank_type"]]]) for w in complete]
    cats = sorted({b.get("category") or "未知" for w in weeks for b in w["books"]})
    result = {"n_weeks": len(complete), "week_labels": [w["week"] for w in weeks], "categories": {},
              "comparison_depths": depths, "experimental": True}
    for cat in cats:
        history = [{"week": w["week"], "heat": round(category_totals([b for b in w["books"] if b["rank"] <= depths[b["rank_type"]]]).get(cat, {}).get("heat", 0.), 2)
                    if w["quality"]["status"] == "complete" else None} for w in weeks]
        series = [t.get(cat, {}).get("heat", 0.) for t in totals]
        output = forecast_series(series)
        result["categories"][cat] = {"history": history, **output}
    return write_result(data_dir, current["week"], "forecast.json", result, [w["week"] for w in weeks])


def mine_association_rules(data_dir=DATA_DIR, week_label=None):
    week = load_week(data_dir, week_label)
    eligible = {rt for rt, q in week["quality"]["rankings"].items() if q["status"] == "complete"}
    transactions = defaultdict(set)
    for b in week["books"]:
        if b["rank_type"] in eligible:
            transactions[book_key(b)].add(b["rank_type"])
    n = len(transactions)
    presences = {rt: {key for key, ranks in transactions.items() if rt in ranks} for rt in eligible}
    rules = []
    # With max_len=2 there are only 56 directed pairs; direct counts are exact.
    for a, b in permutations(sorted(eligible), 2):
        shared = len(presences[a] & presences[b])
        support = shared / n if n else 0.
        confidence = shared / len(presences[a]) if presences[a] else 0.
        if support >= .05 and confidence >= .5:
            rules.append({"antecedent": a, "consequent": b, "support": round(support, 4),
                          "confidence": round(confidence, 4), "lift": round(confidence / (len(presences[b]) / n), 4)})
    rules.sort(key=lambda r: (-r["lift"], r["antecedent"], r["consequent"]))
    return write_result(data_dir, week["week"], "association_rules.json", {"rules": rules, "n_transactions": n, "rank_types": sorted(eligible)})


def cluster_books(data_dir: Path = None, week_label: str = None) -> dict:
    """K-means clustering of books by cross-rank performance, PCA visualization."""

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    if data_dir is None:
        data_dir = DATA_DIR

    week = load_week(data_dir, week_label)
    week_label = week["week"]

    # Build feature vectors per book
    books_index = {}
    eligible = [b for b in week["books"] if week["quality"]["rankings"][b["rank_type"]]["status"] == "complete"]
    for b in eligible:
        key = (b["title"], b["author"])
        if key not in books_index:
            books_index[key] = {r: 0 for r in RANK_TYPES}
            books_index[key]["_category"] = b.get("category", "")
            books_index[key]["_status"] = b.get("status", "")
        rt = b.get("rank_type", "")
        if rt in books_index[key]:
            # Normalize rank: 1→1.0, 200→0.0
            rank = b.get("rank", 200)
            normalized = rank_quality(rank, week["quality"]["rankings"][rt]["depth"])
            books_index[key][rt] = max(books_index[key][rt], normalized)

    if len(books_index) < 20:
        logger.warning("Too few books for clustering: %d", len(books_index))
        return write_result(data_dir, week_label, "clusters.json", {"clusters": [], "k": 0, "message": "insufficient_data"})

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
    rank_labels = [RANK_LABELS[r].removesuffix("榜") for r in RANK_TYPES]
    for i in range(k):
        top_idx = np.argmax(centroids[i])
        cluster_labels.append(f"{rank_labels[top_idx]}型")

    clusters = []
    for i in range(k):
        mask = labels == i
        cluster_books_list = []
        for j in np.where(mask)[0]:
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
        "week": week_label,
    }

    return write_result(data_dir, week_label, "clusters.json", result)


def detect_anomalies(data_dir=DATA_DIR, week_label=None):
    current = load_week(data_dir, week_label)
    history = load_weeks(data_dir, current["week"])
    result = {"anomalies": [], "n_anomalies": 0}
    if len(history) < 2 or not adjacent_weeks(history[-2]["week"], current["week"]):
        return write_result(data_dir, current["week"], "anomalies.json", result)
    old, new, depths = comparable(history[-2], current)
    lookup = {(*book_key(b), b["rank_type"]): b["rank"] for b in old}
    groups = defaultdict(list)
    for b in new:
        prior = lookup.get((*book_key(b), b["rank_type"]))
        if prior is not None:
            groups[(b["rank_type"], b.get("category") or "未知")].append({**b, "prev_rank": prior, "cur_rank": b["rank"], "delta": prior - b["rank"]})
    for entries in groups.values():
        deltas = [e["delta"] for e in entries]
        if len(deltas) < 5 or pstdev(deltas) < .5:
            continue
        avg, std = mean(deltas), pstdev(deltas)
        for e in entries:
            z = (e["delta"] - avg) / std
            if abs(z) > 2.5:
                result["anomalies"].append({**e, "z_score": round(z, 2), "direction": "up" if e["delta"] > 0 else "down"})
    result["anomalies"].sort(key=lambda e: -abs(e["z_score"]))
    result["n_anomalies"] = len(result["anomalies"])
    result["anomalies"] = result["anomalies"][:50]
    result["comparison_depths"] = depths
    return write_result(data_dir, current["week"], "anomalies.json", result, [history[-2]["week"], current["week"]])


def run_data_mining(data_dir=None, week_label=None):
    data_dir = data_dir or DATA_DIR
    week = load_week(data_dir, week_label)["week"]
    summary = {}
    for filename, function in [("forecast", forecast_categories), ("association_rules", mine_association_rules), ("clusters", cluster_books), ("anomalies", detect_anomalies)]:
        try:
            summary[filename] = function(data_dir, week)
        except Exception as error:
            logger.exception("%s failed", filename)
            summary[filename] = record_failure(data_dir, week, filename + ".json", type(error).__name__)
    return summary
