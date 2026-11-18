#!/usr/bin/env python3
"""Stage real Flip5 DeX + KernelSU source as a Flip6 porting kit.

The existing b5q project already owns the smali DeX patches, native pacer
sources and KernelSU root runtime. Reuse these actual files, not a new ROM
implementation. The kit is *source only*: none of the b5q/SM8550 kernel image
or hard-coded native offsets can be used as F741N/SM8650 boot payloads.

No firmware modification, root installation, Odin AP or flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

B5Q = "SM-F731N"
ROOT_DONOR = "SM-F946B"
B6Q = "SM-F741N"
F6_DONOR = "SM-F956N"
MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_FILES = 500

SOURCE_TREES = {
    "dex/smali": "target/b5q/patches/dex/smali",
    "dex/native-reference": "target/b5q/patches/dex/native",
    "root/essential": "onigiri/mods/essential",
    "root/legacy-rootmods": "onigiri/mods/rootmods",
    "kernel/flip5-reference-patches": "external/patches/kernel",
}
SOURCE_FILES = {
    "dex/b5q-customize.sh": "target/b5q/patches/dex/customize.sh",
    "dex/b5q-module.prop": "target/b5q/patches/dex/module.prop",
    "dex/b6q-customize.sh": "target/b6q/patches/dex/customize.sh",
    "kernel/b5q-build_kernel.sh": "scripts/build_kernel.sh",
    "kernel/b5q-package_kernel.sh": "scripts/package_kernel.sh",
    "kernel/b5q-prepare_kernel.sh": "scripts/prepare_kernel.sh",
    "kernel/b6q-stock-config.sh": "target/b6q/config.sh",
}

BINARY_REFERENCES = [
    "prebuilts/apps/system/system/preload/me.weishu.kernelsu-Onigiri/base.apk",
    "prebuilts/rootmods/manifest.json",
]


def verified_sources(repo):
    """Return source file records; never follow symlinks or stage stock images."""
    if repo.is_symlink() or not repo.is_dir():
        raise ValueError("Invalid repository source")
    gathered = []
    selected = {}
    for to, source in SOURCE_TREES.items():
        folder = repo / source
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("Missing Flip5 source directory: " + source)
        count = 0
        for file in sorted(folder.rglob("*")):
            if file.is_symlink():
                raise ValueError("Symlink in Flip5 source: " + source)
            if not file.is_file():
                continue
            if not file.suffix in (".sh", ".py", ".patch", ".S", ".c", ".rc",
                                   ".json", ".prop", ".txt", ""):
                raise ValueError("Unexpected file in source selection: " + source)
            if file.stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError("Unexpectedly large Flip5 source file")
            dest = Path(to) / file.relative_to(folder)
            gathered.append((dest, file))
            count += 1
        if not count:
            raise ValueError("Empty source folder: " + source)
        selected[to] = count
    for to, source in SOURCE_FILES.items():
        file = repo / source
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Missing/invalid Flip5 source: " + source)
        gathered.append((Path(to), file))
    if len(gathered) > MAX_FILES:
        raise ValueError("Source selection unexpectedly large")
    for source in BINARY_REFERENCES:
        f = repo / source
        if f.is_symlink() or not f.is_file():
            raise ValueError("Missing pinned KernelSU/reference root asset: " + source)
    return gathered, selected


def source_summary(repo):
    gathered, counts = verified_sources(repo)
    return {
        "model": B6Q,
        "working_source": B5Q,
        "working_dex_donor": ROOT_DONOR,
        "actual_framework_donor": F6_DONOR,
        "source_counts": counts,
        "source_files": len(gathered),
        "source_bytes": sum(p.stat().st_size for _, p in gathered),
        "kernel_target": "SM8650 / Android 14 GKI 6.1 (requires matching F741N source verification)",
        "not_portable_from_flip5": [
            "SM8550 b5q kernel Image, boot.img, vendor_boot.img, dtbo.img",
            "SM8550 b5q vendor_dlkm/system_dlkm binaries and b5q device tree",
            "Fold5 SurfaceFlinger instruction offsets/hashes",
            "b5q camera/cover display/thermal hardware constants",
        ],
        "reusable_from_flip5": [
            "Fold5-derived DeX smali patch logic applied to matching Fold6 class revisions",
            "KernelSU integration design and root runtime source",
            "Root module packaging logic and pinned module asset references",
            "EROFS -> lpmake -> lpunpack checksum verification workflow",
        ],
        "hardware_preserved": [
            "F741N kernel and all boot/dtbo/vendor/dlkm components unless separately built for b6q",
            "F741N BL/CP/CSC and original AVB trust metadata",
        ],
        "root_kernel_compiled": False,
        "dex_boot_tested": False,
        "odin_ap_created": False,
        "flashable": False,
    }


def stage(repo, dest):
    items, counts = verified_sources(repo)
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("Porting kit exists; refusing to overwrite: " + str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".flip5-to-flip6-", dir=dest.parent) as tmp:
        current = Path(tmp)
        files = []
        for relative, source in items:
            target = current / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != hashlib.sha256(source.read_bytes()).hexdigest():
                raise ValueError("Source changed during staging: " + str(source))
            files.append({
                "source_path": source.relative_to(repo).as_posix(),
                "kit_path": relative.as_posix(),
                "bytes": target.stat().st_size,
                "sha256": digest,
            })
        refs = []
        for rel in BINARY_REFERENCES:
            p = repo / rel
            with p.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            refs.append({"source_path": rel, "bytes": p.stat().st_size,
                         "sha256": checksum,
                         "copy": False})
        index = source_summary(repo)
        index["kit_status"] = "B5Q_SOURCE_PORT_KIT_F741N_KERNEL_NOT_BUILT"
        index["source_counts"] = counts
        index["files"] = files
        index["pinned_binary_references"] = refs
        (current / "port-kit.json").write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        current.rename(dest)
    return index


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=root)
    parser.add_argument("--output", type=Path,
                        default=root / "out/target/b6q/SM-F741N/flip5-source-port-kit")
    parser.add_argument("--inspect", action="store_true",
                        help="Print source mapping without writing any files")
    args = parser.parse_args(argv)
    try:
        if args.inspect:
            result = source_summary(args.source_root)
        else:
            result = stage(args.source_root, args.output)
    except (OSError, ValueError, FileExistsError) as exc:
        parser.exit(1, "Flip5 → Flip6 source staging failed: " + str(exc) + "\n")
    print("DuyKhaiDeX F741N — Flip5 source files:", result["source_files"])
    print("DeX source originally from F946B; apply to F956N framework using b6q adapter")
    print("Kernel root b5q integration staged as SOURCE ONLY; F741N kernel is NOT built")
    if not args.inspect:
        print("Source kit:", args.output)
    print("No firmware modification, no flashable Odin AP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
