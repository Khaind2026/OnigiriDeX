#!/usr/bin/env python3
"""Prepare ONLY Flip6 F741N stock boot-chain images for DuyKhaiDeX research.

Default: inspect already-imported F741NKSS2BYGB Odin AP TAR headers (fast).
--extract: selectively decompress AP boot-related images (NEVER Fold6),
validate image magic, and emit checksums/AVB information. No AP/super
creation, bootloader modification, phone interaction or flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from inspect_f741n_f956n_archives import locate_archive

TARGET = "SM-F741N"
BUILD = "F741NKSS2BYGB"
ASSETS = {
    "boot.img": (b"ANDROID!", True),
    "init_boot.img": (b"ANDROID!", True),
    "vendor_boot.img": (b"VNDRBOOT", True),
    "dtbo.img": (bytes.fromhex("d7b7ab1e"), True),
    "recovery.img": (b"ANDROID!", True),
    "vbmeta.img": (b"AVB0", False),
    "vbmeta_system.img": (b"AVB0", False),
    "vm-bootsys.img": (None, False),
}
MAX_FILE_BYTES = 1024 * 1024 * 1024


def inventory(archive):
    found = {}
    with tarfile.open(archive, "r:") as package:
        for member in package:
            if not member.isfile():
                continue
            name = Path(member.name).name
            if name.endswith(".lz4"):
                key = name[:-4]
                if key not in ASSETS:
                    continue
                if member.name != name:
                    raise ValueError(f"Unsafe non-root TAR entry: {member.name}")
                if key in found:
                    raise ValueError(f"Duplicate AP boot-chain entry: {key}")
                if not 15 <= member.size <= MAX_FILE_BYTES:
                    raise ValueError(f"Invalid {key} compressed size: {member.size}")
                found[key] = {"tar_member": member.name, "compressed_bytes": member.size}
    missing = [name for name, (_, needed) in ASSETS.items()
               if needed and name not in found]
    if missing:
        raise ValueError("Missing F741N boot chain members: " + ", ".join(missing))
    if not any(name in found for name in ("vbmeta.img", "vbmeta_system.img")):
        raise ValueError("F741N AP has no known AVB metadata image")
    return found


def decode_member(package, member, output, lz4="lz4"):
    """Pipe one TAR member through system lz4; never build shell commands."""
    if not member.isfile() or member.size > MAX_FILE_BYTES:
        raise ValueError("Member too large or not a regular file")
    source = package.extractfile(member)
    if source is None:
        raise ValueError(f"Cannot read TAR member {member.name}")
    header = source.read(4)
    if header != bytes.fromhex("04224d18"):
        raise ValueError(f"Invalid LZ4 frame magic in {member.name}")
    with output.open("xb") as written, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(
            [lz4, "-d", "-c"], stdin=subprocess.PIPE, stdout=written,
            stderr=err
        )
        try:
            process.stdin.write(header)
            while True:
                chunk = source.read(1 << 20)
                if not chunk:
                    break
                process.stdin.write(chunk)
            process.stdin.close()
            code = process.wait()
        except (BrokenPipeError, OSError):
            process.kill()
            process.wait()
            raise
        if code != 0:
            err.seek(0)
            raise ValueError(
                f"LZ4 decoding failed for {member.name}: "
                + err.read(1200).decode("utf-8", "replace")
            )
    if output.stat().st_size > MAX_FILE_BYTES or output.stat().st_size < 512:
        raise ValueError(f"Implausible decompressed image size: {member.name}")
    return output.stat().st_size


def image_sha256(path):
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for data in iter(lambda: file.read(1 << 20), b""):
            sha.update(data)
    return sha.hexdigest()


def inspect_avb(image, command=None):
    binary = command or shutil.which("avbtool")
    if not binary:
        return {"checked": False, "reason": "avbtool unavailable"}
    completed = subprocess.run(
        [binary, "info_image", "--image", str(image)],
        capture_output=True, text=True, timeout=30,
    )
    if completed.returncode:
        return {"checked": False, "reason": completed.stderr.strip()[:1000]}
    output = completed.stdout
    relevant = [
        line.strip() for line in output.splitlines()
        if re.search(r"^(Algorithm|Rollback Index|Rollback Index Location|"
                     r"Flags|Header Block|Authentication Block|Auxiliary Block|"
                     r"Descriptors|Hash descriptor|Hashtree descriptor|"
                     r"Partition Name|Chain Partition descriptor):", line.strip(),
                     re.IGNORECASE)
    ]
    return {"checked": True, "summary": relevant}


def stage(archive, dest, tool="lz4", avbtool=None):
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("Refusing to overwrite: " + str(dest))
    entries = inventory(archive)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".f741n-boot.", dir=dest.parent) as tmp:
        stage_dir = Path(tmp)
        records = []
        with tarfile.open(archive, "r:") as stream:
            for key, (magic, needed) in ASSETS.items():
                if key not in entries:
                    records.append({"name": key, "present": False, "required": needed})
                    continue
                member = stream.getmember(entries[key]["tar_member"])
                output = stage_dir / key
                size = decode_member(stream, member, output, tool)
                if magic is not None:
                    with output.open("rb") as src:
                        actual = src.read(len(magic))
                    if actual != magic:
                        raise ValueError(
                            f"Unexpected F741N {key} image magic: {actual.hex()}"
                        )
                record = {
                    "name": key, "present": True, "required": needed,
                    "source": f"{TARGET} {BUILD} AP",
                    "bytes": size,
                    "sha256": image_sha256(output),
                }
                if key.startswith("vbmeta"):
                    record["avbtool"] = inspect_avb(output, avbtool)
                records.append(record)
                print(f"F741N source verified: {key} ({size} bytes)", flush=True)
        result = {
            "status": "F741N_STOCK_BOOT_IMAGES_NOT_FLASHABLE",
            "model": TARGET, "firmware_build": BUILD,
            "source_ap": archive.name,
            "files": records,
            "warnings": [
                "Only original F741N boot-chain images. No Fold6 bootloader/DTBO/kernel used.",
                "A verified stock boot image does not prove a modified Fold6 super will boot.",
                "Original vbmeta AVB descriptors may reject modified partitions.",
                "Do not flash this directory or the branded super preview.",
            ],
        }
        (stage_dir / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
        stage_dir.rename(dest)
    return result


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--odin-root", type=Path, default=root / "out/odin")
    parser.add_argument("--output", type=Path,
                        default=root / "out/b6q/analysis/f741n-stock-boot-chain")
    args = parser.parse_args(argv)
    try:
        imported = args.odin_root / "SM-F741N_SKC"
        if imported.is_symlink() or not imported.is_dir():
            raise ValueError(f"Missing imported F741N stock Odin AP: {imported}")
        ap = locate_archive(imported, TARGET, "AP")
        found = inventory(ap)
        print(f"Stock Flip6 {BUILD} AP boot components ({len(found)}):")
        for key in ASSETS:
            print(f"  {key}: {'PRESENT' if key in found else 'NOT IN AP'}")
        if not args.extract:
            print("READ-ONLY PREFLIGHT PASS. Run --extract to stage F741N images.")
            print("No phone interaction or AP modification.")
            return 0
        if not shutil.which("lz4"):
            raise ValueError("lz4 CLI not found; install existing build dependencies")
        result = stage(ap, args.output)
        print(f"F741N boot-chain research files: {args.output}")
        print(f"Staged {sum(x['present'] for x in result['files'])} stock images.")
        print("NO ODIN AP CREATED. DO NOT FLASH THESE FILES.")
        return 0
    except (OSError, ValueError, tarfile.TarError,
            subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"F741N boot-chain preparation failed: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
