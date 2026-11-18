#!/usr/bin/env python3
"""Read-only F741N first-stage mount and stock boot-image format gate.

Parses stock boot/init_boot/vendor_boot image headers and vendor_boot v4
ramdisk fragment metadata. Also compares stock F741N vendor fstab flags
against the seven dynamic partitions selected for the hybrid ROM.

Does NOT extract ramdisks, sign AVB metadata, modify images, build an Odin AP,
or prove kernel/SELinux/boot compatibility. This gate never authorizes flash.
"""
import argparse
import json
from pathlib import Path
import struct
import sys

from analyze_b6q_avb import verify_stock_images

REQUIRED = ("system", "product", "system_ext", "vendor", "odm",
            "vendor_dlkm", "system_dlkm")
MAX_FSTAB_BYTES = 2 * 1024 * 1024
MAX_FSTAB_FILES = 32


def u32(buf, offset):
    return struct.unpack_from("<I", buf, offset)[0]


def align(size, block):
    return (size + block - 1) // block * block


def read_boot_header(path):
    with path.open("rb") as source:
        header = source.read(4096)
    if len(header) < 1580 or header[:8] != b"ANDROID!":
        raise ValueError("Invalid Android GKI boot header: " + path.name)
    version = u32(header, 40)
    size = u32(header, 20)
    if version not in (3, 4) or size not in (1580, 1584):
        raise ValueError("Unexpected v3/v4 Android boot layout: " + path.name)
    kernel_size, ramdisk_size = u32(header, 8), u32(header, 12)
    end = 4096 + align(kernel_size, 4096) + align(ramdisk_size, 4096)
    if version == 4:
        end += align(u32(header, 1580), 4096)
    if end > path.stat().st_size:
        raise ValueError("Truncated Android boot image: " + path.name)
    return {"header_version": version, "header_size": size,
            "kernel_bytes": kernel_size, "ramdisk_bytes": ramdisk_size,
            "image_bytes": path.stat().st_size}


def read_vendor_boot_header(path):
    with path.open("rb") as source:
        hdr = source.read(4096)
        if len(hdr) < 2128 or hdr[:8] != b"VNDRBOOT":
            raise ValueError("Invalid F741N vendor_boot header")
        version, page = u32(hdr, 8), u32(hdr, 12)
        if version not in (3, 4) or page not in (2048, 4096, 8192, 16384):
            raise ValueError("Unsupported F741N vendor_boot header version/page")
        size, dtb_size = u32(hdr, 2096), u32(hdr, 2100)
        vendor_ramdisk_size = u32(hdr, 24)
        if size != (2128 if version == 4 else 2112):
            raise ValueError("Unexpected F741N vendor_boot header size")
        table_size = entries = entry_size = bootconfig_size = 0
        if version == 4:
            table_size, entries, entry_size, bootconfig_size = (
                u32(hdr, 2112), u32(hdr, 2116),
                u32(hdr, 2120), u32(hdr, 2124))
            if entries > 128 or (entries and entry_size < 108):
                raise ValueError("Unsafe F741N vendor ramdisk table dimensions")
            if entries * entry_size > table_size or table_size > 128 * 1024:
                raise ValueError("Vendor ramdisk table exceeds declared bounds")
        body_offset = align(size, page)
        table_offset = body_offset + align(vendor_ramdisk_size, page) + align(dtb_size, page)
        total = table_offset + align(table_size, page) + align(bootconfig_size, page)
        if total > path.stat().st_size:
            raise ValueError("Truncated F741N vendor_boot sections")
        fragments = []
        if version == 4 and entries:
            source.seek(table_offset)
            table = source.read(table_size)
            for i in range(entries):
                off = i * entry_size
                length, rel_offset, kind = struct.unpack_from("<III", table, off)
                if rel_offset + length > vendor_ramdisk_size or kind not in (0, 1, 2, 3):
                    raise ValueError("Invalid F741N vendor ramdisk table entry")
                label = table[off + 12:off + 44].split(b"\x00", 1)[0]
                fragments.append({"name": label.decode("ascii", "replace"),
                                  "ramdisk_bytes": length, "ramdisk_offset": rel_offset,
                                  "type": kind})
    return {"header_version": version, "page_bytes": page,
            "vendor_ramdisk_bytes": vendor_ramdisk_size,
            "dtb_bytes": dtb_size, "bootconfig_bytes": bootconfig_size,
            "vendor_ramdisk_fragments": fragments,
            "image_bytes": path.stat().st_size,
            "ramdisk_contents_inspected": False}


