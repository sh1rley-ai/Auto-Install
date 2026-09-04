"""
Core module for automated software installation.

This module provides the main components for the DeployBot installation system:
- HistoryManager: Manages conversation history with intelligent summarization
- InstallationLogger: Generates detailed markdown logs
- DeployBot: Main orchestrator for the installation process
"""

from .history_manager import HistoryManager
from .logger import InstallationLogger
from .installer import DeployBot

__all__ = ['HistoryManager', 'InstallationLogger', 'DeployBot']