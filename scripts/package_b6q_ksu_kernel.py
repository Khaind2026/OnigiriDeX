#!/usr/bin/env python3
"""Repack a COMPILED device-specific F741N KernelSU/SUSFS Image into stock boot.

Accepts a genuine SM-F741N/SM8650 Android 14 GKI 6.1 kernel build,
checks its ARM64 Image header and compiled KSU/SUSFS configuration, then
reuses the ORIGINAL F741N boot v4 header, layout and ramdisk via magiskboot.
Never uses b5q/SM8550 kernel images or copies Fold6 bootloader/DTBO.
Does NOT sign AVB, patch vbmeta, flash the phone or claim boot compatibility.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from build_b6q_engineering_ap import verify_stock_boot
from audit_b6q_boot_mount_gate import read_boot_header

MODEL = "SM-F741N"
BUILD = "F741NKSS2BYGB"
MAX_KERNEL_IMAGE = 96 * 1024 * 1024
OUT_NAME = "boot_F741N_KSU_SUSFS_ENGINEERING_NOT_FOR_FLASH.img"
REQUIRED_CONFIG = (
    "CONFIG_ARM64=y", "CONFIG_KSU=y", "CONFIG_KSU_SUSFS=y",
    "CONFIG_MODVERSIONS=y",
)
RELEASE_PATTERN = re.compile(r"^6\.1\.\d+-android14-[\w.-]{2,120}$")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_provenance(root, image, config, release):
    for item in (root, image, config, release):
        if item.is_symlink():
            raise ValueError("Kernel source/build artifact symlinks not accepted")
    if not root.is_dir() or not all(f.is_file() for f in (image, config, release)):
        raise ValueError("Missing compiled F741N kernel Image, .config or kernel.release")
    if not (4096 <= image.stat().st_size <= MAX_KERNEL_IMAGE):
        raise ValueError("Unexpected F741N kernel Image size")
    with image.open("rb") as reader:
        reader.seek(0x38)
        magic = reader.read(4)
    if magic != b"ARMd":
        raise ValueError("Not a raw ARM64 Image (ARMd header at offset 0x38)")
    release_text = release.read_text(encoding="utf-8").strip()
    if not RELEASE_PATTERN.fullmatch(release_text):
        raise ValueError("Kernel release must be Android14 GKI 6.1; b5q/SM8550 is invalid")
    config_text = config.read_text(encoding="utf-8")
    lines = set(config_text.splitlines())
    for option in REQUIRED_CONFIG:
        if option not in lines:
            raise ValueError("Missing compiled F741N kernel option: " + option)
    # Local build profile binds this Image to a particular target build.
    # It is not a Samsung signature or on-device authenticity proof.
    profile = root / "f741n-build-origin.json"
    if profile.is_symlink() or not profile.is_file():
        raise ValueError("F741N kernel build provenance manifest missing")
    origin = json.loads(profile.read_text(encoding="utf-8"))
    for field, expected in (
        ("model", MODEL), ("firmware_build", BUILD),
        ("device", "b6q"), ("platform", "sm8650"),
        ("kernel_release", release_text),
    ):
        if origin.get(field) != expected:
            raise ValueError("F741N root kernel build provenance mismatch: " + field)
    if origin.get("source_is_samsung_f741n") is not True:
        raise ValueError("Kernel source not confirmed as F741N-specific")
    if origin.get("root_backend") != "KernelSU+SUSFS":
        raise ValueError("Compiled kernel provenance does not indicate KernelSU/SUSFS")
    return {
        "kernel_release": release_text,
        "kernel_bytes": image.stat().st_size,
        "kernel_sha256": sha256(image),
        "config_sha256": sha256(config),
        "source_revision": str(origin.get("source_revision") or "UNVERIFIED"),
    }


def package(stock_dir, build_dir, output_dir, magiskboot):
    stock_images = verify_stock_boot(stock_dir)
    stock = stock_images["boot.img"]["path"]
    info = source_provenance(
        build_dir, build_dir / "Image", build_dir / ".config",
        build_dir / "kernel.release",
    )
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("Kernel output exists; refusing to overwrite")
    magisk = shutil.which(magiskboot) or (Path(magiskboot) if Path(magiskboot).is_file() else None)
    if not magisk:
        raise ValueError("magiskboot executable is required from trusted local build tools")
    stock_hdr = read_boot_header(stock)
    if stock_hdr["header_version"] != 4:
        raise ValueError("Expected F741N stock Android boot v4 image")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".f741n-root-kernel.", dir=output_dir.parent) as tmp:
        root = Path(tmp)
        work = root / "repack"
        work.mkdir()
        shutil.copyfile(stock, work / "stock.img")
        unpack = subprocess.run(
            [str(magisk), "unpack", "-n", "-h", "stock.img"],
            cwd=work, capture_output=True, text=True, timeout=180,
        )
        if unpack.returncode != 0 or not (work / "kernel").is_file():
            raise ValueError("Unable to safely unpack F741N stock boot with magiskboot")
        shutil.copyfile(build_dir / "Image", work / "kernel")
        repack = subprocess.run(
            [str(magisk), "repack", "stock.img", "new-boot.img"],
            cwd=work, capture_output=True, text=True, timeout=180,
            env={**__import__("os").environ, "PATCHVBMETAFLAG": "false"},
        )
        if repack.returncode != 0:
            raise ValueError("F741N boot repack failed")
        built = work / "new-boot.img"
        if not built.is_file() or built.stat().st_size > stock.stat().st_size:
            raise ValueError("Repacked F741N boot exceeds the original partition size")
        result_hdr = read_boot_header(built)
        if result_hdr["header_version"] != 4 or sha256(built) == sha256(stock):
            raise ValueError("Root boot header or modified payload not verified")
        stage = root / "stage"
        stage.mkdir()
        shutil.copyfile(built, stage / OUT_NAME)
        report = {
            "status": "F741N_KSU_BOOT_REPACKED_NOT_BOOT_VERIFIED",
            "model": MODEL, "device": "b6q", "platform": "sm8650",
            "firmware_build": BUILD,
            "stock_boot_sha256": stock_images["boot.img"]["sha256"],
            "stock_boot_bytes": stock.stat().st_size,
            "root_boot_file": OUT_NAME,
            "root_boot_sha256": sha256(stage / OUT_NAME),
            "root_boot_bytes": (stage / OUT_NAME).stat().st_size,
            "source": info,
            "root_kernel_compile_claim": "KSU/SUSFS config checked but device not tested",
            "vendor_boot_replaced": False,
            "kernel_module_abi_verified": False,
            "avb_trust_verified": False, "flashable": False, "bootable": False,
            "blockers": [
                "F741N BL root signed AVB descriptors cover rebuilt system/product/system_ext",
                "Kernel module ABI, vendor_boot and DTBO runtime not yet proven",
                "No F741N hardware boot, KernelSU or DeX execution test",
            ],
        }
        (stage / "manifest.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
        stage.rename(output_dir)
    return report


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-build-dir", type=Path, required=True,
                        help="Locally compiled F741N 6.1 kernel Image/.config/kernel.release with provenance")
    parser.add_argument("--stock-boot-dir", type=Path,
                        default=repo / "out/b6q/analysis/f741n-stock-boot-chain")
    parser.add_argument("--output-dir", type=Path,
                        default=repo / "out/target/b6q/kernel-ksu-engineering")
    parser.add_argument("--magiskboot", default=str(repo / "out/tools/bin/magiskboot"))
    args = parser.parse_args(argv)
    try:
        report = package(args.stock_boot_dir, args.kernel_build_dir,
                         args.output_dir, args.magiskboot)
    except (OSError, ValueError, FileExistsError, subprocess.TimeoutExpired) as error:
        parser.exit(1, "F741N kernel staging stopped: " + str(error) + "\n")
    print("F741N experimental KSU boot:", args.output_dir / OUT_NAME)
    print("SHA256:", report["root_boot_sha256"])
    print("AVB/ABI/boot NOT VERIFIED. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