def read_target_fstab(work):
    roots = (work / "vendor/etc", work / "odm/etc")
    files = []
    records = {part: [] for part in REQUIRED}
    for folder in roots:
        if folder.is_symlink() or not folder.is_dir():
            continue
        for path in sorted(folder.rglob("fstab.*")):
            if path.is_symlink() or not path.is_file():
                continue
            if len(files) >= MAX_FSTAB_FILES or path.stat().st_size > MAX_FSTAB_BYTES:
                raise ValueError("Unsafe fstab size/file count")
            files.append(str(path.relative_to(work)))
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                columns = line.split()
                if len(columns) < 5:
                    continue
                device, mount, fstype, _, fs_mgr = columns[:5]
                part = mount.lstrip("/")
                if part not in records:
                    continue
                flags = fs_mgr.split(",")
                records[part].append({
                    "source": str(path.relative_to(work)), "device": device,
                    "fs_type": fstype,
                    "first_stage_mount": "first_stage_mount" in flags,
                    "logical": "logical" in flags,
                    "avb": any(f == "avb" or f.startswith("avb=") for f in flags),
                })
    result = {}
    for part, variants in records.items():
        ok = any(v["first_stage_mount"] and v["logical"] and v["avb"] for v in variants)
        result[part] = {
            "entries": len(variants),
            "first_stage_logical_avb_variant_found": ok,
            "variants": variants[:12],
        }
    return {"fstab_files": files, "partitions": result,
            "all_seven_first_stage_logical_avb_variants_found":
                all(x["first_stage_logical_avb_variant_found"] for x in result.values())}


def analyze(stock, work, chain_report):
    if stock.is_symlink() or not stock.is_dir() or work.is_symlink() or not work.is_dir():
        raise ValueError("Expected stock F741N boot stage and prepared work tree")
    from json import JSONDecodeError
    origin = work / "port-origin.json"
    if origin.is_symlink() or not origin.is_file():
        raise ValueError("Missing hybrid port origin")
    sources = json.loads(origin.read_text())
    if sources.get("target") != "SM-F741N" or sources.get("donor") != "SM-F956N":
        raise ValueError("Unexpected hybrid target or donor")
    stock_hashes = verify_stock_images(stock)
    boot = {name: read_boot_header(stock / name)
            for name in ("boot.img", "init_boot.img")}
    boot["vendor_boot.img"] = read_vendor_boot_header(stock / "vendor_boot.img")
    fstab = read_target_fstab(work)
    if not chain_report.is_file() or chain_report.is_symlink():
        avb = {"state": "UNKNOWN_NO_STOCK_BL_DESCRIPTOR_REPORT"}
    else:
        chain = json.loads(chain_report.read_text())
        if chain.get("model") != "SM-F741N":
            raise ValueError("AVB descriptor source model mismatch")
        descriptors = chain.get("stock_bl_vbmeta", {}).get("descriptors", [])
        hashtrees = sorted({d.get("partition") for d in descriptors
                           if d.get("type") == "hashtree" and d.get("partition")})
        overlap = sorted(set(hashtrees) & {"system", "product", "system_ext"})
        avb = {"state": "STOCK_ROOT_HASHTREE_VS_REBUILT_HYBRID_UNVERIFIED",
               "stock_root_hashtree_partitions": hashtrees,
               "changed_partition_overlap": overlap,
               "stock_vbmeta_signature_verified": False}
    return {
        "model": "SM-F741N", "donor": "SM-F956N",
        "phase": "F741N_BOOT_FORMAT_FSTAB_AVB_PRECHECK",
        "status": "BOOT_MOUNT_LAYOUT_INSPECTED_FULL_VERIFICATION_PENDING",
        "stock_boot_image_hash_manifest_checked": len(stock_hashes),
        "boot_headers": boot, "target_fstab": fstab,
        "avb": avb,
        "unresolved": [
            "No actual first-stage ramdisk content or bootconfig inspected",
            "No kernel/DTB/DTBO hardware ABI or SELinux policy loading check",
            "No cryptographic trust chain or rebuilt system hashtree signing validation",
            "Host checkvintf result and real F741N handset boot remain separate gates",
        ],
        "flashable": False, "bootable": False,
    }


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--stock", type=Path,
                     default=repo / "out/b6q/analysis/f741n-stock-boot-chain")
    cli.add_argument("--work-dir", type=Path,
                     default=repo / "out/target/b6q/SM-F741N/work_dir")
    cli.add_argument("--chain", type=Path,
                     default=repo / "out/b6q/analysis/f741n-bl-vbmeta-chain.json")
    cli.add_argument("--output", type=Path,
                     default=repo / "out/b6q/analysis/f741n-boot-mount-avb-precheck.json")
    args = cli.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Output exists; no overwrite: " + str(args.output))
        result = analyze(args.stock, args.work_dir, args.chain)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, TypeError, KeyError, struct.error) as err:
        cli.exit(1, "F741N boot/mount audit error: " + str(err) + "\n")
    print("F741N boot image header versions:",
          {k: v["header_version"] for k, v in result["boot_headers"].items()})
    print("Seven F741N dynamic first-stage mount flags:",
          result["target_fstab"]["all_seven_first_stage_logical_avb_variants_found"])
    print("Stock BL vbmeta overlap:", result["avb"].get("changed_partition_overlap"))
    print("STATUS:", result["status"])
    print("Report:", args.output)
    print("READ ONLY. NO ODIN AP. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
