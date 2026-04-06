"""Flask/Streamlit dashboard."""

import logging

logger = logging.getLogger(__name__)


class Dashboard:
    """Web dashboard for log analysis."""
    
    def __init__(self, framework: str = 'streamlit'):
        """Initialize dashboard."""
        self.framework = framework
    
    def start(self):
        """Start the dashboard."""
        logger.info(f"Starting {self.framework} dashboard")
    
    def add_metric(self, name: str, value):
        """Add a metric to the dashboard."""
        logger.debug(f"Added metric: {name} = {value}")
    
    def add_chart(self, title: str, data):
        """Add a chart to the dashboard."""
        logger.debug(f"Added chart: {title}")
