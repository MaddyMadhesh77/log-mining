"""
metrics.py
----------
Evaluate LogSense AI anomaly detection against Loghub ground truth labels.

Ground truth: anomaly_label.csv from Loghub HDFS_v1 dataset
    Format: BlockId, Label  (Label: "Anomaly" or "Normal")

Metrics computed:
    ┌─────────────────────────────────────────────────────┐
    │ Precision  = TP / (TP + FP)                         │
    │ Recall     = TP / (TP + FN)                         │
    │ F1 Score   = 2 × Precision × Recall / (P + R)       │
    │ F0.5 Score = weighted F — favors Precision           │
    │ F2 Score   = weighted F — favors Recall              │
    │ MCC        = Matthews Correlation Coefficient        │
    │              (better than F1 for imbalanced classes) │
    │ AUC-ROC    = Area under ROC curve                    │
    │ AUC-PR     = Area under Precision-Recall curve       │
    │              (more informative than AUC-ROC when     │
    │               positives are rare, as in log anomaly) │
    └─────────────────────────────────────────────────────┘

Why MCC and AUC-PR over just F1:
    HDFS_v1 has ~2.9% anomaly rate (16,838 / 575,061 blocks).
    On heavily imbalanced data:
    - F1 can be misleadingly high even with many FPs
    - MCC accounts for all four quadrants of confusion matrix
    - AUC-PR shows performance across ALL thresholds
    → Reporting all three gives a complete picture for the paper.

Also produces:
    - Confusion matrix
    - ROC curve data
    - Precision-Recall curve data
    - Per-threshold metrics sweep (for threshold sensitivity analysis)

Run:
    python -m evaluation.metrics
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    auc,
    average_precision_score,
    confusion_matrix,
    f1_score,
    fbeta_score,
    matthews_corrcoef,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

from config.settings import DatasetConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
LOCAL_SCORES_CSV   = Path("data/output/block_anomaly_scores.csv")
LOCAL_METRICS_JSON = Path("data/output/evaluation_metrics.json")
LOCAL_METRICS_CSV  = Path("data/output/threshold_sweep.csv")


# ─── Load ground truth ────────────────────────────────────────────────────────

def load_ground_truth(
    labels_path: Path = DatasetConfig.ANOMALY_LABELS_CSV,
) -> pd.DataFrame:
    """
    Load Loghub anomaly_label.csv.

    Returns:
        DataFrame [block_id, true_label]
        true_label: 1 = Anomaly, 0 = Normal
    """
    df = pd.read_csv(labels_path)

    # Normalize column names
    block_col = next(c for c in df.columns if "block" in c.lower())
    label_col = next(c for c in df.columns if "label" in c.lower())

    df = df.rename(columns={block_col: "block_id", label_col: "raw_label"})
    df["true_label"] = (
        df["raw_label"].str.strip().str.upper() == "ANOMALY"
    ).astype(int)

    n_anomaly = df["true_label"].sum()
    n_normal  = (df["true_label"] == 0).sum()
    total     = len(df)

    logger.info(
        "Ground truth loaded: {:,} total | {:,} anomaly ({:.2f}%) | {:,} normal",
        total,
        n_anomaly,
        n_anomaly / total * 100,
        n_normal,
    )
    return df[["block_id", "true_label"]]


def load_predictions(
    scores_path: Path = LOCAL_SCORES_CSV,
) -> pd.DataFrame:
    """
    Load IF anomaly scores and binary predictions.

    Returns:
        DataFrame [block_id, if_score, is_anomaly]
    """
    df = pd.read_csv(scores_path)
    logger.info(
        "Predictions loaded: {:,} blocks | {:,} flagged anomalies",
        len(df),
        df["is_anomaly"].sum(),
    )
    return df[["block_id", "if_score", "is_anomaly"]]


def align_predictions_with_truth(
    ground_truth_df: pd.DataFrame,
    predictions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Inner join ground truth with predictions on block_id.

    Only blocks present in BOTH datasets are evaluated.
    Logs counts of blocks that appear in one but not the other.
    """
    merged = ground_truth_df.merge(
        predictions_df,
        on="block_id",
        how="inner",
    )

    in_truth_only = len(ground_truth_df) - len(merged)
    in_pred_only  = len(predictions_df) - len(merged)

    if in_truth_only > 0:
        logger.warning(
            "{:,} blocks in ground truth but not in predictions "
            "(treated as unscored — excluded from metrics)",
            in_truth_only,
        )
    if in_pred_only > 0:
        logger.warning(
            "{:,} blocks in predictions but not in ground truth "
            "(excluded from metrics)",
            in_pred_only,
        )

    logger.info("Aligned dataset: {:,} blocks", len(merged))
    return merged


