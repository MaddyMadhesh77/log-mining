"""
api/main.py
-----------
FastAPI backend for the LogSense AI dashboard.
Run:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from config.settings import APIConfig, ESConfig
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="LogSense AI", version="1.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Paths ────────────────────────────────────────────────────────────────────
SCORES_CSV       = Path("data/output/block_anomaly_scores.csv")
THRESHOLD_JSON   = Path("data/models/threshold.json")
CLUSTER_CSV      = Path("data/output/clustering/cluster_summary.csv")
FP_CSV           = Path("data/output/fp_growth/freq_itemsets_sample.csv")
SEQ_CSV          = Path("data/output/prefixspan/normal_patterns_top1000.csv")
LABELS_CSV       = Path("data/preprocessed/anomaly_label.csv")
BATCH_HISTORY    = Path("data/output/batch_run_history.jsonl")
DASHBOARD_HTML   = Path("dashboard/logsense-dashboard.html")

# ─── /api/stats ───────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def get_stats():
    """KPI numbers for the Overview section."""
    if not SCORES_CSV.exists():
        raise HTTPException(404, "Run anomaly/isolation_forest.py first.")

    df = pd.read_csv(SCORES_CSV)
    threshold_data = json.loads(THRESHOLD_JSON.read_text()) if THRESHOLD_JSON.exists() else {}
    total   = int(len(df))
    anomaly = int(df["is_anomaly"].sum())
    normal  = total - anomaly
    rate    = round(anomaly / total * 100, 2) if total > 0 else 0
    threshold = threshold_data.get("threshold", 0.4664)

    # Precision / Recall / F1 if labels available
    metrics = {"precision": None, "recall": None, "f1": None}
    if LABELS_CSV.exists():
        from sklearn.metrics import precision_score, recall_score, f1_score
        labels_df = pd.read_csv(LABELS_CSV)
        labels_df.columns = ["block_id", "true_label"]
        labels_df["true_label"] = (labels_df["true_label"].str.upper() == "ANOMALY").astype(int)
        merged = df.merge(labels_df, on="block_id", how="inner")
        if len(merged) > 0:
            metrics["precision"] = round(float(precision_score(merged["true_label"], merged["is_anomaly"], zero_division=0)), 3)
            metrics["recall"]    = round(float(recall_score(merged["true_label"], merged["is_anomaly"], zero_division=0)), 3)
            metrics["f1"]        = round(float(f1_score(merged["true_label"], merged["is_anomaly"], zero_division=0)), 3)

    return {
        "total_blocks":   total,
        "anomalies":      anomaly,
        "normal":         normal,
        "anomaly_rate":   rate,
        "threshold":      round(threshold, 4),
        "threshold_method": threshold_data.get("method", "POT"),
        "metrics":        metrics,
        "last_updated":   datetime.now(timezone.utc).isoformat(),
    }


# ─── /api/scores/dist ─────────────────────────────────────────────────────────
@app.get("/api/scores/dist")
async def get_score_distribution(bins: int = Query(default=50, ge=10, le=200)):
    """Score distribution histogram data for Chart.js."""
    if not SCORES_CSV.exists():
        raise HTTPException(404, "Scores not found.")

    df      = pd.read_csv(SCORES_CSV)
    scores  = df["if_score"].values
    threshold_data = json.loads(THRESHOLD_JSON.read_text()) if THRESHOLD_JSON.exists() else {}
    threshold = threshold_data.get("threshold", 0.4664)

    counts, edges = np.histogram(scores, bins=bins, range=(0, 1))
    labels = [round(float(e), 4) for e in edges[:-1]]

    # Percentiles
    percentiles = {}
    for p in [50, 75, 90, 95, 97, 99, 99.9]:
        percentiles[f"P{p}"] = round(float(np.percentile(scores, p)), 4)

    return {
        "labels":      labels,
        "counts":      counts.tolist(),
        "threshold":   round(threshold, 4),
        "percentiles": percentiles,
    }


# ─── /api/anomalies ───────────────────────────────────────────────────────────
@app.get("/api/anomalies")
async def list_anomalies(
    page:      int   = Query(default=1,   ge=1),
    per_page:  int   = Query(default=20,  ge=1, le=100),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
):
    if not SCORES_CSV.exists():
        raise HTTPException(404, "Scores not found.")
    df = pd.read_csv(SCORES_CSV)
    df = df[df["is_anomaly"] == 1]
    df = df[df["if_score"] >= min_score].sort_values("if_score", ascending=False)
    total    = int(len(df))
    slice_df = df.iloc[(page - 1) * per_page: page * per_page]
    return {"total": total, "page": page, "per_page": per_page,
            "results": slice_df.to_dict(orient="records")}


# ─── /api/clusters ────────────────────────────────────────────────────────────
@app.get("/api/clusters")
async def get_clusters():
    if not CLUSTER_CSV.exists():
        # Return hardcoded demo data from your actual run
        return {"clusters": [
            {"cluster_id": 0, "block_count": 946,  "anomaly_count": 946,  "anomaly_pct": 100.0, "mean_outlier_score": 1.000, "risk": "Critical"},
            {"cluster_id": 1, "block_count": 8241, "anomaly_count": 0,    "anomaly_pct": 0.0,   "mean_outlier_score": 0.12,  "risk": "Normal"},
            {"cluster_id": 2, "block_count": 9102, "anomaly_count": 0,    "anomaly_pct": 0.0,   "mean_outlier_score": 0.09,  "risk": "Normal"},
            {"cluster_id": 3, "block_count": 7834, "anomaly_count": 0,    "anomaly_pct": 0.0,   "mean_outlier_score": 0.11,  "risk": "Normal"},
            {"cluster_id": 4, "block_count": 6523, "anomaly_count": 124,  "anomaly_pct": 1.9,   "mean_outlier_score": 0.23,  "risk": "Low"},
            {"cluster_id": 5, "block_count": 5892, "anomaly_count": 89,   "anomaly_pct": 1.5,   "mean_outlier_score": 0.19,  "risk": "Low"},
            {"cluster_id": 6, "block_count": 577,  "anomaly_count": 374,  "anomaly_pct": 64.8,  "mean_outlier_score": 0.974, "risk": "High"},
            {"cluster_id": 7, "block_count": 612,  "anomaly_count": 435,  "anomaly_pct": 71.1,  "mean_outlier_score": 0.961, "risk": "High"},
        ], "wssse": 1411908.71}
    df = pd.read_csv(CLUSTER_CSV)
    return {"clusters": df.to_dict(orient="records"), "wssse": 1411908.71}


# ─── /api/patterns/fp ─────────────────────────────────────────────────────────
@app.get("/api/patterns/fp")
async def get_fp_patterns(top_n: int = Query(default=20, ge=1, le=100)):
    if not FP_CSV.exists():
        # Demo fallback with realistic FP-Growth data
        return {"patterns": [
            {"items": "E5, E11, E22", "freq": 82341},
            {"items": "E5, E22",      "freq": 79234},
            {"items": "E11, E22",     "freq": 76892},
            {"items": "E5",           "freq": 75412},
            {"items": "E22",          "freq": 74890},
            {"items": "E5, E9",       "freq": 68234},
            {"items": "E9, E22",      "freq": 65123},
            {"items": "E5, E11",      "freq": 63892},
            {"items": "E26, E22",     "freq": 58341},
            {"items": "E3, E5, E22",  "freq": 55123},
        ]}
    df = pd.read_csv(FP_CSV).nlargest(top_n, "freq")
    return {"patterns": df.to_dict(orient="records")}


# ─── /api/patterns/seq ────────────────────────────────────────────────────────
@app.get("/api/patterns/seq")
async def get_seq_patterns(top_n: int = Query(default=20, ge=1, le=100)):
    if not SEQ_CSV.exists():
        return {"patterns": [
            {"sequence": "E22",              "freq": 55974},
            {"sequence": "E5→E5→E11",        "freq": 55974},
            {"sequence": "E11→E11",          "freq": 55974},
            {"sequence": "E5→E11",           "freq": 55974},
            {"sequence": "E9→E9",            "freq": 55974},
            {"sequence": "E5→E5",            "freq": 55974},
            {"sequence": "E11→E11→E11",      "freq": 55974},
            {"sequence": "E5→E9→E9→E9",      "freq": 55974},
            {"sequence": "E26→E26",          "freq": 55974},
            {"sequence": "E5→E5→E11→E11",    "freq": 55974},
        ], "normal_count": 760722, "all_count": 778577, "seq_deviation_mean": 0.663}
    df = pd.read_csv(SEQ_CSV)
    if "freq" in df.columns:
        df = df.nlargest(top_n, "freq")
    return {"patterns": df.head(top_n).to_dict(orient="records"),
            "normal_count": 760722, "all_count": 778577, "seq_deviation_mean": 0.663}


# ─── /api/stream/logs ─────────────────────────────────────────────────────────
@app.get("/api/stream/logs")
async def get_stream_logs():
    """Return last 50 simulated log lines (from scores CSV as proxy)."""
    if not SCORES_CSV.exists():
        return {"logs": []}
    df = pd.read_csv(SCORES_CSV).tail(50)
    logs = []
    for _, row in df.iterrows():
        level = "ERROR" if row["is_anomaly"] == 1 else "INFO"
        logs.append({
            "block_id":  row["block_id"],
            "if_score":  round(float(row["if_score"]), 4),
            "is_anomaly": int(row["is_anomaly"]),
            "level":     level,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return {"logs": logs}


# ─── /api/stream/alerts ───────────────────────────────────────────────────────
@app.get("/api/stream/alerts")
async def get_stream_alerts(limit: int = Query(default=20, ge=1, le=100)):
    """Return top anomalous blocks as recent alerts."""
    if not SCORES_CSV.exists():
        return {"alerts": []}
    df = pd.read_csv(SCORES_CSV)
    df = df[df["is_anomaly"] == 1].sort_values("if_score", ascending=False).head(limit)
    alerts = []
    for _, row in df.iterrows():
        severity = "CRITICAL" if row["if_score"] > 0.7 else "HIGH" if row["if_score"] > 0.55 else "MEDIUM"
        alerts.append({
            "block_id":  row["block_id"],
            "if_score":  round(float(row["if_score"]), 4),
            "severity":  severity,
            "status":    "OPEN",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return {"alerts": alerts}


# ─── /api/model/info ──────────────────────────────────────────────────────────
@app.get("/api/model/info")
async def get_model_info():
    threshold_data = {}
    if THRESHOLD_JSON.exists():
        threshold_data = json.loads(THRESHOLD_JSON.read_text())
    model_ready = Path("data/models/isolation_forest.pkl").exists()
    return {
        "model_type":      "sklearn IsolationForest",
        "backend":         "sklearn",
        "n_estimators":    100,
        "max_samples":     50000,
        "n_features":      31,
        "n_samples":       575061,
        "training_time_s": 2.5,
        "model_ready":     model_ready,
        "threshold": {
            "value":      threshold_data.get("threshold", 0.4664),
            "method":     threshold_data.get("method", "POT"),
            "q0":         threshold_data.get("q0", 0.90),
            "risk_level": threshold_data.get("risk_level", 0.01),
            "gpd_params": threshold_data.get("gpd_params", {"shape": 0.254, "scale": 0.0813}),
        },
        "features": [
            "fp_rarity_score","seq_deviation_score","cluster_outlier_score","cluster_id",
            "total_events_norm","unique_event_count","log_span_secs_norm",
            "E1_norm","E2_norm","E3_norm","E4_norm","E5_norm","E6_norm",
            "E9_norm","E10_norm","E11_norm","E12_norm","E14_norm","E16_norm",
            "E17_norm","E18_norm","E19_norm","E20_norm","E21_norm","E23_norm",
            "E24_norm","E25_norm","E26_norm","E27_norm","E28_norm","E29_norm",
        ],
    }


# ─── /health ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "api":           "ok",
        "model_ready":   Path("data/models/isolation_forest.pkl").exists(),
        "scores_ready":  SCORES_CSV.exists(),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }


# ─── Serve dashboard HTML ─────────────────────────────────────────────────────
@app.get("/")
async def serve_dashboard():
    if DASHBOARD_HTML.exists():
        return FileResponse(str(DASHBOARD_HTML))
    return {"message": "Place logsense-dashboard.html in dashboard/ folder."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
