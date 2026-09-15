from __future__ import annotations

import re
from pathlib import Path

from aiva_collector.version import PUBLIC_VERSION, VERSION


COMPANY_NAME = "AIVA Comercial"
PRODUCT_NAME = "AIVA Collector"
COPYRIGHT = "Copyright (c) 2026 AIVA Comercial"

EXECUTABLE_METADATA = {
    "aiva-collector.exe": {
        "description": "AIVA Collector Desktop",
        "internal_name": "aiva-collector",
    },
    "aiva-collector-cli.exe": {
        "description": "AIVA Collector CLI",
        "internal_name": "aiva-collector-cli",
    },
    "aiva-collector-background.exe": {
        "description": "AIVA Collector Background",
        "internal_name": "aiva-collector-background",
    },
}


def numeric_version(version: str = VERSION) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)rc(\d+)", version)
    if not match:
        raise ValueError(f"Version Windows no soportada: {version}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def render_version_info(
    filename: str,
    *,
    version: str = VERSION,
    public_version: str = PUBLIC_VERSION,
) -> str:
    metadata = EXECUTABLE_METADATA.get(filename)
    if metadata is None:
        raise ValueError(f"Ejecutable Windows desconocido: {filename}")
    version_tuple = numeric_version(version)
    file_version = ".".join(str(part) for part in version_tuple)
    strings = {
        "CompanyName": COMPANY_NAME,
        "FileDescription": metadata["description"],
        "FileVersion": file_version,
        "InternalName": metadata["internal_name"],
        "LegalCopyright": COPYRIGHT,
        "OriginalFilename": filename,
        "ProductName": PRODUCT_NAME,
        "ProductVersion": public_version,
    }
    string_structs = ",\n".join(
        f"        StringStruct({key!r}, {value!r})" for key, value in strings.items()
    )
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple!r},
    prodvers={version_tuple!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
[
{string_structs}
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_version_info_files(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for filename in EXECUTABLE_METADATA:
        target = output_dir / f"{Path(filename).stem}.version.txt"
        target.write_text(render_version_info(filename), encoding="utf-8")
        result[filename] = target
    return result
