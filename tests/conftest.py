"""Pytest configuration and global fixtures."""

from pathlib import Path
try:
    import pytest
except ImportError:
    pytest = None

import hey_whisper.config as config_mod

if pytest is not None:
    @pytest.fixture(autouse=True)
    def isolate_user_config(tmp_path_factory, monkeypatch):
        """Ensure no test can read from or write to the user's actual host configuration files."""
        test_conf_dir = tmp_path_factory.mktemp("test_user_config")
        mock_default = test_conf_dir / "hey-whisper.conf"
        mock_fallback = test_conf_dir / "spoken-notes.conf"

        monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", mock_default)
        monkeypatch.setattr(config_mod, "FALLBACK_CONFIG_PATH", mock_fallback)
        yield
