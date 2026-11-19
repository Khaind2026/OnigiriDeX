#!/usr/bin/env python3
"""Build and stage a MATCHING F741N Android15 kernel with KernelSU/SUSFS.

Reuses Samsung's original b6q/pineapple build_kernel_GKI.sh, not Flip5's
SM8550/Kalama source tree. Requires a user-supplied F741N kernel source
whose build script declares the SAME F741NKSS2BYGB build as the firmware.
Will NOT automatically fetch a different F741B / OneUI8 source or apply
old Android13-5.15 SUSFS patches to Android14-6.1.
Root integration MUST already be correctly present in that source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from package_b6q_ksu_kernel import (
    MODEL, BUILD, REQUIRED_CONFIG, RELEASE_PATTERN, source_provenance, package
)

TARGET_PATTERN = re.compile(r"(?m)^\s*(?:export\s+)?BUILD_TARGET\s*=\s*['\"]?(b6q_[a-zA-Z0-9_]+)")
BUILD_PATTERN = re.compile(r"(?m)^\s*(?:export\s+)?BUILD_NUMBER\s*=\s*['\"]?(F741N[A-Z0-9]+)")
CHIPSET_PATTERN = re.compile(r"(?m)^\s*(?:export\s+)?CHIPSET_NAME\s*=\s*['\"]?pineapple")
BUILD_DIRS = (
    "out/msm-pineapple-pineapple-gki",
    "kernel_platform/out/msm-pineapple-pineapple-gki",
)


def assert_source_is_matching(source):
    if source.is_symlink() or not source.is_dir():
        raise ValueError("The SM-F741N Samsung kernel source directory is missing")
    script = source / "build_kernel_GKI.sh"
    kp = source / "kernel_platform"
    if script.is_symlink() or not script.is_file() or not kp.is_dir():
        raise ValueError("Expected Samsung source build_kernel_GKI.sh and kernel_platform")
    if script.stat().st_size > 256 * 1024:
        raise ValueError("Unexpectedly large Samsung build script")
    data = script.read_text(encoding="utf-8", errors="replace")
    targets = TARGET_PATTERN.findall(data)
    builds = BUILD_PATTERN.findall(data)
    if len(targets) != 1 or not targets[0].startswith("b6q_"):
        raise ValueError("Source does not specify the b6q kernel target")
    if builds != [BUILD]:
        raise ValueError("Samsung F741N source BUILD_NUMBER does not match " + BUILD)
    if not CHIPSET_PATTERN.search(data):
        raise ValueError("Source is not for the SM8650/pineapple platform")
    # A confirmed target naming/build string is local source metadata,
    # not a cryptographic Samsung vendor attestation.
    return {"target": targets[0], "build": builds[0], "build_script_sha256":
            hashlib.sha256(script.read_bytes()).hexdigest()}


def discover_build_files(source):
    options = []
    for sub in BUILD_DIRS:
        d = source / sub
        for image in (d / "dist/Image", d / "packaged/Image"):
            for config in (d / "gki_kernel/common/.config", d / "common/.config"):
                release = d / "dist/kernel.release"
                if all(f.is_file() and not f.is_symlink()
                       for f in (image, config, release)):
                    options.append((image, config, release))
    if len(options) != 1:
        raise ValueError("Expected exactly one complete F741N Image/.config/kernel.release set; found " + str(len(options)))
    return options[0]


def build_source(source, *, run_build):
    src = assert_source_is_matching(source)
    if run_build:
        subprocess.run(["bash", "./build_kernel_GKI.sh"], cwd=source,
                       check=True, env={**os.environ, "TARGET_MODEL": MODEL})
    image, config, release = discover_build_files(source)
    version = release.read_text().strip()
    if not RELEASE_PATTERN.fullmatch(version):
        raise ValueError("F741N kernel release is not Android14 GKI 6.1")
    lines = set(config.read_text(encoding="utf-8").splitlines())
    missing = [line for line in REQUIRED_CONFIG if line not in lines]
    if missing:
        raise ValueError("F741N kernel not built with KernelSU/SUSFS: " + ",".join(missing))
    with image.open("rb") as f:
        f.seek(0x38)
        if f.read(4) != b"ARMd":
            raise ValueError("F741N build did not produce raw ARM64 Image")
    src["kernel_release"] = version
    src["image"] = image
    src["config"] = config
    src["release"] = release
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source,
                             check=True, capture_output=True, text=True, timeout=10)
        src["source_revision"] = rev.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        src["source_revision"] = "SAMSUNG_SOURCE_ARCHIVE_UNVERSIONED"
    return src


def stage_compiled(source, destination, *, run_build=False):
    if destination.is_symlink() or destination.exists():
        raise FileExistsError("F741N kernel artifact output already exists")
    prepared = build_source(source, run_build=run_build)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".f741n-ksu-build.", dir=destination.parent) as tmp:
        folder = Path(tmp) / "artifacts"
        folder.mkdir()
        for field, name in (("image", "Image"), ("config", ".config"),
                            ("release", "kernel.release")):
            shutil.copyfile(prepared[field], folder / name)
        profile = {
            "model": MODEL,
            "device": "b6q",
            "firmware_build": BUILD,
            "platform": "sm8650",
            "kernel_release": prepared["kernel_release"],
            "root_backend": "KernelSU+SUSFS",
            "source_is_samsung_f741n": True,
            "source_vendor_authenticity_not_verified": True,
            "source_build_target": prepared["target"],
            "source_build_script_sha256": prepared["build_script_sha256"],
            "source_revision": prepared["source_revision"],
            "module_abi_verified": False,
            "boot_tested": False,
        }
        (folder / "f741n-build-origin.json").write_text(json.dumps(profile, indent=2) + "\n")
        source_provenance(folder, folder / "Image", folder / ".config",
                          folder / "kernel.release")
        folder.rename(destination)
    return profile


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True,
                        help="LOCAL exact F741N One UI 7 Samsung kernel source (not Flip5/F741B UI8)")
    parser.add_argument("--build", action="store_true",
                        help="Execute the source's native b6q Samsung kernel build")
    parser.add_argument("--output-dir", type=Path,
                        default=repo / "out/target/b6q/kernel-compiled-ksu")
    parser.add_argument("--package-boot", action="store_true",
                        help="Also repack ORIGINAL F741N boot with compiled KSU kernel")
    args = parser.parse_args(argv)
    try:
        result = stage_compiled(args.source_root, args.output_dir, run_build=args.build)
        print("F741N KernelSU/SUSFS ARM64 Image staged:", args.output_dir)
        if args.package_boot:
            package(repo / "out/b6q/analysis/f741n-stock-boot-chain",
                    args.output_dir,
                    repo / "out/target/b6q/kernel-ksu-engineering",
                    str(repo / "out/tools/bin/magiskboot"))
            print("F741N KernelSU boot engineering image prepared. NOT FOR FLASH.")
    except (OSError, ValueError, FileExistsError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as error:
        parser.exit(1, "F741N kernel build stopped: " + str(error) + "\n")
    print("Model:", result["model"], "Source:", result["source_build_target"])
    print("Kernel ABI, OEM trust, AVB and on-device root NOT verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
