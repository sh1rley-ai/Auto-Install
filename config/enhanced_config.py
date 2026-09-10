"""
Enhanced Configuration Management
Provides structured configuration for the AML-Guard investigation system.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class HistoryConfig:
    """Configuration for short-term memory (history summarization)."""
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
class InvestigationConfig:
    """Configuration for the investigation loop."""
    max_investigation_steps: int = 30
    max_step_retries: int = 2
    max_replans: int = 3
    tool_timeout_seconds: int = 60


@dataclass
class AIModelConfig:
    """Configuration for AI models."""
    deepseek_api_key: str = ""
    qwen_api_key: str = ""
    default_temperature: float = 0.3
    max_tokens: int = 4000


class EnhancedConfig:
    """
    Configuration manager for AML-Guard.

    Priority (low to high): dataclass defaults < JSON config file < environment variables.
    API keys are never hardcoded; they come only from the config file or environment.
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
        self.investigation = InvestigationConfig()
        self.ai_models = AIModelConfig()

        # Load from file if specified
        if self.config_file and Path(self.config_file).exists():
            self._load_from_file()

        # Override with environment variables
        self._load_from_env()

    def _load_from_file(self):
        """Load configuration from JSON file."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            sections = {
                'history': self.history,
                'logging': self.logging,
                'investigation': self.investigation,
                'ai_models': self.ai_models,
            }
            for name, instance in sections.items():
                if name in config_data:
                    self._update_dataclass(instance, config_data[name])

        except Exception as e:
            print(f"Warning: Failed to load config file {self.config_file}: {e}")

    def _load_from_env(self):
        """Load configuration from environment variables."""
        # AI Model API Keys
        if os.getenv('DEEPSEEK_API_KEY'):
            self.ai_models.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')

        if os.getenv('DASHSCOPE_API_KEY'):
            self.ai_models.qwen_api_key = os.getenv('DASHSCOPE_API_KEY')

        # Investigation settings
        if os.getenv('MAX_INVESTIGATION_STEPS'):
            try:
                self.investigation.max_investigation_steps = int(os.getenv('MAX_INVESTIGATION_STEPS'))
            except ValueError:
                pass

        # Logging settings
        if os.getenv('LOG_DIRECTORY'):
            self.logging.log_directory = os.getenv('LOG_DIRECTORY')

    def _update_dataclass(self, dataclass_instance, update_dict: Dict[str, Any]):
        """Update dataclass instance with dictionary values."""
        for key, value in update_dict.items():
            if hasattr(dataclass_instance, key):
                setattr(dataclass_instance, key, value)

    def get_legacy_config_dict(self) -> Dict[str, Any]:
        """
        Get configuration as the flat dict consumed by core.installer.

        Returns:
            Dictionary with flat configuration keys
        """
        return {
            'deepseek_api_key': self.ai_models.deepseek_api_key,
            'qwen_api_key': self.ai_models.qwen_api_key,
            'max_steps': self.investigation.max_investigation_steps,
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
            'investigation': asdict(self.investigation),
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

        if not self.ai_models.qwen_api_key:
            warnings.append("Qwen API key is not set, summarization and memory distillation will be unavailable")

        # Validate numeric values
        if self.investigation.max_investigation_steps <= 0:
            errors.append("Max investigation steps must be positive")

        if self.investigation.max_step_retries < 0:
            errors.append("Max step retries must be >= 0")

        if self.investigation.max_replans < 0:
            errors.append("Max replans must be >= 0")

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
        """Print a summary of current configuration (never prints key values)."""
        print("=== AML-Guard Configuration ===")
        print("History Management:")
        print(f"  - Max rounds: {self.history.max_history_rounds}")
        print(f"  - Keep recent: {self.history.keep_recent_rounds}")
        print(f"  - Summarization: {self.history.enable_summarization}")

        print("\nLogging:")
        print(f"  - Directory: {self.logging.log_directory}")
        print(f"  - Markdown logs: {self.logging.enable_markdown_logs}")

        print("\nInvestigation:")
        print(f"  - Max steps: {self.investigation.max_investigation_steps}")
        print(f"  - Max step retries: {self.investigation.max_step_retries}")
        print(f"  - Max replans: {self.investigation.max_replans}")
        print(f"  - Tool timeout (s): {self.investigation.tool_timeout_seconds}")

        print("\nAI Models:")
        print(f"  - Deepseek API key: {'set' if self.ai_models.deepseek_api_key else 'not set'}")
        print(f"  - Qwen API key: {'set' if self.ai_models.qwen_api_key else 'not set'}")

        # Show validation results
        validation = self.validate_config()
        if validation['errors']:
            print("\nConfiguration Errors:")
            for error in validation['errors']:
                print(f"  - {error}")

        if validation['warnings']:
            print("\nConfiguration Warnings:")
            for warning in validation['warnings']:
                print(f"  - {warning}")

        if not validation['errors'] and not validation['warnings']:
            print("\nConfiguration is valid")
