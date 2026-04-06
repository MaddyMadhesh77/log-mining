"""Tests for anomaly detection modules."""

import unittest
import numpy as np
from src.anomaly_detection.statistical_detector import StatisticalDetector


class TestAnomalyDetection(unittest.TestCase):
    """Test anomaly detection module."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.detector = StatisticalDetector(threshold=2.0)
    
    def test_zscore_detection(self):
        """Test Z-score anomaly detection."""
        data = np.array([1, 2, 3, 4, 5, 100])  # 100 is an outlier
        anomalies = self.detector.detect_zscore(data)
        
        self.assertTrue(anomalies[-1])  # Last element should be detected as anomaly
    
    def test_iqr_detection(self):
        """Test IQR-based anomaly detection."""
        data = np.array([1, 2, 3, 4, 5, 100])
        anomalies = self.detector.detect_iqr(data)
        
        self.assertEqual(len(anomalies), len(data))


if __name__ == '__main__':
    unittest.main()
