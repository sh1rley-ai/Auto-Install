"""
Utilities module for automated software installation.

This module provides utility functions and classes for:
- AI model integrations (Deepseek, Qwen, Kimi)
- System information detection
- Code execution helpers
- Text processing utilities
"""
from .deepseek import Deepseek
from .qwen import QueryTongyi
from .kimi_search import KimiSearch
from .get_system_summary import get_system_summary
from .text_processors import TextProcessor

__all__ = [
    'Deepseek', 
    'QueryTongyi', 
    'KimiSearch', 
    'get_system_summary',
    'TextProcessor'
]