"""Pattern evaluation and scoring."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class PatternEvaluator:
    """Evaluate and score mined patterns."""
    
    @staticmethod
    def evaluate_pattern(pattern: Dict, metrics: Dict = None) -> Dict:
        """Evaluate a single pattern."""
        score = {
            'support': pattern.get('support', 0),
            'confidence': pattern.get('confidence', 0),
            'lift': pattern.get('lift', 1),
        }
        
        overall_score = (
            score['support'] * 0.3 +
            score['confidence'] * 0.5 +
            score['lift'] * 0.2
        )
        
        return {
            'scores': score,
            'overall_score': overall_score,
        }
    
    @staticmethod
    def rank_patterns(patterns: List[Dict]) -> List[Dict]:
        """Rank patterns by quality."""
        evaluated = [
            {**p, 'evaluation': PatternEvaluator.evaluate_pattern(p)}
            for p in patterns
        ]
        
        # Sort by overall score
        evaluated.sort(
            key=lambda x: x['evaluation']['overall_score'],
            reverse=True
        )
        
        return evaluated
