"""Extract log templates from parsed logs."""

import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


class TemplateExtractor:
    """Extract templates and patterns from parsed logs."""
    
    def extract_templates(self, logs: List[Dict]) -> Dict[str, int]:
        """
        Extract unique templates and their frequencies.
        
        Args:
            logs: List of parsed log entries
            
        Returns:
            Dictionary mapping templates to frequencies
        """
        templates = {}
        
        for log in logs:
            message = log.get('message', '')
            template = self._extract_template(message)
            templates[template] = templates.get(template, 0) + 1
        
        return templates
    
    @staticmethod
    def _extract_template(message: str) -> str:
        """Extract template from a message by replacing values."""
        # Simple implementation - replace numbers and hex values with wildcards
        template = message
        template = re.sub(r'\d+', '<*>', template)
        template = re.sub(r'0x[0-9a-f]+', '<*>', template, flags=re.IGNORECASE)
        return template

import re
