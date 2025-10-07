"""
Core module for automated software installation.

This module provides the main components for the auto-installation system:
- HistoryManager: Manages conversation history with intelligent summarization
- InstallationLogger: Generates detailed markdown logs
- AutoInstaller: Main orchestrator for the installation process
"""

from .history_manager import HistoryManager
from .logger import InstallationLogger
from .installer import AutoInstaller

__all__ = ['HistoryManager', 'InstallationLogger', 'AutoInstaller']