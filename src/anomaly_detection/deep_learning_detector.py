"""Deep Learning-based anomaly detection (LSTM/RNN)."""

import logging
import numpy as np
from typing import List, Dict

logger = logging.getLogger(__name__)


class DeepLearningDetector:
    """LSTM/RNN-based deep learning anomaly detector."""
    
    def __init__(self, model_path: str = None, sequence_length: int = 50):
        """Initialize deep learning detector."""
        self.model = None
        self.model_path = model_path
        self.sequence_length = sequence_length
        
        if model_path:
            self.load_model(model_path)
    
    def load_model(self, model_path: str):
        """Load trained LSTM/RNN model."""
        try:
            from tensorflow.keras.models import load_model
            self.model = load_model(model_path)
            logger.info(f"Loaded deep learning model from {model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
    
    def prepare_sequences(self, data: np.ndarray) -> np.ndarray:
        """Prepare sequences for LSTM input."""
        sequences = []
        for i in range(len(data) - self.sequence_length):
            sequences.append(data[i:i + self.sequence_length])
        
        return np.array(sequences)
    
    def detect(self, data: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Detect anomalies using deep learning model."""
        if self.model is None:
            logger.error("Model not loaded")
            return np.array([])
        
        try:
            sequences = self.prepare_sequences(data)
            predictions = self.model.predict(sequences)
            anomalies = predictions > threshold
            
            logger.info(f"Found {np.sum(anomalies)} anomalies using deep learning")
            return anomalies
        except Exception as e:
            logger.error(f"Error during prediction: {e}")
            return np.array([])
