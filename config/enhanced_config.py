"""
Enhanced Configuration Management
Provides comprehensive configuration for the auto-installation system.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class HistoryConfig:
    """Configuration for history management."""
    max_history_rounds: int = 6
    keep_recent_rounds: int = 2
    enable_summarization: bool = True
    save_history_to_file: bool = True
    history_file_prefix: str = "history"


@dataclass
class LoggingConfig:
    """Configuration for logging system."""
    log_directory: str = "logs"
    enable_markdown_logs: bool = True
    log_file_prefix: str = "installation"
    max_log_file_size_mb: int = 50
    compress_old_logs: bool = True


@dataclass
class InstallationConfig:
    """Configuration for installation process."""
    max_installation_steps: int = 30
    enable_code_execution: bool = True
    enable_web_search: bool = True
    search_timeout_seconds: int = 30
    code_execution_timeout_seconds: int = 300


@dataclass
class AIModelConfig:
    """Configuration for AI models."""
    deepseek_api_key: str = ""
    kimi_api_key: str = ""
    default_temperature: float = 0.3
    max_tokens: int = 4000


class EnhancedConfig:
    """
    Enhanced configuration manager for the auto-installation system.
    
    Supports loading from files, environment variables, and provides
    structured configuration objects.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to configuration file (JSON format)
        """
        self.config_file = config_file
        self._load_config()
    
    def _load_config(self):
        """Load configuration from various sources."""
        # Start with default configurations
        self.history = HistoryConfig()
        self.logging = LoggingConfig()
        self.installation = InstallationConfig()
        self.ai_models = AIModelConfig()
        
        # Load from file if specified
        if self.config_file and Path(self.config_file).exists():
            self._load_from_file()
        
        # Override with environment variables
        self._load_from_env()
        
        # Load legacy config for backward compatibility
        self._load_legacy_config()
    
    def _load_from_file(self):
        """Load configuration from JSON file."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Update configurations
            if 'history' in config_data:
                self._update_dataclass(self.history, config_data['history'])
            
            if 'logging' in config_data:
                self._update_dataclass(self.logging, config_data['logging'])
            
            if 'installation' in config_data:
                self._update_dataclass(self.installation, config_data['installation'])
            
            if 'ai_models' in config_data:
                self._update_dataclass(self.ai_models, config_data['ai_models'])
                
        except Exception as e:
            print(f"Warning: Failed to load config file {self.config_file}: {e}")
    
    def _load_from_env(self):
        """Load configuration from environment variables."""
        # AI Model API Keys
        if os.getenv('DEEPSEEK_API_KEY'):
            self.ai_models.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        
        if os.getenv('KIMI_API_KEY'):
            self.ai_models.kimi_api_key = os.getenv('KIMI_API_KEY')
        
        if os.getenv('QWEN_API_KEY_FILE'):
            self.ai_models.qwen_api_key_file = os.getenv('QWEN_API_KEY_FILE')
        
        # Installation settings
        if os.getenv('MAX_INSTALLATION_STEPS'):
            try:
                self.installation.max_installation_steps = int(os.getenv('MAX_INSTALLATION_STEPS'))
            except ValueError:
                pass
        
        # Logging settings
        if os.getenv('LOG_DIRECTORY'):
            self.logging.log_directory = os.getenv('LOG_DIRECTORY')
    
    def _load_legacy_config(self):
        """Load legacy configuration for backward compatibility."""
        try:
            from src.config.config import config as legacy_config
            
            if 'deepseek_api_key' in legacy_config:
                self.ai_models.deepseek_api_key = legacy_config['deepseek_api_key']
            
            if 'kimi_api_key' in legacy_config:
                self.ai_models.kimi_api_key = legacy_config['kimi_api_key']
                
        except ImportError:
            pass  # Legacy config not available
    
    def _update_dataclass(self, dataclass_instance, update_dict: Dict[str, Any]):
        """Update dataclass instance with dictionary values."""
        for key, value in update_dict.items():
            if hasattr(dataclass_instance, key):
                setattr(dataclass_instance, key, value)
    
    def get_legacy_config_dict(self) -> Dict[str, Any]:
        """
        Get configuration in legacy format for backward compatibility.
        
        Returns:
            Dictionary with legacy configuration format
        """
        return {
            'deepseek_api_key': self.ai_models.deepseek_api_key,
            'kimi_api_key': self.ai_models.kimi_api_key,
            'max_steps': self.installation.max_installation_steps,
            'log_dir': self.logging.log_directory,
            'enable_logging': self.logging.enable_markdown_logs,
            'enable_history': self.history.enable_summarization
        }
    
    def save_to_file(self, filepath: str):
        """
        Save current configuration to file.
        
        Args:
            filepath: Path to save configuration file
        """
        config_data = {
            'history': asdict(self.history),
            'logging': asdict(self.logging),
            'installation': asdict(self.installation),
            'ai_models': asdict(self.ai_models)
        }
        
        # Create directory if it doesn't exist
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
    
    def validate_config(self) -> Dict[str, list]:
        """
        Validate configuration and return any issues.
        
        Returns:
            Dictionary with validation errors and warnings
        """
        errors = []
        warnings = []
        
        # Validate API keys
        if not self.ai_models.deepseek_api_key:
            errors.append("Deepseek API key is required")
        
        if not self.ai_models.kimi_api_key:
            warnings.append("Kimi API key is not set, search functionality may not work")
        
        # Validate numeric values
        if self.installation.max_installation_steps <= 0:
            errors.append("Max installation steps must be positive")
        
        if self.history.max_history_rounds < self.history.keep_recent_rounds:
            errors.append("Max history rounds must be >= keep recent rounds")
        
        # Validate directories
        try:
            Path(self.logging.log_directory).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create log directory: {e}")
        
        return {
            'errors': errors,
            'warnings': warnings
        }
    
    def print_config_summary(self):
        """Print a summary of current configuration."""
        print("=== Auto-Installer Configuration ===")
        print(f"History Management:")
        print(f"  - Max rounds: {self.history.max_history_rounds}")
        print(f"  - Keep recent: {self.history.keep_recent_rounds}")
        print(f"  - Summarization: {self.history.enable_summarization}")
        
        print(f"\nLogging:")
        print(f"  - Directory: {self.logging.log_directory}")
        print(f"  - Markdown logs: {self.logging.enable_markdown_logs}")
        print(f"  - File prefix: {self.logging.log_file_prefix}")
        
        print(f"\nInstallation:")
        print(f"  - Max steps: {self.installation.max_installation_steps}")
        print(f"  - Code execution: {self.installation.enable_code_execution}")
        print(f"  - Web search: {self.installation.enable_web_search}")
        
        print(f"\nAI Models:")
        print(f"  - Deepseek API: {'✓' if self.ai_models.deepseek_api_key else '✗'}")
        print(f"  - Kimi API: {'✓' if self.ai_models.kimi_api_key else '✗'}")
        print(f"  - Qwen key file: {self.ai_models.qwen_api_key_file}")
        
        # Show validation results
        validation = self.validate_config()
        if validation['errors']:
            print(f"\n❌ Configuration Errors:")
            for error in validation['errors']:
                print(f"  - {error}")
        
        if validation['warnings']:
            print(f"\n⚠️ Configuration Warnings:")
            for warning in validation['warnings']:
                print(f"  - {warning}")
        
        if not validation['errors'] and not validation['warnings']:
            print(f"\n✅ Configuration is valid")
