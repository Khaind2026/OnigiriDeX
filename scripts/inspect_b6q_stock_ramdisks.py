#!/usr/bin/env python3
"""Offline read-only inventory of F741N init_boot/vendor_boot ramdisk contents.

Only stock F741N image bytes are read. The tool parses bounded CPIO entries,
reports init/fstab filenames and first-stage mount flags. No firmware/image
writes, unpacked files on disk, rooting, signing, or Odin AP generation.
"""
import argparse
import gzip
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from audit_b6q_boot_mount_gate import (
    align, read_boot_header, read_vendor_boot_header, verify_stock_images,
)

MAX_COMPRESSED = 40 * 1024 * 1024
MAX_DECOMPRESSED = 192 * 1024 * 1024
MAX_ENTRIES = 25000
MAX_INTERESTING_BYTES = 512 * 1024
CPIO_MAGICS = (b"070701", b"070702")
LZ4_MAGICS = (bytes.fromhex("04224d18"), bytes.fromhex("02214c18"))
SAFE_BOOTCONFIG_KEY = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")


def ramdisk_payload(path, offset, length):
    if not 0 <= length <= MAX_COMPRESSED or offset < 0:
        raise ValueError("Unexpected compressed ramdisk bounds")
    if offset + length > path.stat().st_size:
        raise ValueError("Ramdisk extends beyond original F741N image")
    with path.open("rb") as image:
        image.seek(offset)
        raw = image.read(length)
    if len(raw) != length:
        raise ValueError("Truncated stock ramdisk")
    return raw


