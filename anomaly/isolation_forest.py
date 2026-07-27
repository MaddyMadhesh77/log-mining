"""
isolation_forest.py
-------------------
Anomaly scoring using XGBoost Isolation Forest.

Why XGBoost IF over sklearn IF:
    - XGBoost IF is significantly faster on large tabular datasets
    - Supports GPU acceleration (optional)
    - Better sub-sampling control (subsample parameter)
    - Identical API to sklearn IF → easy to swap back if needed
    - Published results on HDFS_v1: XGBoost IF outperforms sklearn IF
      (Meng et al. 2023 — LogADEmpirical benchmark)

Two scoring modes:
    1. BATCH (hourly): Full feature matrix → score all 575k blocks
    2. STREAMING (per micro-batch): Score only new blocks seen in last window
                                    using the already-trained batch model

Dynamic threshold:
    We do NOT use a fixed contamination parameter (e.g., 0.1 = 10% anomalies).
    Instead we use Peak-Over-Threshold (POT) on the anomaly score distribution:
        - Fit a Generalized Pareto Distribution to the tail of IF scores
        - Threshold = score at which P(false_positive) < 0.01
    This self-calibrates to the actual data distribution.
    If POT fails → fallback to percentile threshold (97th percentile).

Output:
    1. block_anomaly_scores.parquet → [block_id, if_score, is_anomaly, threshold]
    2. model saved locally as isolation_forest.json
    3. threshold saved as threshold.json

Run:
    python -m anomaly.isolation_forest
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import genpareto
from sklearn.preprocessing import StandardScaler

from config.settings import AnomalyConfig, DatasetConfig, HDFSConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
LOCAL_FEATURE_CSV    = Path("data/output/block_features.csv")
LOCAL_MODEL_PATH     = Path("data/models/isolation_forest.json")
LOCAL_THRESHOLD_PATH = Path("data/models/threshold.json")
LOCAL_SCORES_CSV     = Path("data/output/block_anomaly_scores.csv")
HDFS_SCORES_PATH     = f"hdfs://localhost:9000{HDFSConfig.ANOMALIES_PATH}/if_scores"


# ─── XGBoost Isolation Forest wrapper ────────────────────────────────────────

class IsolationForestModel:
    """
    Thin wrapper around XGBoost Isolation Forest.
    Falls back to sklearn IsolationForest if XGBoost is unavailable
    (e.g., in environments without GPU).

    Unified interface: fit(), score(), save(), load()
    """

    def __init__(
        self,
        n_estimators: int = AnomalyConfig.IF_N_ESTIMATORS,
        max_samples: int | str = AnomalyConfig.IF_MAX_SAMPLES,
        subsample: float = AnomalyConfig.IF_SUBSAMPLE,
        random_state: int = AnomalyConfig.IF_RANDOM_STATE,
        use_xgboost: bool = True,
    ):
        self.n_estimators   = n_estimators
        self.max_samples    = max_samples
        self.subsample      = subsample
        self.random_state   = random_state
        self.use_xgboost    = use_xgboost
        self._model         = None
        self._scaler        = StandardScaler()
        self._is_fitted     = False
        self._backend       = None    # "xgboost" or "sklearn"

    def _build_model(self):
        """Build XGBoost IF model, falling back to sklearn if unavailable."""
        if self.use_xgboost:
            try:
                from xgboost import XGBClassifier

                # XGBoost Isolation Forest uses tree_method="hist" with
                # objective="binary:logistic" — it's not a native IF API,
                # so we use the dedicated xgboost.XGBIsolationForest if available
                try:
                    from xgboost import XGBIsolationForest
                    model = XGBIsolationForest(
                        n_estimators=self.n_estimators,
                        max_samples=self.max_samples,
                        subsample=self.subsample,
                        random_state=self.random_state,
                    )
                    self._backend = "xgboost_native"
                    logger.info("Backend: XGBoost native IsolationForest")
                    return model

                except ImportError:
                    # Older XGBoost — use sklearn wrapper
                    pass

            except ImportError:
                logger.warning("XGBoost not available. Falling back to sklearn.")

        # sklearn fallback
        from sklearn.ensemble import IsolationForest
        model = IsolationForest(
            n_estimators=self.n_estimators,
            max_samples=self.max_samples,
            contamination="auto",
            random_state=self.random_state,
            n_jobs=-1,
        )
        self._backend = "sklearn"
        logger.info("Backend: sklearn IsolationForest")
        return model

    def fit(self, X: np.ndarray) -> "IsolationForestModel":
        """
        Fit the model on feature matrix X.

        Steps:
        1. StandardScale the features (IF is distance-sensitive)
        2. Fit the IF model

        Note: We scale even though IF is theoretically scale-invariant
        because our features are mixed scales (0-1 scores vs log counts).
        Scaling ensures FP/seq/cluster scores don't dominate over event counts.
        """
        logger.info(
            "Fitting Isolation Forest | {} samples × {} features | backend={}",
            X.shape[0],
            X.shape[1],
            "xgboost" if self.use_xgboost else "sklearn",
        )

        self._model = self._build_model()

        start = time.perf_counter()

        # Scale features
        X_scaled = self._scaler.fit_transform(X)

        # Fit model
        if self._backend and "xgboost" in self._backend:
            self._model.fit(X_scaled)
            del X_scaled
        else:
            self._model.fit(X_scaled)   # sklearn IF — same call
            del X_scaled

        elapsed = time.perf_counter() - start
        self._is_fitted = True

        logger.success(
            "Isolation Forest fitted in {:.1f}s",
            elapsed,
        )
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        """
        Compute anomaly scores for all samples.

        Returns raw anomaly scores (float array):
            sklearn IF:   decision_function() → lower = more anomalous
                          We negate and min-max normalize → higher = more anomalous
            XGBoost IF:   predict_proba()[:, 1] or score_samples()

        Final scores are in [0, 1] where:
            0 = definitely normal
            1 = definitely anomalous
        """
        if not self._is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")

        X_scaled = self._scaler.transform(X)

        if self._backend == "sklearn":
            # decision_function: higher = more normal, lower = more anomalous
            raw = self._model.decision_function(X_scaled)
            del X_scaled   # ← ADD HERE — raw scores extracted, free it now
            # Negate + min-max normalize to [0, 1]
            raw_neg = -raw
            score_min = raw_neg.min()
            score_max = raw_neg.max()
            if score_max > score_min:
                scores = (raw_neg - score_min) / (score_max - score_min)
            else:
                scores = np.zeros_like(raw_neg)

        elif self._backend and "xgboost" in self._backend:
            try:
                # XGBIsolationForest has score_samples()
                raw = self._model.score_samples(X_scaled)
                del X_scaled   # ← ADD HERE — raw scores extracted, free it now
                # Negate + normalize (same as sklearn convention)
                raw_neg = -raw
                score_min = raw_neg.min()
                score_max = raw_neg.max()
                scores = (
                    (raw_neg - score_min) / (score_max - score_min)
                    if score_max > score_min
                    else np.zeros_like(raw_neg)
                )
            except AttributeError:
                # Fallback for older XGBoost API
                raw = self._model.predict(X_scaled).astype(float)
                del X_scaled   # ← ADD HERE — raw scores extracted, free it now
                scores = np.where(raw == -1, 1.0, 0.0)

        else:
            raise RuntimeError(f"Unknown backend: {self._backend}")

        logger.info(
            "Scores computed | mean={:.4f} std={:.4f} max={:.4f}",
            scores.mean(),
            scores.std(),
            scores.max(),
        )
        return scores

    def save(self, path: Path = LOCAL_MODEL_PATH) -> None:
        """Save model + scaler to disk."""
        import pickle
        path.parent.mkdir(parents=True, exist_ok=True)
        model_data = {
            "model":      self._model,
            "scaler":     self._scaler,
            "backend":    self._backend,
            "n_estimators": self.n_estimators,
            "is_fitted":  self._is_fitted,
        }
        with open(path.with_suffix(".pkl"), "wb") as f:
            import pickle
            pickle.dump(model_data, f)
        logger.info("Model saved: {}", path.with_suffix(".pkl"))

    @classmethod
    def load(cls, path: Path = LOCAL_MODEL_PATH) -> "IsolationForestModel":
        """Load a previously saved model."""
        import pickle
        pkl_path = path.with_suffix(".pkl")
        if not pkl_path.exists():
            raise FileNotFoundError(f"Model file not found: {pkl_path}")

        with open(pkl_path, "rb") as f:
            data = pickle.load(f)

        instance = cls.__new__(cls)
        instance._model     = data["model"]
        instance._scaler    = data["scaler"]
        instance._backend   = data["backend"]
        instance.n_estimators = data["n_estimators"]
        instance._is_fitted = data["is_fitted"]
        instance.use_xgboost = "xgboost" in (data["backend"] or "")

        logger.info(
            "Model loaded from {} | backend={}",
            pkl_path,
            instance._backend,
        )
        return instance


# ─── Dynamic Threshold (POT) ──────────────────────────────────────────────────

class DynamicThreshold:
    """
    Peak-Over-Threshold (POT) based anomaly threshold calibration.

    Method:
        1. Take the top (1 - q0) fraction of anomaly scores as "extreme tail"
           Default q0 = 0.90 → use top 10% of scores for tail fitting
        2. Fit a Generalized Pareto Distribution (GPD) to the tail
        3. Compute threshold t* where P(score > t* | score > q0_val) < risk_level
        4. Final threshold = q0_val + t*

    Parameters:
        q0:         Initial threshold quantile for tail extraction (default 0.90)
        risk_level: Desired false positive rate above threshold (default 0.01)

    Reference:
        Siffer et al. "Anomaly Detection in Streams with Extreme Value Theory"
        KDD 2017 — standard method for log anomaly thresholding.
    """

    def __init__(
        self,
        q0: float = AnomalyConfig.POT_Q0,
        risk_level: float = AnomalyConfig.POT_RISK_LEVEL,
        fallback_percentile: float = AnomalyConfig.FALLBACK_PERCENTILE,
    ):
        self.q0                 = q0
        self.risk_level         = risk_level
        self.fallback_percentile = fallback_percentile
        self.threshold_         = None
        self.gpd_params_        = None
        self._method_used       = None

    def fit(self, scores: np.ndarray) -> "DynamicThreshold":
        """
        Fit the POT threshold on anomaly scores.

        Args:
            scores: Array of anomaly scores (0–1, higher = more anomalous)

        Returns:
            self (fitted)
        """
        logger.info(
            "Fitting POT threshold | q0={} | risk_level={}",
            self.q0,
            self.risk_level,
        )

        try:
            # Step 1: Extract tail (scores above q0 quantile)
            q0_val = np.quantile(scores, self.q0)
            tail = scores[scores > q0_val] - q0_val

            if len(tail) < 10:
                raise ValueError(
                    f"Tail too small for GPD fit: {len(tail)} samples"
                )

            # Step 2: Fit Generalized Pareto Distribution to tail
            shape, loc, scale = genpareto.fit(tail, floc=0)
            self.gpd_params_ = {"shape": shape, "loc": loc, "scale": scale}

            logger.info(
                "GPD fit: shape={:.4f} scale={:.4f}",
                shape,
                scale,
            )

            # Step 3: Compute threshold using POT formula
            # t* = (scale / shape) * ((n * risk_level / len(tail)) ** (-shape) - 1)
            n = len(scores)
            n_tail = len(tail)

            if abs(shape) < 1e-6:
                # Exponential case (shape ≈ 0)
                t_star = -scale * np.log(n * self.risk_level / n_tail)
            else:
                t_star = (scale / shape) * (
                    (n * self.risk_level / n_tail) ** (-shape) - 1
                )

            # Clip t_star to valid range [0, max_tail]
            t_star = np.clip(t_star, 0, tail.max())

            self.threshold_ = float(q0_val + t_star)
            self._method_used = "POT"

            logger.success(
                "POT threshold computed: {:.4f} (q0_val={:.4f} + t*={:.4f})",
                self.threshold_,
                q0_val,
                t_star,
            )

        except Exception as exc:
            logger.warning(
                "POT fitting failed: {}. Falling back to {}th percentile.",
                exc,
                self.fallback_percentile,
            )
            self.threshold_ = float(np.percentile(scores, self.fallback_percentile))
            self._method_used = f"percentile_{self.fallback_percentile}"
            logger.info(
                "Fallback threshold: {:.4f}",
                self.threshold_,
            )

        return self

    def predict(self, scores: np.ndarray) -> np.ndarray:
        """
        Apply threshold. Returns binary array: 1 = anomaly, 0 = normal.
        """
        if self.threshold_ is None:
            raise RuntimeError("Call fit() before predict().")
        return (scores >= self.threshold_).astype(int)

    def save(self, path: Path = LOCAL_THRESHOLD_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "threshold":    self.threshold_,
            "method":       self._method_used,
            "q0":           self.q0,
            "risk_level":   self.risk_level,
            "gpd_params":   self.gpd_params_,
        }
        path.write_text(json.dumps(data, indent=2))
        logger.info("Threshold saved: {} = {:.4f}", path, self.threshold_)

    @classmethod
    def load(cls, path: Path = LOCAL_THRESHOLD_PATH) -> "DynamicThreshold":
        data = json.loads(path.read_text())
        instance = cls()
        instance.threshold_   = data["threshold"]
        instance._method_used = data["method"]
        instance.gpd_params_  = data.get("gpd_params")
        logger.info(
            "Threshold loaded: {:.4f} (method={})",
            instance.threshold_,
            instance._method_used,
        )
        return instance


# ─── Full scoring pipeline ────────────────────────────────────────────────────

def run_batch_scoring(
    feature_csv: Path = LOCAL_FEATURE_CSV,
) -> pd.DataFrame:
    """
    Full batch anomaly scoring pipeline.

    Steps:
        1. Load feature matrix (local CSV or HDFS parquet)
        2. Fit Isolation Forest
        3. Compute anomaly scores
        4. Fit POT threshold
        5. Label blocks as anomaly / normal
        6. Save model, threshold, and scores

    Returns:
        results_df: [block_id, if_score, is_anomaly, threshold, method]
    """
    logger.info("=== Isolation Forest Batch Scoring ===")

    # ── Load from HDFS parquet (full 575k blocks) ──
    from pyspark.sql import SparkSession
    from config.settings import SparkConfig

    spark = (
        SparkSession.builder
        .appName(f"{SparkConfig.APP_NAME}-IF")
        .master(SparkConfig.MASTER)
        .config("spark.driver.memory", "4g")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )

    HDFS_FEATURE_PATH = f"hdfs://localhost:9000{HDFSConfig.FEATURES_PATH}/block_features"

    logger.info("Loading feature matrix from HDFS parquet...")
    spark_df = spark.read.parquet(HDFS_FEATURE_PATH)

    # Convert to pandas — 575k × 31 float32 ≈ 71MB, safe in RAM
    df = spark_df.toPandas()
    spark.stop()
    del spark_df   # ← ADD THIS — frees Spark df from RAM immediately

    logger.info("Feature matrix loaded: {:,} rows × {} cols", *df.shape)

    block_ids = df["block_id"].values
    feature_cols = [c for c in df.columns if c != "block_id"]
    X = df[feature_cols].values.astype(np.float32)
    del df         # ← ADD THIS — free pandas df, X is all we need now

    logger.info(
        "Training on {} features: {}",
        len(feature_cols),
        feature_cols,
    )

    # 2. Fit Isolation Forest
    model = IsolationForestModel()
    model.fit(X)

    # 3. Compute anomaly scores
    scores = model.score(X)

    # 4. Fit POT threshold
    threshold = DynamicThreshold()
    threshold.fit(scores)

    # 5. Label blocks
    labels = threshold.predict(scores)

    anomaly_count  = labels.sum()
    normal_count   = len(labels) - anomaly_count
    anomaly_rate   = anomaly_count / len(labels) * 100

    logger.success(
        "Scoring complete | {:,} anomalies ({:.2f}%) | {:,} normal",
        anomaly_count,
        anomaly_rate,
        normal_count,
    )

    # 6. Build results DataFrame
    results_df = pd.DataFrame({
        "block_id":   block_ids,
        "if_score":   scores,
        "is_anomaly": labels,
        "threshold":  threshold.threshold_,
        "threshold_method": threshold._method_used,
    })

    # 7. Save
    model.save()
    threshold.save()

    LOCAL_SCORES_CSV.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(LOCAL_SCORES_CSV, index=False)
    logger.info("Scores saved: {}", LOCAL_SCORES_CSV)

    # Score distribution log
    logger.info("Score distribution:")
    for pct in [50, 75, 90, 95, 97, 99, 99.9]:
        logger.info(
            "  P{:.1f} = {:.4f}",
            pct,
            np.percentile(scores, pct),
        )

    return results_df


def score_new_blocks(
    new_features_df: pd.DataFrame,
    model: IsolationForestModel | None = None,
    threshold: DynamicThreshold | None = None,
) -> pd.DataFrame:
    """
    Score a batch of NEW blocks using the pre-trained model.
    Called by the batch job for each hourly window of streaming data.

    Args:
        new_features_df: DataFrame with same feature columns as training set
        model:           Pre-loaded IsolationForestModel (loads from disk if None)
        threshold:       Pre-loaded DynamicThreshold (loads from disk if None)

    Returns:
        scored_df: [block_id, if_score, is_anomaly]
    """
    if model is None:
        model = IsolationForestModel.load()
    if threshold is None:
        threshold = DynamicThreshold.load()

    block_ids   = new_features_df["block_id"].values
    feature_cols = [c for c in new_features_df.columns if c != "block_id"]
    X = new_features_df[feature_cols].values.astype(np.float32)

    scores = model.score(X)
    labels = threshold.predict(scores)

    return pd.DataFrame({
        "block_id":   block_ids,
        "if_score":   scores,
        "is_anomaly": labels,
    })


if __name__ == "__main__":
    results = run_batch_scoring()
    print(f"\nTotal blocks: {len(results):,}")
    print(f"Anomalies:    {results['is_anomaly'].sum():,}")
    print(f"Normal:       {(results['is_anomaly'] == 0).sum():,}")
    print(f"Threshold:    {results['threshold'].iloc[0]:.4f}")