# ─── Core metrics ─────────────────────────────────────────────────────────────

def compute_core_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray,
) -> dict:
    """
    Compute the full metric suite.

    Args:
        y_true:  Binary ground truth (1=anomaly, 0=normal)
        y_pred:  Binary prediction at chosen threshold
        y_score: Continuous anomaly score (0–1)

    Returns:
        dict of all metrics
    """
    # Confusion matrix
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    # Core metrics
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall    = recall_score(y_true, y_pred, zero_division=0)
    f1        = f1_score(y_true, y_pred, zero_division=0)
    f05       = fbeta_score(y_true, y_pred, beta=0.5, zero_division=0)
    f2        = fbeta_score(y_true, y_pred, beta=2.0, zero_division=0)
    mcc       = matthews_corrcoef(y_true, y_pred)
    accuracy  = accuracy_score(y_true, y_pred)

    # Curve-based metrics (need continuous scores)
    try:
        auc_roc = roc_auc_score(y_true, y_score)
    except ValueError:
        auc_roc = 0.0

    try:
        auc_pr = average_precision_score(y_true, y_score)
    except ValueError:
        auc_pr = 0.0

    metrics = {
        # Counts
        "total_blocks":  int(len(y_true)),
        "true_positives":  int(tp),
        "false_positives": int(fp),
        "true_negatives":  int(tn),
        "false_negatives": int(fn),
        # Core metrics
        "accuracy":   round(float(accuracy), 4),
        "precision":  round(float(precision), 4),
        "recall":     round(float(recall), 4),
        "f1_score":   round(float(f1), 4),
        "f05_score":  round(float(f05), 4),
        "f2_score":   round(float(f2), 4),
        "mcc":        round(float(mcc), 4),
        "auc_roc":    round(float(auc_roc), 4),
        "auc_pr":     round(float(auc_pr), 4),
        # Rates
        "anomaly_rate_true": round(float(y_true.mean()), 4),
        "anomaly_rate_pred": round(float(y_pred.mean()), 4),
        "false_positive_rate": round(float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0, 4),
        "false_negative_rate": round(float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0, 4),
    }

    return metrics


def log_metrics(metrics: dict, title: str = "Evaluation Results") -> None:
    """Print formatted metrics to logger."""
    logger.info("")
    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║  {}  ║", title.center(42))
    logger.info("╠══════════════════════════════════════════════╣")
    logger.info("║  Precision : {:.4f}                          ║", metrics["precision"])
    logger.info("║  Recall    : {:.4f}                          ║", metrics["recall"])
    logger.info("║  F1 Score  : {:.4f}                          ║", metrics["f1_score"])
    logger.info("║  F0.5      : {:.4f}  (precision-weighted)    ║", metrics["f05_score"])
    logger.info("║  F2        : {:.4f}  (recall-weighted)       ║", metrics["f2_score"])
    logger.info("║  MCC       : {:.4f}                          ║", metrics["mcc"])
    logger.info("║  AUC-ROC   : {:.4f}                          ║", metrics["auc_roc"])
    logger.info("║  AUC-PR    : {:.4f}                          ║", metrics["auc_pr"])
    logger.info("╠══════════════════════════════════════════════╣")
    logger.info("║  TP={:,}  FP={:,}  TN={:,}  FN={:,}",
                metrics["true_positives"], metrics["false_positives"],
                metrics["true_negatives"], metrics["false_negatives"])
    logger.info("╚══════════════════════════════════════════════╝")
    logger.info("")


