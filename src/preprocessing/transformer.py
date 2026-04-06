"""Spark DataFrame transformations."""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class SparkTransformer:
    """Transform data using Spark."""
    
    @staticmethod
    def transform_to_spark_df(spark_session, logs: List[Dict]):
        """Convert logs to Spark DataFrame."""
        try:
            df = spark_session.createDataFrame(logs)
            logger.info(f"Created Spark DataFrame with {df.count()} rows")
            return df
        except Exception as e:
            logger.error(f"Failed to create Spark DataFrame: {e}")
            return None
    
    @staticmethod
    def filter_by_level(df, levels: List[str]):
        """Filter DataFrame by log levels."""
        from pyspark.sql.functions import col
        
        level_filter = col('level').isin(levels)
        return df.filter(level_filter)
    
    @staticmethod
    def group_by_source(df):
        """Group logs by source."""
        return df.groupBy('source').count()
