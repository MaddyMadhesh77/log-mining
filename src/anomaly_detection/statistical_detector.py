"""Statistical anomaly detection methods."""

import logging
import numpy as np
from typing import List, Dict

logger = logging.getLogger(__name__)


class StatisticalDetector:
    """Detect anomalies using statistical methods."""
    
    def __init__(self, threshold: float = 3.0):
        """Initialize statistical detector."""
        self.threshold = threshold  # Standard deviations
    
    def detect_zscore(self, data: np.ndarray) -> np.ndarray:
        """Detect anomalies using Z-score method."""
        mean = np.mean(data)
        std = np.std(data)
        
        z_scores = np.abs((data - mean) / std)
        anomalies = z_scores > self.threshold
        
        logger.info(f"Found {np.sum(anomalies)} anomalies using Z-score")
        return anomalies
    
    def detect_iqr(self, data: np.ndarray) -> np.ndarray:
        """Detect anomalies using Interquartile Range (IQR) method."""
        Q1 = np.percentile(data, 25)
        Q3 = np.percentile(data, 75)
        IQR = Q3 - Q1
        
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        anomalies = (data < lower_bound) | (data > upper_bound)
        
        logger.info(f"Found {np.sum(anomalies)} anomalies using IQR")
        return anomalies
