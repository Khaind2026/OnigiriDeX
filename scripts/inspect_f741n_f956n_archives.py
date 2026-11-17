#!/usr/bin/env python3
"""Read-only AP/BL archive inventory for DuyKhaiDeX Flip6/Fold6 port.

Uses already checksum-verified Odin imports from out/odin/SM-F741N_SKC and
out/odin/SM-F956N_SKC. Reads TAR headers only, never extracts or flashes files.
Writes a local JSON report to out/reports/f741n-f956n-odin-layout.json.
"""
import argparse
import json
from pathlib import Path
import tarfile

MODELS = {
    "SM-F741N": {"role": "hardware_target", "build": "F741NKSS2BYGB"},
    "SM-F956N": {"role": "system_donor", "build": "F956NKSS2BYGB"},
}
ARCHIVE_ROLES = ("AP", "BL")
MAX_ENTRIES = 4096


def locate_archive(folder: Path, model: str, role: str) -> Path:
    build = MODELS[model]["build"]
    candidates = sorted(
        item for item in folder.iterdir()
        if item.name.upper().startswith(role + "_" + build)
        and item.name.lower().endswith(".tar.md5")
        and item.is_file()
    )
    if len(candidates) != 1:
        raise ValueError(
            f"{model}: expected one {role} archive for {build}, found {len(candidates)} "
            f"in {folder}"
        )
    return candidates[0]


def list_tar_headers(archive: Path) -> list[dict]:
    entries = []
    # r: is a random-access TAR reader. It seeks over image payloads rather
    # than extracting them; the Odin MD5 footer was validated at import time.
    with tarfile.open(archive, mode="r:") as stream:
        for item in stream:
            if not item.isfile():
                continue
            if len(entries) >= MAX_ENTRIES:
                raise ValueError(f"Too many TAR entries in {archive.name}")
            entries.append({"name": item.name, "bytes": item.size})
    return entries


def analyze_model(odin_root: Path, model: str) -> dict:
    source = odin_root / (model + "_SKC")
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"Missing or invalid imported firmware directory: {source}")
    result = {"model": model, **MODELS[model], "archives": {}}
    for role in ARCHIVE_ROLES:
        archive = locate_archive(source, model, role)
        items = list_tar_headers(archive)
        names = {Path(item["name"]).name.removesuffix(".lz4") for item in items}
        result["archives"][role] = {
            "filename": archive.name,
            "members": items,
            "member_count": len(items),
        }
        if role == "AP":
            result["ap_image_layout"] = (
                "super" if "super.img" in names
                else "separate_partition_images"
                if "system.img" in names or "vendor.img" in names
                else "unknown"
            )
            result["ap_image_members"] = sorted(n for n in names if n.endswith(".img"))
    return result


def run(odin_root: Path) -> dict:
    return {
        "status": "tar_headers_only_no_partition_extraction",
        "devices": [analyze_model(odin_root, model) for model in MODELS],
        "notes": [
            "This does not validate framework/vendor compatibility or phone bootloader.",
            "Never flash Fold6 BL, CP, vendor, boot, vbmeta or DTBO to Flip6.",
            "Actual super geometry still requires extracting a matching target super image and inspecting its metadata.",
        ],
    }


def main(argv=None):
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odin-root", type=Path, default=repo_root / "out/odin")
    parser.add_argument(
        "--output", type=Path,
        default=repo_root / "out/reports/f741n-f956n-odin-layout.json",
    )
    args = parser.parse_args(argv)
    try:
        result = run(args.odin_root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print("DuyKhaiDeX — safe AP/BL inventory")
    for device in result["devices"]:
        print(f" {device['model']} ({device['role']}): AP layout = {device['ap_image_layout']}")
        for role in ARCHIVE_ROLES:
            print(f"   {role}: {device['archives'][role]['member_count']} TAR entries")
        print("   AP images: " + ", ".join(device["ap_image_members"]))
    print(f"Report: {args.output}")
    print("No images extracted, modified, built or flashed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