def decompress_ramdisk(raw, lz4_tool=None):
    if not raw:
        return "EMPTY", b""
    if raw[:6] in CPIO_MAGICS:
        return "RAW_CPIO", raw
    if raw.startswith(bytes.fromhex("1f8b")):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            inflated = stream.read(MAX_DECOMPRESSED + 1)
        if len(inflated) > MAX_DECOMPRESSED:
            raise ValueError("Gzip ramdisk exceeds safety bound")
        return "GZIP", inflated
    if raw[:4] in LZ4_MAGICS:
        tool = lz4_tool or shutil.which("lz4")
        if not tool:
            return "LZ4_CANNOT_INSPECT_TOOL_MISSING", None
        with tempfile.TemporaryDirectory(prefix="f741n-ramdisk-readonly-") as tmp:
            compressed = Path(tmp) / "ramdisk.lz4"
            compressed.write_bytes(raw)
            proc = subprocess.Popen([str(tool), "-d", "-c", str(compressed)],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            output = bytearray()
            try:
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > MAX_DECOMPRESSED:
                        raise ValueError("LZ4 ramdisk exceeds safety bound")
                if proc.wait(timeout=60):
                    return "LZ4_DECODE_ERROR", None
            except BaseException:
                proc.kill()
                proc.wait()
                raise
        return "LZ4", bytes(output)
    return "UNKNOWN_COMPRESSION", None


def parse_cpio(raw):
    """Yield bounded newc entries. Never write archive paths to disk."""
    entries = []
    offset = 0
    count = 0
    while offset < len(raw):
        if raw[offset:] and not raw[offset:].strip(b"\x00"):
            break
        if len(raw) - offset < 110:
            raise ValueError("Truncated CPIO header")
        magic = raw[offset:offset + 6]
        if magic not in CPIO_MAGICS:
            raise ValueError("Ramdisk is not newc CPIO at offset " + str(offset))
        hdr = raw[offset + 6:offset + 110]
        try:
            fields = [int(hdr[i:i + 8], 16) for i in range(0, 104, 8)]
        except ValueError as error:
            raise ValueError("Invalid CPIO hexadecimal header") from error
        mode, size, name_length = fields[1], fields[6], fields[11]
        if not 1 <= name_length <= 4096:
            raise ValueError("Invalid CPIO filename length")
        name_at = offset + 110
        data_at = align(name_at + name_length, 4)
        end = data_at + size
        if end > len(raw):
            raise ValueError("Truncated CPIO file content")
        name_bytes = raw[name_at:name_at + name_length]
        if name_bytes[-1:] != b"\x00":
            raise ValueError("Missing CPIO filename terminator")
        name = name_bytes[:-1].decode("utf-8", "replace")
        if name == "TRAILER!!!":
            offset = align(end, 4)
            if offset >= len(raw) or not raw[offset:].strip(b"\x00"):
                break
            continue
        count += 1
        if count > MAX_ENTRIES:
            raise ValueError("CPIO entry count exceeds safety bound")
        kind = mode & 0o170000
        content = raw[data_at:end] if kind == 0o100000 and size <= MAX_INTERESTING_BYTES else None
        entries.append((name, kind, size, content))
        offset = align(end, 4)
    if not count:
        raise ValueError("No CPIO filesystem entries found")
    return entries


def safe_name(raw):
    name = raw.lstrip("./")
    if not name or ".." in name.split("/") or len(name) > 250:
        return None
    return name


def analyze_entries(entries):
    found = []
    fstab = []
    init = []
    important_mounts = {"system", "product", "system_ext", "vendor", "odm",
                        "vendor_dlkm", "system_dlkm"}
    for original, kind, size, content in entries:
        name = safe_name(original)
        if name is None:
            continue
        basename = name.rsplit("/", 1)[-1]
        is_fstab = basename.startswith("fstab.") or basename == "fstab"
        is_rc = name.endswith(".rc") and ("init" in name or name.startswith("etc/"))
        if is_fstab or is_rc:
            found.append({"file": name, "bytes": size,
                          "type": "fstab" if is_fstab else "init_rc"})
        if is_rc:
            init.append(name)
        if is_fstab and content is not None:
            for line in content.decode("utf-8", "replace").splitlines():
                cols = line.strip().split()
                if len(cols) < 5 or cols[0].startswith("#"):
                    continue
                mount = cols[1].strip("/")
                if mount in important_mounts:
                    flags = cols[4].split(",")
                    fstab.append({
                        "source": name, "mountpoint": "/" + mount,
                        "fs_type": cols[2], "logical": "logical" in flags,
                        "first_stage_mount": "first_stage_mount" in flags,
                        "avb": any(f == "avb" or f.startswith("avb=") for f in flags),
                    })
    return {
        "entries": len(entries), "interesting_files": found[:150],
        "init_rc_files": sorted(set(init))[:100],
        "first_stage_fstab_dynamic_entries": fstab[:100],
    }


def inspect_stock_ramdisks(folder, lz4_tool=None):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("F741N stock boot stage missing")
    verified = verify_stock_images(folder)
    init_path = folder / "init_boot.img"
    init_hdr = read_boot_header(init_path)
    init_offset = 4096 + align(init_hdr["kernel_bytes"], 4096)
    vendor_path = folder / "vendor_boot.img"
    v = read_vendor_boot_header(vendor_path)
    header_size = 2128 if v["header_version"] == 4 else 2112
    base_offset = align(header_size, v["page_bytes"])
    targets = [
        ("init_boot.img", init_path, init_offset, init_hdr["ramdisk_bytes"])
    ]
    fragments = v["vendor_ramdisk_fragments"]
    if fragments:
        for i, frag in enumerate(fragments):
            targets.append((
                "vendor_boot.img/fragment_" + str(i), vendor_path,
                base_offset + frag["ramdisk_offset"], frag["ramdisk_bytes"]
            ))
    else:
        targets.append((
            "vendor_boot.img/vendor_ramdisk", vendor_path,
            base_offset, v["vendor_ramdisk_bytes"]
        ))
    results = []
    for name, path, offset, size in targets:
        record = {"source": name, "compressed_bytes": size}
        try:
            raw = ramdisk_payload(path, offset, size)
            fmt, contents = decompress_ramdisk(raw, lz4_tool)
            record["compression"] = fmt
            if contents is None:
                record["status"] = "NOT_INSPECTED_UNSUPPORTED_COMPRESSION"
            elif not contents:
                record["status"] = "EMPTY"
            else:
                details = analyze_entries(parse_cpio(contents))
                record.update(details)
                record["status"] = "CPIO_INSPECTED"
        except (OSError, ValueError, EOFError, subprocess.TimeoutExpired) as error:
            record["status"] = "INSPECTION_ERROR"
            record["error"] = str(error)[:500]
        results.append(record)
    return {
        "model": "SM-F741N", "phase": "READ_ONLY_STOCK_BOOT_RAMDISK_INSPECTION",
        "status": "OFFLINE_RAMDISK_CONTENTS_PARTIALLY_INSPECTED",
        "original_boot_assets_manifest_verified": len(verified),
        "bootconfig_bytes": v["bootconfig_bytes"],
        "bootconfig_content_inspected": False,
        "ramdisks": results,
        "flashable": False, "bootable": False,
        "unresolved": [
            "Ramdisk file presence does not validate init execution or mounts",
            "Bootconfig, DTB, kernel ABI, and complete SELinux loading not verified",
            "AVB signature validation and acceptance of rebuilt super not verified",
            "No controlled SM-F741N handset boot has been attempted",
        ],
    }


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=Path,
                        default=root / "out/b6q/analysis/f741n-stock-boot-chain")
    parser.add_argument("--output", type=Path,
                        default=root / "out/b6q/analysis/f741n-stock-ramdisk-content.json")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.exit(1, "Output exists, refusing overwrite\n")
    try:
        report = inspect_stock_ramdisks(args.stock)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError) as error:
        parser.exit(1, "Stock F741N ramdisk analysis failed: " + str(error) + "\n")
    for rec in report["ramdisks"]:
        print(rec["source"], rec["status"], rec.get("compression", "UNKNOWN"))
        if rec.get("status") == "CPIO_INSPECTED":
            print("  CPIO entries:", rec["entries"],
                  "fstab dynamic mounts:", len(rec["first_stage_fstab_dynamic_entries"]))
    print("READ-ONLY RAMDISK REPORT:", args.output)
    print("DO NOT FLASH. No ROM images modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
