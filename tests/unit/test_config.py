import json
import sys

import pytest

from config.enhanced_config import EnhancedConfig

ENV_VARS = ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "KIMI_API_KEY", "MAX_INVESTIGATION_STEPS", "LOG_DIRECTORY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # validate_config creates the log directory


def test_ai_model_config_has_no_kimi_field():
    config = EnhancedConfig()
    assert not hasattr(config.ai_models, "kimi_api_key")
    assert "kimi_api_key" not in config.get_legacy_config_dict()


def test_environment_variables_map_to_api_keys(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qw-key")
    monkeypatch.setenv("KIMI_API_KEY", "ignored")

    config = EnhancedConfig()

    assert config.ai_models.deepseek_api_key == "ds-key"
    assert config.ai_models.qwen_api_key == "qw-key"
    assert config.get_legacy_config_dict()["qwen_api_key"] == "qw-key"


def test_file_loads_investigation_section_and_env_overrides_file(tmp_path, monkeypatch):
    config_file = tmp_path / "user_config.json"
    config_file.write_text(json.dumps({
        "ai_models": {"deepseek_api_key": "from-file", "kimi_api_key": "legacy"},
        "investigation": {"max_investigation_steps": 12, "max_replans": 5},
    }), encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")

    config = EnhancedConfig(str(config_file))

    assert config.ai_models.deepseek_api_key == "from-env"
    assert config.investigation.max_investigation_steps == 12
    assert config.investigation.max_replans == 5
    assert not hasattr(config.ai_models, "kimi_api_key")


def test_missing_deepseek_key_is_error_and_missing_qwen_key_is_warning():
    validation = EnhancedConfig().validate_config()

    assert "Deepseek API key is required" in validation["errors"]
    assert any("Qwen" in warning for warning in validation["warnings"])


def test_print_config_summary_does_not_crash_or_leak_key_values(monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-very-secret")

    EnhancedConfig().print_config_summary()

    output = capsys.readouterr().out
    assert "Deepseek API key: set" in output
    assert "Qwen API key: not set" in output
    assert "sk-very-secret" not in output
    assert "Kimi" not in output


def test_main_show_config_runs(monkeypatch, tmp_path, capsys):
    import main

    monkeypatch.setattr(main, "enhanced_config", EnhancedConfig(str(tmp_path / "absent.json")))
    monkeypatch.setattr(sys, "argv", ["main.py", "--show-config"])

    main.main()

    assert "AML-Guard Configuration" in capsys.readouterr().out
