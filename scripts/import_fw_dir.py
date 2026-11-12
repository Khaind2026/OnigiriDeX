#!/usr/bin/env python3
"""Import an extracted Samsung firmware directory without re-zipping it.

Use the exact pinned AP, BL, CP, CSC Odin packages. Each package's own MD5
trailer is checked; original ZIP MD5 cannot be checked for folder inputs.
The large files remain on their source disk and are linked into out/odin/.
Keep the source folder accessible until firmware extraction is complete.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

from import_fw import ROOT, verify_odin_package


def import_directory(folder: Path, spec: dict, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Firmware output already exists: {output}")
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    pda, csc, modem = spec["version"].split("/")
    # Same exact version-prefix checks as import_fw.py.
    group = csc[len(spec["model"]) - 3:][:3]
    prefixes = {
        "AP": f"AP_{pda}_",
        "BL": f"BL_{pda}_",
        "CP": f"CP_{modem}_",
        "CSC": f"CSC_{group}_{csc}_",
        "HOME_CSC": f"HOME_CSC_{group}_{csc}_",
    }
    packages = {}
    for path in folder.iterdir():
        if not path.name.endswith(".tar.md5"):
            continue
        if not path.is_file():
            raise ValueError(f"Not a regular file: {path}")
        role = next(
            (name for name, prefix in prefixes.items() if path.name.startswith(prefix)),
            None,
        )
        if role is None:
            raise ValueError(f"Unexpected firmware version or role: {path.name}")
        if role in packages:
            raise ValueError(f"Duplicate {role} Odin package")
        packages[role] = path

    required = ("AP", "BL", "CP", "CSC")
    missing = [role for role in required if role not in packages]
    if missing:
        raise ValueError(f"Missing Odin package(s): {', '.join(missing)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    print(
        "Directory import: validating Odin MD5 for each package. "
        "The original ZIP MD5 cannot be checked.",
        flush=True,
    )
    for role in required:
        source = packages[role].resolve(strict=True)
        print(f"Verifying {role}: {source.name}", flush=True)
        verify_odin_package(source)

    with tempfile.TemporaryDirectory(prefix=".import-", dir=output.parent) as temp:
        staged = Path(temp) / "firmware"
        staged.mkdir()
        for role in required:
            source = packages[role].resolve(strict=True)
            os.symlink(source, staged / source.name)
        (staged / ".downloaded").write_text(spec["version"])
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Firmware output already exists: {output}")
        staged.rename(output)

    print(f"Imported {spec['model']} {spec['version']} from {folder}", flush=True)


def main() -> None:
    config = json.loads((ROOT / "onigiri/configs/firmware.json").read_text())
    specs = {**config["targets"], "donor": config["donor"]}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=specs)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    spec = specs[args.role]
    output = ROOT / "out/odin" / f"{spec['model']}_{spec['csc']}"
    try:
        import_directory(args.directory, spec, output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
