import tomllib
from pathlib import Path

import aiva_collector
from aiva_collector.config import CollectorConfig
from aiva_collector.version import (
    INSTALLER_FILENAME,
    INSTALLER_MANIFEST_FILENAME,
    MANUAL_ZIP_FILENAME,
    PUBLIC_VERSION,
    RELEASE_TAG,
    VERSION,
    release_metadata,
)


def test_rc3_version_and_release_names_have_one_canonical_source():
    assert VERSION == "0.2.7rc3"
    assert aiva_collector.__version__ == VERSION
    assert PUBLIC_VERSION == "0.2.7-desktop-rc3"
    assert INSTALLER_FILENAME == "AIVA-Collector-Setup-v0.2.7-desktop-rc3.exe"
    assert INSTALLER_MANIFEST_FILENAME == "AIVA-Collector-Installer-v0.2.7rc3.manifest.json"
    assert MANUAL_ZIP_FILENAME == "aiva-collector-windows-manual-v0.2.7-desktop-rc3.zip"
    assert RELEASE_TAG == "v0.2.7-collector-desktop-rc3"
    assert release_metadata()["package_version"] == VERSION


def test_pyproject_derives_distribution_version_from_canonical_module():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert "version" not in pyproject["project"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "aiva_collector.version.VERSION"
    }


def test_runtime_version_does_not_regress_when_upgrade_preserves_legacy_config(tmp_path):
    config = CollectorConfig(
        raw={"collector_version": "0.2.7rc1"},
        config_path=tmp_path / "config.windows.json",
    )
    assert config.raw["collector_version"] == "0.2.7rc1"
    assert config.collector_version == VERSION
