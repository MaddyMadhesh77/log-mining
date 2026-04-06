"""ML-based anomaly detection."""

import logging
import numpy as np
from typing import List, Dict

logger = logging.getLogger(__name__)


class MLDetector:
    """ML-based anomaly detection using trained model."""
    
    def __init__(self, model_path: str = None):
        """Initialize ML detector."""
        self.model = None
        self.model_path = model_path
        if model_path:
            self.load_model(model_path)
    
    def load_model(self, model_path: str):
        """Load trained model from file."""
        try:
            from tensorflow.keras.models import load_model
            self.model = load_model(model_path)
            logger.info(f"Loaded model from {model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
    
    def detect(self, data: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Detect anomalies using ML model."""
        if self.model is None:
            logger.error("Model not loaded")
            return np.array([])
        
        try:
            predictions = self.model.predict(data)
            anomalies = predictions > threshold
            logger.info(f"Found {np.sum(anomalies)} anomalies using ML model")
            return anomalies
        except Exception as e:
            logger.error(f"Error during prediction: {e}")
            return np.array([])
