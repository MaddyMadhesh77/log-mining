"""Chart generation using Matplotlib/Plotly."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generate charts for log analysis."""
    
    @staticmethod
    def plot_line_chart(data: Dict, title: str = ''):
        """Generate a line chart."""
        try:
            import matplotlib.pyplot as plt
            
            plt.figure(figsize=(10, 6))
            for label, values in data.items():
                plt.plot(values, label=label)
            
            plt.title(title)
            plt.legend()
            plt.tight_layout()
            
            logger.info(f"Generated line chart: {title}")
        except Exception as e:
            logger.error(f"Failed to generate chart: {e}")
    
    @staticmethod
    def plot_bar_chart(data: Dict, title: str = ''):
        """Generate a bar chart."""
        try:
            import matplotlib.pyplot as plt
            
            plt.figure(figsize=(10, 6))
            plt.bar(data.keys(), data.values())
            
            plt.title(title)
            plt.tight_layout()
            
            logger.info(f"Generated bar chart: {title}")
        except Exception as e:
            logger.error(f"Failed to generate chart: {e}")
