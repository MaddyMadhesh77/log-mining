"""Clustering algorithms (K-Means, DBSCAN)."""

import logging
from typing import List, Dict
import numpy as np

logger = logging.getLogger(__name__)


class LogClustering:
    """Cluster logs into groups."""
    
    @staticmethod
    def kmeans_cluster(data: np.ndarray, n_clusters: int = 5) -> np.ndarray:
        """Apply K-Means clustering."""
        try:
            from sklearn.cluster import KMeans
            
            kmeans = KMeans(n_clusters=n_clusters)
            labels = kmeans.fit_predict(data)
            
            logger.info(f"K-Means clustering completed with {n_clusters} clusters")
            return labels
        except Exception as e:
            logger.error(f"Error in K-Means clustering: {e}")
            return None
    
    @staticmethod
    def dbscan_cluster(data: np.ndarray, eps: float = 0.5, min_samples: int = 5) -> np.ndarray:
        """Apply DBSCAN clustering."""
        try:
            from sklearn.cluster import DBSCAN
            
            dbscan = DBSCAN(eps=eps, min_samples=min_samples)
            labels = dbscan.fit_predict(data)
            
            logger.info(f"DBSCAN clustering completed")
            return labels
        except Exception as e:
            logger.error(f"Error in DBSCAN clustering: {e}")
            return None
