#!/usr/bin/env python3
"""Read-only preflight inventory for SM-F741N target and SM-F956B donor firmware.

This is NOT a ROM builder or a compatibility proof.
Accepts unpacked Odin firmware directories or ZIP archives that contain Odin files.
Never extracts, modifies, or flashes any image.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import zipfile

ODIN_KINDS = ("AP", "BL", "CP", "CSC")
MODEL_RE = re.compile(r"(?<![A-Z0-9])(F741N|F956B)(?![A-Z0-9])", re.I)


def list_filenames(location: Path):
    if location.is_dir():
        return [p.name for p in location.iterdir() if p.is_file()]
    if location.is_file() and zipfile.is_zipfile(location):
        with zipfile.ZipFile(location) as zf:
            return [Path(info.filename).name for info in zf.infolist() if not info.is_dir()]
    raise ValueError(f"Expected firmware directory or ZIP: {location}")


def inventory(location: Path, model: str):
    names = list_filenames(location)
    found = {}
    warnings = []
    for kind in ODIN_KINDS:
        # HOME_CSC is not interchangeable with CSC for initial wipes.
        candidates = sorted(
            n for n in names
            if n.upper().startswith(kind + "_")
            and n.lower().endswith((".tar.md5", ".tar"))
        )
        found[kind] = candidates
        if not candidates:
            warnings.append(f"Missing {kind} Odin package")
        if len(candidates) > 1:
            warnings.append(f"Multiple {kind} packages: select/verify one manually")
        for filename in candidates:
            if model.upper().replace("SM-", "") not in filename.upper():
                warnings.append(f"{kind} filename does not contain {model}: {filename}")
    related = sorted(n for n in names if n.upper().startswith(("HOME_CSC_", "USERDATA_")))
    if not found["AP"]:
        warnings.append("Cannot continue build without target/donor AP")
    warnings.append("Filename inspection does not verify hashes, Android 15, bootloader revision, partition layout, VINTF, or image compatibility")
    return {"model": model, "location": str(location), "packages": found,
            "other_packages": related, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flip6", type=Path, required=True, help="SM-F741N stock firmware folder or ZIP")
    parser.add_argument("--fold6", type=Path, required=True, help="SM-F956B One UI 7 donor firmware folder or ZIP")
    args = parser.parse_args()
    try:
        result = {
            "status": "inventory_only_not_buildable",
            "hardware_target": inventory(args.flip6, "SM-F741N"),
            "system_donor": inventory(args.fold6, "SM-F956B"),
            "next_step": "Verify firmware signatures/hashes and real target metadata; do not flash donor hardware partitions.",
        }
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if any(not item["packages"][kind] for item in (result["hardware_target"], result["system_donor"]) for kind in ODIN_KINDS):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
