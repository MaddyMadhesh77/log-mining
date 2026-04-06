"""End-to-end processing pipeline."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrate the end-to-end log processing pipeline."""
    
    def __init__(self, stages: List):
        """Initialize pipeline with stages."""
        self.stages = stages
    
    def execute(self, data: List[Dict]) -> List[Dict]:
        """Execute all pipeline stages."""
        logger.info("Starting pipeline execution")
        result = data
        
        for i, stage in enumerate(self.stages):
            logger.info(f"Executing stage {i+1}: {stage.__class__.__name__}")
            try:
                result = stage.execute(result)
            except Exception as e:
                logger.error(f"Error in stage {i+1}: {e}")
                raise
        
        logger.info("Pipeline execution completed")
        return result
