#!/usr/bin/env python3
"""Verify staged F741N/F956N partition images before DuyKhaiDeX framework work.

Read-only checks: model/source mapping, manifest, expected image names and
byte lengths from verified LP metadata, plus filesystem signatures.
Optional --sha256 hashes all images for reproducible research manifests.
No partition patching, boot image rebuilding, Odin packaging or flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from plan_f741n_f956n_port import report_from_data

MODELS = ("SM-F741N", "SM-F956N")
PREFIX = "STOCK_IMAGES_ONLY_NOT_BUILDABLE"
EXPECTED_FSTYPES = {"erofs", "ext4", "f2fs"}


def detect_filesystem(path):
    with path.open("rb") as stream:
        stream.seek(1024)
        magic = stream.read(4)
        stream.seek(1080)
        ext4 = stream.read(2)
    if magic in (b"\xe2\xe1\xf5\xe0", b"\xe0\xf5\xe1\xe2"):
        return "erofs"
    if magic == b"\x10\x20\xf5\xf2":
        return "f2fs"
    if ext4 == b"\x53\xef":
        return "ext4"
    return "unknown"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_stage(folder, model, capacity, hash_images=False):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"Stage directory missing or is symlink: {folder}")
    selected = {p["partition"]: p for p in capacity["hybrid_partitions"] if p["source"] == model}
    if not selected:
        raise ValueError(f"Capacity plan does not include {model}")
    manifest_path = folder / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(f"Missing or linked manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != PREFIX or manifest.get("model") != model:
        raise ValueError(f"Invalid model or stage status in {manifest_path}")
    entries = manifest.get("partitions", [])
    if not isinstance(entries, list):
        raise ValueError("Expected partition list in stage manifest")
    indexed = {p["partition"]: p for p in entries}
    if len(indexed) != len(entries) or set(indexed) != set(selected):
        raise ValueError(f"Manifest partition set mismatch for {model}")
    actual_names = {item.name for item in folder.iterdir()}
    expected_names = {"manifest.json"} | {name + ".img" for name in selected}
    if actual_names != expected_names:
        raise ValueError(f"Unexpected/missing image files in {folder}: "
                         f"{sorted(actual_names ^ expected_names)}")

    images = []
    for partition in sorted(selected):
        image = folder / (partition + ".img")
        if image.is_symlink() or not image.is_file():
            raise ValueError(f"Image missing or symlink: {image}")
        expected_bytes = selected[partition]["current_image_bytes"]
        entry = indexed[partition]
        if entry.get("bytes") != expected_bytes:
            raise ValueError(f"Manifest size mismatch for {partition}")
        actual_bytes = image.stat().st_size
        if actual_bytes != expected_bytes:
            raise ValueError(f"LP image size mismatch for {partition}: "
                             f"{actual_bytes} vs {expected_bytes}")
        if actual_bytes < 4096:
            raise ValueError(f"Empty or implausibly small filesystem: {partition}")
        fstype = detect_filesystem(image)
        if fstype not in EXPECTED_FSTYPES:
            raise ValueError(f"Unrecognized filesystem signature in {image}")
        record = {"partition": partition, "model": model,
                  "bytes": actual_bytes, "filesystem": fstype}
        if hash_images:
            record["sha256"] = sha256_file(image)
        images.append(record)
    return {"model": model, "status": "STAGED_IMAGES_CHECKED_NOT_BOOTABLE",
            "source_ap": manifest["source_ap"], "images": images}


def verify_all(root, metadata_file, plan_file, hash_images=False):
    metadata = json.loads(metadata_file.read_text())
    plan = json.loads(plan_file.read_text())
    capacity = report_from_data(metadata, plan)
    if not capacity["capacity_estimate_pass"]:
        raise ValueError("Previous F741N group capacity estimate failed")
    devices = [
        verify_stage(root / "out/b6q/extracted" / model, model, capacity, hash_images)
        for model in MODELS
    ]
    return {"status": "IMAGE_STAGE_VALIDATION_ONLY_NO_ROM",
            "devices": devices, "capacity_estimate_pass": True,
            "warnings": [
                "Stock image sizes and filesystem signatures checked, not framework/vendor compatibility.",
                "DeX is not yet ported or enabled for b6q by this step.",
                "No boot, recovery, AVB, SELinux or VINTF validation was performed.",
            ]}


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha256", action="store_true",
                        help="Also hash each staged partition (reads ~10 GiB)")
    parser.add_argument("--output", type=Path,
                        default=root / "out/reports/f741n-f956n-stage-validation.json")
    args = parser.parse_args(argv)
    try:
        result = verify_all(
            root, root / "out/reports/f741n-f956n-super-metadata.json",
            root / "target/b6q/port-plan.json", args.sha256
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Stage verification failed: {exc}\n")
    for device in result["devices"]:
        print(f"{device['model']}: {len(device['images'])} images validated")
        for image in device["images"]:
            print(f"  {image['partition']}: {image['bytes']} bytes [{image['filesystem']}]")
    print(f"Stage verification PASS (NOT a bootable ROM). Report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
