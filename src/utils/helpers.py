"""Helper functions."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def safe_get(obj: Dict, path: str, default: Any = None) -> Any:
    """
    Safely get nested dictionary values.
    
    Args:
        obj: Dictionary to search
        path: Dot-separated path (e.g., 'config.database.host')
        default: Default value if not found
    
    Returns:
        Value at path or default
    """
    keys = path.split('.')
    current = obj
    
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    
    return current


def merge_dicts(*dicts: Dict) -> Dict:
    """Merge multiple dictionaries."""
    result = {}
    for d in dicts:
        result.update(d)
    return result
