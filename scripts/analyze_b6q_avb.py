#!/usr/bin/env python3
"""Read-only boot/AVB compatibility report for the existing DuyKhaiDeX b6q port.

Consumes seven *already extracted* stock SM-F741N boot images, the staging
manifest and the already built branded super preview. No extraction, partition
writes, vbmeta patching, Odin AP packaging, or interaction with a phone.
Passing this report NEVER means the hybrid Fold6 system can boot on Flip6.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from stage_b6q_boot_chain import ASSETS, BUILD, TARGET

PREVIEW_NAME = "DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img"


def sha256_file(path: Path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def decode_vbmeta_header(path: Path):
    """Read AVB header without relying on installed optional avbtool."""
    with path.open("rb") as stream:
        buf = stream.read(256)
    if len(buf) != 256 or buf[:4] != b"AVB0":
        raise ValueError("Missing AVB0 header in F741N vbmeta_system")
    u32 = lambda offset: int.from_bytes(buf[offset:offset+4], "big")
    u64 = lambda offset: int.from_bytes(buf[offset:offset+8], "big")
    auth, aux = u64(12), u64(20)
    desc_off, desc_size = u64(96), u64(104)
    if path.stat().st_size < 256 + auth + aux:
        raise ValueError("Truncated AVB metadata blocks")
    if desc_off + desc_size > aux:
        raise ValueError("AVB descriptors extend beyond auxiliary block")
    return {
        "required_libavb_major": u32(4),
        "required_libavb_minor": u32(8),
        "auth_block_bytes": auth,
        "aux_block_bytes": aux,
        "algorithm_type": u32(28),
        "descriptor_bytes": desc_size,
        "rollback_index": u64(112),
        "flags": u32(120),
        "rollback_index_location": u32(124),
        "release_string": buf[128:176].split(b"\0", 1)[0].decode("ascii", "replace"),
        "signature_verified": False,
    }


def read_avbtool(path: Path, tool=None):
    binary = tool or shutil.which("avbtool")
    if not binary:
        return {"available": False, "reason": "avbtool not installed; descriptor detail unknown"}
    try:
        result = subprocess.run(
            [binary, "info_image", "--image", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "reason": str(error)}
    if result.returncode:
        return {"available": True, "parsed": False,
                "error": result.stderr.strip()[:2000]}
    return {"available": True, "parsed": True, "info": result.stdout[:10000],
            "signature_verified": False}


def verify_stock_images(folder: Path):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"Missing staged F741N images: {folder}")
    manifest = folder / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError("Missing original boot-chain manifest")
    obj = json.loads(manifest.read_text())
    if obj.get("status") != "F741N_STOCK_BOOT_IMAGES_NOT_FLASHABLE":
        raise ValueError("Unexpected stage manifest status")
    if obj.get("model") != TARGET or obj.get("firmware_build") != BUILD:
        raise ValueError("Wrong stock device or firmware: expected F741NKSS2BYGB")
    entries = obj.get("files")
    if not isinstance(entries, list) or len(entries) != len(ASSETS):
        raise ValueError("Manifest has wrong number of original boot entries")
    if len({rec.get("name") for rec in entries}) != len(entries):
        raise ValueError("Duplicate boot images in manifest")
    records = {rec["name"]: rec for rec in entries}
    if set(records) != set(ASSETS):
        raise ValueError("Manifest contains missing/unexpected boot assets")
    validated = []
    for name, (magic, required) in ASSETS.items():
        rec = records[name]
        file = folder / name
        if not rec.get("present"):
            if required or file.exists():
                raise ValueError("Missing required or unexpected stock asset: " + name)
            continue
        if file.is_symlink() or not file.is_file():
            raise ValueError("Missing or linked original asset: " + name)
        if file.stat().st_size != rec.get("bytes"):
            raise ValueError("Image size changed: " + name)
        actual_hash = sha256_file(file)
        if actual_hash != rec.get("sha256"):
            raise ValueError("Stock boot SHA256 mismatch: " + name)
        if magic:
            with file.open("rb") as stream:
                if stream.read(len(magic)) != magic:
                    raise ValueError("Stock boot image magic mismatch: " + name)
        validated.append({"image": name, "bytes": file.stat().st_size,
                          "sha256": actual_hash})
    return validated


def inspect_super(preview: Path, verify_large=False):
    if preview.is_symlink() or not preview.is_file():
        raise ValueError("Branded super preview missing: " + str(preview))
    sums = Path(str(preview) + ".sha256")
    if not sums.is_file() or sums.is_symlink():
        raise ValueError("Branded super SHA256 record missing")
    pieces = sums.read_text().strip().split()
    if len(pieces) != 2 or pieces[1] != str(preview):
        raise ValueError("Branded super SHA256 manifest name mismatch")
    digest = pieces[0].lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid branded super SHA256 manifest")
    if verify_large and sha256_file(preview) != digest:
        raise ValueError("Branded super checksum mismatch")
    return {"file": str(preview), "bytes": preview.stat().st_size,
            "sha256_recorded": digest, "sha256_recomputed": verify_large,
            "partition_repack_verified": "confirmed in user's Debian build output",
            "flashable": False}


def produce(stock: Path, preview: Path, *, verify_large=False, avbtool=None):
    boot = verify_stock_images(stock)
    vbmeta_path = stock / "vbmeta_system.img"
    if not vbmeta_path.exists():
        raise ValueError("F741N vbmeta_system.img missing")
    vm = decode_vbmeta_header(vbmeta_path)
    output = {
        "status": "BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT",
        "model": TARGET, "firmware_build": BUILD,
        "stock_boot_images_verified": boot,
        "vbmeta_system": {"header": vm, "avbtool": read_avbtool(vbmeta_path, avbtool)},
        "branded_super": inspect_super(preview, verify_large),
        "verified_conditions": [
            "F741N original boot images match staging manifest SHA256",
            "F741N vbmeta_system contains a structurally bounded AVB0 header",
            "Brand-new super preview exists with a recorded SHA256",
        ],
        "blockers": [
            "Stock F741N vbmeta_system signature/descriptors have not been proven to validate rebuilt Fold6 system/product/system_ext",
            "Top-level vbmeta.img is not in staged AP; chain of trust from stock F741N BL/boot must be established",
            "F956N Android framework vs F741N vendor/odm HAL, sepolicy, VINTF and early-mount compatibility are unverified",
            "F741N kernel, boot/vendor_boot ramdisk and fstab mount-policy compatibility are unverified",
            "No controlled-device boot or DeX functionality test has occurred",
        ],
        "flashable": False,
        "notes": [
            "This tool does not disable AVB, alter signatures, build an Odin AP, or access hardware",
            "Successful extraction and EROFS repacking are not proof of bootability",
            "Do not flash the engineering preview",
        ],
    }
    return output


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path,
                        default=root / "out/b6q/analysis/f741n-stock-boot-chain")
    parser.add_argument("--super", type=Path, default=root / "out/b6q/build" / PREVIEW_NAME)
    parser.add_argument("--verify-super", action="store_true",
                        help="Rehash the existing large super preview (optional)")
    parser.add_argument("--output", type=Path,
                        default=root / "out/b6q/analysis/f741n-avb-boot-readiness.json")
    args = parser.parse_args(argv)
    try:
        report = produce(args.stock, args.super, verify_large=args.verify_super)
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Report already exists; refusing overwrite: " + str(args.output))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"F741N AVB analysis failed: {exc}\n")
    print("F741N STOCK BOOT STAGE VERIFIED: 7 selected AP image files")
    print("vbmeta_system: AVB0 header parsed (signature NOT verified)")
    print("Top-level vbmeta.img: absent from F741N staged AP")
    print("Branded super exists. Hybrid boot compatibility: NOT PROVEN.")
    print("STATUS: BLOCKED_FOR_FLASH_UNVERIFIED_HYBRID_BOOT")
    print("Report:", args.output)
    print("No images modified; no Odin AP created; DO NOT FLASH PREVIEW.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
