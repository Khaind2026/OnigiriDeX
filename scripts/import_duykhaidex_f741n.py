#!/usr/bin/env python3
"""Safely import Korean F741N/F956N Odin archives from the user's shared folder.

Supports reruns after an interrupted or successful import. An existing model
import is NEVER overwritten: its version, symlink targets, expected file list
and Odin MD5 checksums are verified before skipping it. Mismatches stop safely.
Only symlinks and .downloaded metadata are created in out/odin/. No flashing.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

from import_fw import ROOT, verify_odin_package
from import_fw_dir import import_directory
from preflight_f741n import EXPECTED, ODIN_ROLES, inventory, list_filenames

MODELS = ("SM-F741N", "SM-F956N")


def model_spec(model):
    return {
        "model": model,
        "csc": "SKC",  # Carrier region; actual Odin CSC archive uses OKR.
        "version": "/".join(EXPECTED[model][role] for role in ("AP", "CSC", "CP")),
    }


def verify_existing_import(output, folder, report, spec):
    """Check the directory is an exact import of the expected source archives.

    Refuse unknown files, modified metadata and wrong/dangling symlinks.
    Never delete or replace any file. Verify each Odin MD5 even when resuming.
    """
    if output.is_symlink() or not output.is_dir():
        raise ValueError(f"Cannot safely reuse non-directory/symlink import: {output}")

    selected_names = [report["packages"][role][0] for role in ODIN_ROLES]
    expected_names = set(selected_names) | {".downloaded"}
    actual_names = {entry.name for entry in output.iterdir()}
    if actual_names != expected_names:
        raise ValueError(
            f"Existing import has unexpected/missing files: {output}. "
            f"Expected {sorted(expected_names)}, found {sorted(actual_names)}. "
            "No files were changed."
        )

    version_file = output / ".downloaded"
    if not version_file.is_file() or version_file.is_symlink() or version_file.read_text() != spec["version"]:
        raise ValueError(f"Existing import version marker differs: {version_file}. No files were changed.")

    for name in selected_names:
        linked = output / name
        expected_source = (folder / name).resolve(strict=True)
        if not linked.is_symlink() or linked.resolve(strict=True) != expected_source:
            raise ValueError(f"Existing import points to a different file: {linked}. No files were changed.")
        print(f"Rechecking Odin MD5: {name}", flush=True)
        verify_odin_package(linked)
    print(f"Verified existing import (skipped): {output}", flush=True)


def import_both(folder, output_root):
    if not folder.is_dir():
        raise ValueError(f"Not a firmware directory: {folder}")
    files = list_filenames(folder)
    selected = {model: inventory(files, model, folder) for model in MODELS}
    for model, report in selected.items():
        if report["errors"]:
            raise ValueError(f"{model} firmware inventory failed: {'; '.join(report['errors'])}")

    output_root.mkdir(parents=True, exist_ok=True)
    # Verify *all* existing model folders before doing any new writes. A bad
    # folder should never cause partial changes to the other model.
    for model in MODELS:
        output = output_root / f"{model}_SKC"
        if output.exists() or output.is_symlink():
            verify_existing_import(output, folder, selected[model], model_spec(model))

    for model in MODELS:
        output = output_root / f"{model}_SKC"
        if output.exists() or output.is_symlink():
            continue
        report = selected[model]
        # import_directory takes one model at a time. Stage links to original
        # source files, not large copied firmware archives.
        with tempfile.TemporaryDirectory(prefix=f".{model}-", dir=output_root) as staging:
            stage_path = Path(staging)
            for role in ODIN_ROLES:
                name = report["packages"][role][0]
                source = (folder / name).resolve(strict=True)
                os.symlink(source, stage_path / name)
            import_directory(stage_path, model_spec(model), output)
    print("F741N/F956N Odin imports verified. No ROM built or flashed.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True, help="Shared firmware folder containing F741N and F956N")
    parser.add_argument("--output", type=Path, default=ROOT / "out/odin", help="Local Odin import directory")
    args = parser.parse_args(argv)
    try:
        import_both(args.folder, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
