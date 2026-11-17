#!/usr/bin/env python3
"""Read-only Odin firmware inventory for DuyKhaiDeX SM-F741N + SM-F956N.

Supports a shared folder containing files for BOTH models (as seen on Windows).
It checks package names and expected build identifiers, not image compatibility.
It does not extract, patch, hash, flash, or build firmware.
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile

EXPECTED = {
    "SM-F741N": {
        "AP": "F741NKSS2BYGB",
        "BL": "F741NKSS2BYGB",
        "CP": "F741NKSU2BYCG",
        "CSC": "F741NOKR2BYGB",
    },
    "SM-F956N": {
        "AP": "F956NKSS2BYGB",
        "BL": "F956NKSS2BYGB",
        "CP": "F956NKSU2BYCG",
        "CSC": "F956NOKR2BYGB",
    },
}
ODIN_ROLES = ("AP", "BL", "CP", "CSC")


def list_filenames(path):
    """List *names*, never read the large Odin payloads."""
    if path.is_dir():
        return sorted(f.name for f in path.iterdir() if f.is_file())
    if path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return sorted(Path(f.filename).name for f in archive.infolist() if not f.is_dir())
    raise ValueError(f"Firmware input is not a directory or ZIP: {path}")


def inventory(files, model, location):
    model_part = model.replace("SM-", "")
    packages = {}
    errors, warnings = [], []
    for role in ODIN_ROLES:
        # A mixed F741N/F956N folder is fine; filter EACH role by model.
        candidates = [
            name for name in files
            if name.upper().startswith(role + "_")
            and name.lower().endswith((".tar.md5", ".tar"))
            and model_part in name.upper()
        ]
        packages[role] = candidates
        if len(candidates) != 1:
            errors.append(f"{model}: expected one {role} archive, found {len(candidates)}")
        for name in candidates:
            if EXPECTED[model][role] not in name.upper():
                errors.append(
                    f"{model} {role}: expected {EXPECTED[model][role]} in filename: {name}"
                )

    other = [
        name for name in files
        if name.upper().startswith(("HOME_CSC_", "USERDATA_"))
        and model_part in name.upper()
    ]
    warnings.append(
        "Names only: MD5, binary revision on the phone, Android build, AVB, "
        "VINTF, partition layout and boot compatibility NOT verified"
    )
    return {
        "model": model, "source": str(location), "expected": EXPECTED[model],
        "packages": packages, "other_packages": other,
        "errors": errors, "warnings": warnings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flip6", type=Path, required=True, help="F741N firmware ZIP or folder")
    parser.add_argument("--fold6", type=Path, required=True, help="F956N firmware ZIP or folder")
    args = parser.parse_args(argv)
    try:
        # A single shared directory may be provided for both arguments.
        files_flip = list_filenames(args.flip6)
        files_fold = files_flip if args.flip6.resolve() == args.fold6.resolve() else list_filenames(args.fold6)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))

    target = inventory(files_flip, "SM-F741N", args.flip6)
    donor = inventory(files_fold, "SM-F956N", args.fold6)
    errors = target["errors"] + donor["errors"]
    print(json.dumps({
        "status": "inventory_passed_not_buildable" if not errors else "inventory_failed",
        "hardware_target": target, "system_donor": donor,
        "errors": errors,
        "next_step": (
            "Inspect actual target phone bootloader + firmware metadata; "
            "extract matching images separately; do not flash Fold6 partitions to Flip6."
        ),
    }, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
