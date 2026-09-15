from __future__ import annotations

import re


VERSION = "0.2.7rc4"
PRODUCT_CHANNEL = "desktop"


def public_version(version: str = VERSION) -> str:
    match = re.fullmatch(r"(?P<base>\d+\.\d+\.\d+)rc(?P<candidate>\d+)", version)
    if not match:
        return version
    return f"{match.group('base')}-{PRODUCT_CHANNEL}-rc{match.group('candidate')}"


PUBLIC_VERSION = public_version()
RELEASE_TAG = f"v{PUBLIC_VERSION.replace('-desktop-', '-collector-desktop-', 1)}"
RELEASE_TITLE = f"AIVA Collector Desktop RC{VERSION.rsplit('rc', maxsplit=1)[1]}"
INSTALLER_FILENAME = f"AIVA-Collector-Setup-v{PUBLIC_VERSION}.exe"
INSTALLER_MANIFEST_FILENAME = f"AIVA-Collector-Installer-v{VERSION}.manifest.json"
MANUAL_ZIP_FILENAME = f"aiva-collector-windows-manual-v{PUBLIC_VERSION}.zip"
MANUAL_MANIFEST_FILENAME = f"aiva-collector-windows-manual-v{PUBLIC_VERSION}.manifest.json"
DIAGNOSTIC_FILENAME = f"aiva-collector-diagnostico-v{VERSION}.zip"


def release_metadata() -> dict[str, str]:
    return {
        "package_version": VERSION,
        "public_version": PUBLIC_VERSION,
        "release_tag": RELEASE_TAG,
        "release_title": RELEASE_TITLE,
        "installer_filename": INSTALLER_FILENAME,
        "installer_manifest_filename": INSTALLER_MANIFEST_FILENAME,
        "manual_zip_filename": MANUAL_ZIP_FILENAME,
        "manual_manifest_filename": MANUAL_MANIFEST_FILENAME,
    }
