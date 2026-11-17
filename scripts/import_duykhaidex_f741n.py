#!/usr/bin/env python3
"""Import the user's Korean Flip6/Fold6 Odin archives without mixing models.

Accepts a Windows-extracted folder containing both SM-F741N and SM-F956N files.
Runs the existing import_fw_dir.verify_odin_package checksum validation;
creates only local out/odin symlinks and .downloaded metadata (no image edits).
Does NOT make a bootable ROM and must NOT be fed into the b5q builder.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

from import_fw import ROOT
from import_fw_dir import import_directory
from preflight_f741n import EXPECTED, ODIN_ROLES, inventory, list_filenames


def import_both(folder, output_root):
    if not folder.is_dir():
        raise ValueError(f"Not a firmware directory: {folder}")
    files = list_filenames(folder)
    selected = {
        model: inventory(files, model, folder) for model in ("SM-F741N", "SM-F956N")
    }
    for model, result in selected.items():
        if result["errors"]:
            raise ValueError(f"{model} firmware inventory failed: {'; '.join(result['errors'])}")

    # Refuse to overwrite any previously imported files.
    for model in selected:
        output = output_root / f"{model}_SKC"
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Existing import detected: {output}")

    output_root.mkdir(parents=True, exist_ok=True)
    for model, report in selected.items():
        spec = {
            "model": model,
            "csc": "SKC",  # Selected carrier region, Odin CSC package is OKR.
            "version": "/".join(EXPECTED[model][role] for role in ("AP", "CSC", "CP")),
        }
        # Existing importer expects exactly one model's packages per directory.
        # Link only the selected model's files into a disposable staging directory.
        with tempfile.TemporaryDirectory(prefix=f".{model}-", dir=output_root) as staging:
            stage_path = Path(staging)
            for role in ODIN_ROLES:
                name = report["packages"][role][0]
                source = (folder / name).resolve(strict=True)
                os.symlink(source, stage_path / name)
            import_directory(stage_path, spec, output_root / f"{model}_SKC")
    print("Korean Flip6 + Fold6 Odin packages imported. NO ROM built or flashed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True, help="Shared extracted firmware folder")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "out/odin",
        help="Local import destination (default: out/odin)",
    )
    args = parser.parse_args(argv)
    try:
        import_both(args.folder, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
