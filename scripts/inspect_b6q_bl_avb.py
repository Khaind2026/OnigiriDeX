#!/usr/bin/env python3
"""Inspect F741N BL AVB candidates and stock vbmeta_system descriptors, read-only.

Uses firmware and boot assets already imported/extracted in OnigiriDeX.
Identifies which Odin archive contains candidate AVB metadata, and reports
which modified partitions a stock vbmeta_system might refer to. Does not
extract Odin BL components, modify AVB, or claim a bootable ROM.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

from inspect_f741n_f956n_archives import locate_archive, list_tar_headers

MODEL = "SM-F741N"
AVB_COMPONENT = re.compile(r"(?i)^(vbmeta(?:_[a-z0-9_]+)?|avb(?:_[a-z0-9_]+)?)\.img(?:\.lz4)?$")
BOOT_COMPONENT = re.compile(r"(?i)(?:boot|sboot|abl|xbl|lk|vbmeta|avb)")
PORT_PARTITIONS = {"system", "system_ext", "product", "vendor", "odm", "vendor_dlkm", "system_dlkm"}
PARTITION_LINE = re.compile(r"(?im)^\s*Partition Name:\s*([A-Za-z0-9_]+)\s*$")


def stock_bl_inventory(odin_root: Path):
    folder = odin_root / "SM-F741N_SKC"
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("F741N stock imported Odin directory missing")
    archive = locate_archive(folder, MODEL, "BL")
    headers = list_tar_headers(archive)
    if len(headers) == 0:
        raise ValueError("Empty stock F741N BL TAR")
    candidates = []
    seen = set()
    for entry in headers:
        name = Path(entry["name"]).name
        if name != entry["name"]:
            raise ValueError("BL archive contains nested or unsafe name: " + entry["name"])
        if name in seen:
            raise ValueError("BL archive duplicate: " + name)
        seen.add(name)
        if BOOT_COMPONENT.search(name):
            candidates.append({"name": name, "bytes": entry["bytes"],
                               "avb_metadata_candidate": bool(AVB_COMPONENT.fullmatch(name))})
    return {"archive": archive.name, "entries": len(headers),
            "related_members": candidates,
            "top_level_vbmeta_found": any(
                x["name"].lower() in ("vbmeta.img", "vbmeta.img.lz4")
                for x in candidates
            )}


def scan_vbmeta(avb_image: Path, avbtool: str | None = None):
    if avb_image.is_symlink() or not avb_image.is_file():
        raise ValueError("Missing previously staged F741N vbmeta_system.img")
    with avb_image.open("rb") as file:
        if file.read(4) != b"AVB0":
            raise ValueError("F741N vbmeta_system is not AVB0")
    tool = avbtool or shutil.which("avbtool")
    if not tool:
        return {"tool_available": False, "descriptors_parsed": False,
                "reason": "avbtool not installed; do not assume matching descriptors",
                "signature_verified": False}
    try:
        proc = subprocess.run([tool, "info_image", "--image", str(avb_image)],
                              capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"tool_available": True, "descriptors_parsed": False,
                "reason": str(error), "signature_verified": False}
    if proc.returncode != 0:
        return {"tool_available": True, "descriptors_parsed": False,
                "reason": (proc.stderr or proc.stdout).strip()[:1200],
                "signature_verified": False}
    partitions = sorted(set(PARTITION_LINE.findall(proc.stdout)))
    return {
        "tool_available": True, "descriptors_parsed": True,
        "referenced_partitions": partitions,
        "modified_system_partition_overlap": sorted(
            set(partitions) & {"system", "product", "system_ext"}
        ),
        "hashtree_or_hash_descriptors": (
            "Hashtree descriptor:" in proc.stdout
            or "Hash descriptor:" in proc.stdout
        ),
        "signature_verified": False,
        "raw_avbtool_details": proc.stdout[:16000],
    }


def make_report(odin_root: Path, staged: Path, prior_report: Path,
                *, avbtool: str | None = None):
    if prior_report.is_symlink() or not prior_report.is_file():
        raise ValueError("Previous F741N stock-stage AVB report missing")
    prior = json.loads(prior_report.read_text(encoding="utf-8"))
    if (prior.get("model") != MODEL or
            prior.get("status") != "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT" or
            prior.get("flashable") is not False):
        raise ValueError("Previous report is not the expected blocked F741N analysis")
    bl = stock_bl_inventory(odin_root)
    vbmeta = scan_vbmeta(staged / "vbmeta_system.img", avbtool)
    return {
        "model": MODEL,
        "phase": "READ_ONLY_F741N_BL_AVB_DESCRIPTOR_DISCOVERY",
        "status": "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT",
        "bl_inventory": bl,
        "stock_vbmeta_system": vbmeta,
        "candidate_super_partitions": sorted(PORT_PARTITIONS),
        "next_gates": [
            "Determine origin and actual verification chain of top-level vbmeta on F741N (BL, AP or boot chain)",
            "Prove all changed system/product/system_ext image hashes or hashtrees are accepted by verified chain",
            "Evaluate framework versus F741N vendor VINTF/SELinux interfaces and required boot fstab",
            "Check A/B and bootloader matching and create a recoverable device-test plan",
            "Validate boot and DeX on actual F741N hardware; no test has yet occurred",
        ],
        "flashable": False,
        "notes": [
            "This report inventories existing files only; it does not extract or patch BL",
            "avbtool info_image displays metadata; it does NOT verify Android signatures",
            "Do not flash the branded super engineering preview",
        ],
    }


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odin-root", type=Path, default=repo / "out/odin")
    parser.add_argument("--stock", type=Path,
                        default=repo / "out/b6q/analysis/f741n-stock-boot-chain")
    parser.add_argument("--previous", type=Path,
                        default=repo / "out/b6q/analysis/f741n-avb-boot-readiness.json")
    parser.add_argument("--output", type=Path,
                        default=repo / "out/b6q/analysis/f741n-bl-avb-discovery.json")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Output exists, refusing overwrite: " + str(args.output))
        result = make_report(args.odin_root, args.stock, args.previous)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, tarfile.TarError, json.JSONDecodeError) as error:
        parser.exit(1, f"F741N BL / AVB discovery failed: {error}\n")
    print("Stock F741N BL:", result["bl_inventory"]["archive"])
    print("BL top-level vbmeta.img:", "FOUND" if result["bl_inventory"]["top_level_vbmeta_found"]
          else "NOT FOUND IN BL HEADERS")
    print("vbmeta_system descriptor parsing:", "OK" if result["stock_vbmeta_system"].get("descriptors_parsed")
          else "UNAVAILABLE")
    print("Hybrid Fold6 system boot compatibility: NOT VERIFIED")
    print("STATUS:", result["status"])
    print("Report:", args.output)
    print("No firmware modified, no Odin AP created, NO FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