# ─── Threshold sensitivity sweep ─────────────────────────────────────────────

def threshold_sweep(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_points: int = 100,
) -> pd.DataFrame:
    """
    Sweep threshold from min to max score and compute metrics at each point.

    Used for:
    1. Threshold sensitivity analysis (show professor our threshold is near optimal)
    2. ROC and PR curve data (for paper/report figures)
    3. Finding the F1-optimal threshold (validation that POT is competitive)

    Returns:
        DataFrame with columns: threshold, precision, recall, f1, fpr, tpr
    """
    logger.info("Running threshold sweep ({} points)...", n_points)

    thresholds = np.linspace(y_score.min(), y_score.max(), n_points)
    rows = []

    for t in thresholds:
        y_pred_t = (y_score >= t).astype(int)
        p = precision_score(y_true, y_pred_t, zero_division=0)
        r = recall_score(y_true, y_pred_t, zero_division=0)
        f = f1_score(y_true, y_pred_t, zero_division=0)
        tn, fp, fn, tp = confusion_matrix(
            y_true, y_pred_t, labels=[0, 1]
        ).ravel()
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        rows.append({
            "threshold": round(float(t), 4),
            "precision": round(float(p), 4),
            "recall":    round(float(r), 4),
            "f1":        round(float(f), 4),
            "fpr":       round(float(fpr), 4),
            "tpr":       round(float(r), 4),
            "tp": int(tp), "fp": int(fp),
            "tn": int(tn), "fn": int(fn),
        })

    sweep_df = pd.DataFrame(rows)

    # Log the threshold that maximizes F1
    best_row = sweep_df.loc[sweep_df["f1"].idxmax()]
    logger.info(
        "F1-optimal threshold: {:.4f} → F1={:.4f} P={:.4f} R={:.4f}",
        best_row["threshold"],
        best_row["f1"],
        best_row["precision"],
        best_row["recall"],
    )

    return sweep_df


# ─── Comparison table ─────────────────────────────────────────────────────────

def compare_with_baselines(
    our_metrics: dict,
    y_true: np.ndarray,
    y_score: np.ndarray,
    feature_csv: Path = Path("data/output/block_features.csv"),
) -> pd.DataFrame:
    """
    Compare our approach against two simple baselines.

    Baselines:
        1. Threshold-only (no mining): IF score from raw event counts only
           (cluster_outlier_score + E1..E29 counts, NO fp/seq scores)
        2. Rule-based: flag any block containing E9 or E11 as anomaly

    This table is the key "ablation study" for the paper.
    Demonstrates that FP-Growth + PrefixSpan features ADD value to raw IF.
    """
    logger.info("Running baseline comparison (ablation study)...")
    rows = []

    # Our method
    rows.append({
        "method": "LogSense (Full: IF + FP + PrefixSpan + KMeans)",
        **{k: our_metrics[k] for k in ["precision", "recall", "f1_score", "mcc", "auc_pr"]},
    })

    # Baseline 1: IF without mining scores
    try:
        df = pd.read_csv(feature_csv)
        mining_cols = ["fp_rarity_score", "seq_deviation_score"]
        base_cols   = [c for c in df.columns if c != "block_id" and c not in mining_cols]
        X_base      = df[base_cols].values.astype(np.float32)

        from anomaly.isolation_forest import IsolationForestModel, DynamicThreshold
        base_model = IsolationForestModel()
        base_model.fit(X_base)
        base_scores = base_model.score(X_base)
        base_thresh = DynamicThreshold()
        base_thresh.fit(base_scores)

        y_pred_base = base_thresh.predict(base_scores)
        aligned_true = y_true[:len(y_pred_base)]
        rows.append({
            "method": "IF only (no FP/PrefixSpan scores)",
            "precision": round(precision_score(aligned_true, y_pred_base, zero_division=0), 4),
            "recall":    round(recall_score(aligned_true, y_pred_base, zero_division=0), 4),
            "f1_score":  round(f1_score(aligned_true, y_pred_base, zero_division=0), 4),
            "mcc":       round(matthews_corrcoef(aligned_true, y_pred_base), 4),
            "auc_pr":    round(average_precision_score(aligned_true, base_scores), 4),
        })
    except Exception as exc:
        logger.warning("Baseline 1 failed: {}", exc)

    # Baseline 2: Rule-based (E9 or E11 present → anomaly)
    try:
        df = pd.read_csv(feature_csv)
        e9_col  = next((c for c in df.columns if c.startswith("E9")),  None)
        e11_col = next((c for c in df.columns if c.startswith("E11")), None)

        if e9_col and e11_col:
            rule_pred = ((df[e9_col] > 0) | (df[e11_col] > 0)).astype(int).values
            rows.append({
                "method": "Rule-based (E9 or E11 present)",
                "precision": round(precision_score(y_true[:len(rule_pred)], rule_pred, zero_division=0), 4),
                "recall":    round(recall_score(y_true[:len(rule_pred)], rule_pred, zero_division=0), 4),
                "f1_score":  round(f1_score(y_true[:len(rule_pred)], rule_pred, zero_division=0), 4),
                "mcc":       round(matthews_corrcoef(y_true[:len(rule_pred)], rule_pred), 4),
                "auc_pr":    0.0,   # No continuous score for rule-based
            })
    except Exception as exc:
        logger.warning("Baseline 2 failed: {}", exc)

    comparison_df = pd.DataFrame(rows)
    logger.info("\nAblation Study:\n{}", comparison_df.to_string(index=False))

    return comparison_df


