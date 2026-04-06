"""Ensemble anomaly detection combining multiple methods."""

import logging
import numpy as np
from typing import List, Dict

logger = logging.getLogger(__name__)


class EnsembleDetector:
    """Combine multiple anomaly detection methods."""
    
    def __init__(self, detectors: List):
        """Initialize ensemble with multiple detectors."""
        self.detectors = detectors
    
    def detect(self, data: np.ndarray, voting: str = 'majority') -> np.ndarray:
        """Detect anomalies using ensemble voting."""
        if not self.detectors:
            logger.error("No detectors in ensemble")
            return np.array([])
        
        predictions = []
        for detector in self.detectors:
            try:
                pred = detector.detect(data)
                predictions.append(pred)
            except Exception as e:
                logger.warning(f"Detector failed: {e}")
        
        if not predictions:
            return np.array([])
        
        # Voting
        predictions = np.array(predictions)
        
        if voting == 'majority':
            anomalies = np.sum(predictions, axis=0) > len(predictions) / 2
        elif voting == 'unanimous':
            anomalies = np.all(predictions, axis=0)
        else:
            anomalies = np.any(predictions, axis=0)
        
        logger.info(f"Ensemble found {np.sum(anomalies)} anomalies")
        return anomalies
