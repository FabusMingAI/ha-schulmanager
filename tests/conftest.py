"""Keep generated HA configuration and files isolated between test cases."""
import pytest


@pytest.fixture(autouse=True)
def isolated_config_directory(hass, tmp_path):
    """Never write into the installed pytest plugin's shared testing_config."""
    hass.config.config_dir = str(tmp_path)