# ─── Main evaluation pipeline ─────────────────────────────────────────────────

def run_evaluation(
    scores_path: Path = LOCAL_SCORES_CSV,
    labels_path: Path = DatasetConfig.ANOMALY_LABELS_CSV,
) -> dict:
    """
    Full evaluation pipeline.

    Steps:
        1. Load ground truth + predictions
        2. Align on block_id
        3. Compute core metrics
        4. Threshold sweep
        5. Baseline comparison (ablation)
        6. Save all results

    Returns:
        metrics dict (for API use in dashboard)
    """
    logger.info("=== LogSense AI — Evaluation ===")

    # 1. Load
    truth_df = load_ground_truth(labels_path)
    pred_df  = load_predictions(scores_path)

    # 2. Align
    merged = align_predictions_with_truth(truth_df, pred_df)

    y_true  = merged["true_label"].values
    y_pred  = merged["is_anomaly"].values
    y_score = merged["if_score"].values

    # 3. Core metrics
    metrics = compute_core_metrics(y_true, y_pred, y_score)
    log_metrics(metrics)

    # 4. Threshold sweep
    sweep_df = threshold_sweep(y_true, y_score, n_points=100)
    sweep_df.to_csv(LOCAL_METRICS_CSV, index=False)
    logger.info("Threshold sweep saved: {}", LOCAL_METRICS_CSV)

    # 5. Ablation study
    comparison_df = compare_with_baselines(metrics, y_true, y_score)
    comparison_df.to_csv(
        LOCAL_METRICS_CSV.parent / "ablation_study.csv", index=False
    )

    # 6. Save full metrics
    full_results = {
        "core_metrics":    metrics,
        "best_f1_threshold": float(
            sweep_df.loc[sweep_df["f1"].idxmax(), "threshold"]
        ),
        "pot_threshold":   float(pred_df["threshold"].iloc[0])
                           if "threshold" in pred_df.columns else None,
    }

    LOCAL_METRICS_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_METRICS_JSON.write_text(json.dumps(full_results, indent=2))
    logger.success("Metrics saved: {}", LOCAL_METRICS_JSON)

    return full_results


if __name__ == "__main__":
    results = run_evaluation()
    m = results["core_metrics"]
    print(f"\n{'='*50}")
    print(f"  F1 Score  : {m['f1_score']:.4f}")
    print(f"  Precision : {m['precision']:.4f}")
    print(f"  Recall    : {m['recall']:.4f}")
    print(f"  MCC       : {m['mcc']:.4f}")
    print(f"  AUC-PR    : {m['auc_pr']:.4f}")
    print(f"{'='*50}")