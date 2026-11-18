#!/usr/bin/env python3
"""Build a real Odin-format engineering AP from the existing b6q port tree.

Reuses OnigiriDeX's EROFS -> lpmake/lpunpack -> LZ4 -> tar.md5 pipeline.
Sources: F956N system/product/system_ext (ported DeX); F741N vendor, odm
and both dlkm partitions; STOCK F741N boot, init_boot, vendor_boot, dtbo,
recovery and optional stock vbmeta from the pinned F741N AP.

This is a mechanically valid but UNVERIFIED engineering Odin archive:
the stock signed F741N BL root vbmeta has hashtree descriptors over the
modified system/product/system_ext contents. Those hashes have NOT been
re-signed by the device's trusted signer. Stock boot is NOT KernelSU/rooted.
NEVER FLASH this archive. No flash/AVB bypass or root enable commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

from import_fw import verify_odin_package
from run_b6q_checkvintf import checked_work_tree
from stage_b6q_boot_chain import ASSETS, image_sha256

MODEL = "SM-F741N"
DONOR = "SM-F956N"
STOCK_BUILD = "F741NKSS2BYGB"
ARCHIVE_NAME = "DuyKhaiDeX_F741N_F956N_ENGINEERING_AP_NOT_FOR_FLASH.tar.md5"
MAX_BOOT_BYTES = 1024 * 1024 * 1024
SPARSE_MAGIC = bytes.fromhex("3aff26ed")
MIN_FREE_BUFFER = 512 * 1024 * 1024
# The AP deliberately contains only stock F741N boot images + rebuilt super.
STOCK_BOOT_ORDER = (
    "boot.img", "init_boot.img", "vendor_boot.img", "dtbo.img",
    "recovery.img", "vbmeta.img", "vbmeta_system.img",
)
IMAGE_MAGIC = {name: magic for name, (magic, _) in ASSETS.items()}
ALLOWED_SOURCE_NAMES = set(STOCK_BOOT_ORDER)


def expected_super(work, repo):
    name = ("DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img"
            if (work / ".b6q-settings-patched").is_file() else
            "DuyKhaiDeX_F741N_SUPER_PREVIEW_NOT_FOR_FLASH.img")
    return repo / "out/b6q/build" / name


def verify_input_super(super_img):
    if super_img.is_symlink() or not super_img.is_file():
        raise ValueError("Missing b6q super preview")
    if super_img.stat().st_size < 4096:
        raise ValueError("Truncated b6q super preview")
    with super_img.open("rb") as input_file:
        if input_file.read(4) != SPARSE_MAGIC:
            raise ValueError("Expected sparse F741N super image built by lpmake")
    checksum = Path(str(super_img) + ".sha256")
    if checksum.is_symlink() or not checksum.is_file():
        raise ValueError("Missing b6q super SHA256; do not use untracked images")
    expected = checksum.read_text(encoding="ascii").split()
    if len(expected) < 1 or len(expected[0]) != 64:
        raise ValueError("Invalid b6q super checksum manifest")
    with super_img.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    if actual != expected[0].lower():
        raise ValueError("F741N super image differs from its checksum")
    return {"bytes": super_img.stat().st_size, "sha256": actual}


def verify_stock_boot(boot_dir):
    manifest = boot_dir / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Missing staged STOCK F741N boot-chain manifest")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (data.get("model") != MODEL or data.get("firmware_build") != STOCK_BUILD
            or data.get("status") != "F741N_STOCK_BOOT_IMAGES_NOT_FLASHABLE"):
        raise ValueError("Wrong F741N boot model, build or stock source status")
    records = {}
    for entry in data.get("files", []):
        name = entry.get("name")
        if name not in ASSETS or name in records:
            raise ValueError("Unexpected/duplicate stock boot image record")
        records[name] = entry
    prepared = {}
    for name in STOCK_BOOT_ORDER:
        record = records.get(name)
        required = ASSETS[name][1]
        if not record or not record.get("present"):
            if required:
                raise ValueError("Missing essential F741N stock boot image: " + name)
            continue
        file = boot_dir / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("Stock F741N boot source unavailable: " + name)
        size = file.stat().st_size
        if not (512 <= size <= MAX_BOOT_BYTES) or size != record.get("bytes"):
            raise ValueError("Incorrect F741N stock boot image size: " + name)
        expected_magic = IMAGE_MAGIC[name]
        if expected_magic is not None:
            with file.open("rb") as handle:
                if handle.read(len(expected_magic)) != expected_magic:
                    raise ValueError("Bad stock F741N boot image header: " + name)
        digest = image_sha256(file)
        if digest != record.get("sha256"):
            raise ValueError("F741N stock boot hash mismatch: " + name)
        prepared[name] = {"path": file, "bytes": size, "sha256": digest}
    if not any(name in prepared for name in ("vbmeta.img", "vbmeta_system.img")):
        raise ValueError("Stock F741N AP contains no vbmeta source image")
    return prepared


def ensure_local_inputs(repo, boot_dir, super_img, *, auto_build):
    work = repo / "out/target/b6q/SM-F741N/work_dir"
    checked_work_tree(work)
    if not (work / ".b6q-dex-patched").is_file():
        raise ValueError("DeX F956N patches not completed; run scripts/port_b6q.sh apply")
    if not boot_dir.exists() and auto_build:
        subprocess.run([sys.executable, str(repo / "scripts/stage_b6q_boot_chain.py"),
                        "--extract", "--output", str(boot_dir)], cwd=repo, check=True)
    stock = verify_stock_boot(boot_dir)
    if not super_img.exists() and auto_build:
        subprocess.run(["bash", str(repo / "scripts/build_super_b6q.sh"), "--build"],
                       cwd=repo, check=True)
    super_info = verify_input_super(super_img)
    return stock, super_info


def compress_image(binary, source, output):
    # Samsung's LZ4 legacy frame header (same command as b5q build_odin.sh).
    # With an explicit destination, the source is left unchanged.
    completed = subprocess.run(
        [binary, "-B6", "--content-size", "-12", str(source), str(output)],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode:
        raise ValueError("LZ4 compression failed: " + completed.stderr[-400:])
    with output.open("rb") as handle:
        header = handle.read(15)
    if (len(header) < 15 or header[:5] != bytes.fromhex("04224d186c")
            or header[5] not in (0x40, 0x50, 0x60)
            or int.from_bytes(header[6:14], "little") != source.stat().st_size):
        raise ValueError("Invalid Samsung LZ4 output frame: " + source.name)


def assemble_ap(stock, super_img, output, *, lz4):
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to overwrite AP: " + str(output))
    if not shutil.which(lz4):
        raise ValueError("Missing lz4 executable")
    # LZ4 input, compressed copies and the TAR coexist temporarily.
    required = 2 * super_img.stat().st_size + 2 * sum(
        entry["bytes"] for entry in stock.values()
    ) + MIN_FREE_BUFFER
    if shutil.disk_usage(output.parent).free < required:
        raise OSError("Not enough free storage for compressed images + TAR; use --output-dir")
    with tempfile.TemporaryDirectory(prefix=".f741n-ap.", dir=output.parent) as temp:
        stage = Path(temp)
        entries = [("super.img", super_img)] + [
            (name, stock[name]["path"]) for name in STOCK_BOOT_ORDER if name in stock
        ]
        archive_entries = {}
        for name, source in entries:
            target = stage / (name + ".lz4")
            compress_image(lz4, source, target)
            archive_entries[target.name] = target
        tar = stage / "package.tar"
        with tarfile.open(tar, "w", format=tarfile.GNU_FORMAT) as archive:
            for name, source in archive_entries.items():
                archive.add(source, arcname=name, recursive=False)
        with tarfile.open(tar, "r:") as archive:
            if {m.name for m in archive} != set(archive_entries):
                raise ValueError("Staged Odin AP has wrong image names")
            if any(not m.isfile() or m.name.startswith("/") for m in archive):
                raise ValueError("Unexpected TAR entry in Odin AP")
        with tar.open("rb") as stream:
            md5 = hashlib.file_digest(stream, "md5").hexdigest()
        staged_ap = stage / output.name
        tar.rename(staged_ap)
        with staged_ap.open("ab") as stream:
            stream.write(f"{md5}  {output.name.removesuffix('.md5')}\n".encode())
        verify_odin_package(staged_ap)
        with staged_ap.open("rb") as stream:
            sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        staged_ap.rename(output)
    return {"path": output.name, "sha256": sha256,
            "bytes": output.stat().st_size, "members": list(archive_entries)}


def build(repo, output_dir, *, auto_build=True, lz4="lz4"):
    work = repo / "out/target/b6q/SM-F741N/work_dir"
    super_img = expected_super(work, repo)
    boot_dir = repo / "out/b6q/analysis/f741n-stock-boot-chain"
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ValueError("Output folder must not be a symlink")
    ap = output_dir / ARCHIVE_NAME
    if ap.exists() or ap.is_symlink():
        raise FileExistsError("Existing F741N AP will not be overwritten: " + str(ap))
    stock, super_info = ensure_local_inputs(
        repo, boot_dir, super_img, auto_build=auto_build
    )
    artifact = assemble_ap(stock, super_img, ap, lz4=lz4)
    manifest = {
        "status": "ENGINEERING_ODIN_AP_CREATED_NOT_FLASHABLE",
        "model": MODEL, "donor": DONOR,
        "donor_framework": ["system", "product", "system_ext"],
        "target_hardware": ["vendor", "odm", "vendor_dlkm", "system_dlkm"],
        "boot_source": "STOCK F741N ONLY", "stock_firmware_build": STOCK_BUILD,
        "stock_boot_images": {k: {"bytes": v["bytes"], "sha256": v["sha256"]}
                              for k, v in stock.items()},
        "sparse_super": {"file": super_img.name, **super_info},
        "archive": artifact,
        "kernel_root_built": False,
        "kernel_su_from_flip5_reused_on_flip6": False,
        "dex_boot_verified": False, "avb_device_trust_verified": False,
        "bootable": False, "flashable": False,
        "reasons": [
            "F741N stock BL root vbmeta has signed hashtree descriptors directly over modified system/product/system_ext",
            "DeX on F956N and SELinux/AVB have not passed complete device verification",
            "STOCK F741N boot is not a newly compiled F741N KernelSU kernel",
        ],
    }
    (output_dir / (ARCHIVE_NAME + ".json")).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / (ARCHIVE_NAME + ".sha256")).write_text(
        artifact["sha256"] + "  " + ARCHIVE_NAME + "\n", encoding="ascii"
    )
    return manifest


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true",
                        help="Actually produce one NOT-FOR-FLASH engineering AP from local inputs")
    parser.add_argument("--no-auto-build", action="store_true",
                        help="Do not stage F741N boot or construct super automatically")
    parser.add_argument("--output-dir", type=Path, default=repo / "out/b6q/build",
                        help="Output folder (must have free space for compression)")
    args = parser.parse_args(argv)
    if not args.build:
        parser.print_help()
        return 0
    try:
        result = build(repo, args.output_dir,
                       auto_build=not args.no_auto_build)
    except (ValueError, OSError, FileExistsError, subprocess.CalledProcessError,
            tarfile.TarError, json.JSONDecodeError) as exc:
        parser.exit(1, "F741N engineering AP build failed: " + str(exc) + "\n")
    print("ENGINEERING AP CREATED:", args.output_dir / ARCHIVE_NAME)
    print("Checksum:", result["archive"]["sha256"])
    print("STOCK F741N BOOT ONLY. NO KERNELSU BUILD. AVB UNVERIFIED.")
    print("THIS ODIN ARCHIVE IS NOT FLASH SAFE. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
