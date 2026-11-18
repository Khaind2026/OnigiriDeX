#!/usr/bin/env python3
"""Compare F741N stock vendor_boot ramdisk fstab and vendor EROFS fstab.

Pure read-only comparison of diagnostics already gathered by
audit_b6q_boot_mount_gate.py and inspect_b6q_stock_ramdisks.py.
Matching rules only prove a metadata-level agreement, NOT Android boot.
"""
from pathlib import Path
import argparse
import json
import sys

PARTITIONS = ("system", "product", "system_ext", "vendor", "odm",
              "vendor_dlkm", "system_dlkm")
FIELDS = ("fs_type", "logical", "first_stage_mount", "avb")


def signature(entry):
    if not isinstance(entry, dict) or not all(key in entry for key in FIELDS):
        raise ValueError("Incomplete fstab entry")
    if not isinstance(entry["fs_type"], str) or not entry["fs_type"]:
        raise ValueError("Missing filesystem type")
    if any(type(entry[key]) is not bool for key in FIELDS[1:]):
        raise ValueError("Inconsistent first-stage mount flag type")
    return tuple(entry[key] for key in FIELDS)


def comparable_data(sections):
    boot = sections.get("boot_mount_avb_precheck", {})
    ramdisk = sections.get("stock_ramdisk_content", {})
    if (not isinstance(boot, dict) or not isinstance(ramdisk, dict)
            or boot.get("model") != "SM-F741N"
            or ramdisk.get("model") != "SM-F741N"):
        return None, "Missing or wrong-model F741N boot/ramdisk analysis"
    if boot.get("status") != "BOOT_MOUNT_LAYOUT_INSPECTED_FULL_VERIFICATION_PENDING":
        return None, "First-stage vendor fstab structure not confirmed"
    scans = ramdisk.get("ramdisks", [])
    if not isinstance(scans, list) or not scans:
        return None, "No stock ramdisks scanned"
    vendor_scans = [
        entry for entry in scans
        if isinstance(entry, dict)
        and entry.get("source", "").startswith("vendor_boot.img/")
    ]
    if not vendor_scans or any(e.get("status") != "CPIO_INSPECTED" for e in vendor_scans):
        return None, "Vendor ramdisk CPIO not fully inspected"
    if not isinstance(boot.get("target_fstab", {}).get("partitions"), dict):
        return None, "No prepared vendor/etc fstab partition evidence"
    return (boot, vendor_scans), None


def evaluate(sections):
    data, error = comparable_data(sections)
    base = {
        "target": "SM-F741N", "donor": "SM-F956N",
        "phase": "READ_ONLY_VENDOR_AND_RAMDISK_FSTAB_COMPARISON",
        "flashable": False, "bootable": False,
        "scope": "Only fs type + logical / first_stage_mount / avb flags; not device paths or init execution",
    }
    if error:
        return {**base, "status": "UNKNOWN_INSUFFICIENT_FSTAB_EVIDENCE",
                "reason": error, "partitions": {}}
    boot, vendor_scans = data
    source = boot["target_fstab"]["partitions"]
    from_ramdisk = {}
    for scan in vendor_scans:
        for item in scan.get("first_stage_fstab_dynamic_entries", []):
            if not isinstance(item, dict):
                continue
            mount = item.get("mountpoint")
            if isinstance(mount, str):
                from_ramdisk.setdefault(mount.lstrip("/"), []).append(item)
    comparison = {}
    mismatched = []
    checked = 0
    for name in PARTITIONS:
        vendor = source.get(name, {})
        vendor_entries = vendor.get("variants", []) if isinstance(vendor, dict) else []
        boot_entries = from_ramdisk.get(name, [])
        if not vendor_entries or not boot_entries:
            comparison[name] = {
                "status": "MISSING_EVIDENCE",
                "vendor_entry_count": len(vendor_entries),
                "ramdisk_entry_count": len(boot_entries),
            }
            mismatched.append(name)
            continue
        try:
            a = sorted({signature(x) for x in vendor_entries})
            b = sorted({signature(x) for x in boot_entries})
        except ValueError as exc:
            comparison[name] = {"status": "INVALID_METADATA", "reason": str(exc)}
            mismatched.append(name)
            continue
        checked += len(a)
        equal = a == b
        comparison[name] = {
            "status": "MATCHED_FSTAB_FLAGS" if equal else "MISMATCHED_FSTAB_FLAGS",
            "vendor_entries": [list(row) for row in a],
            "ramdisk_entries": [list(row) for row in b],
        }
        if not equal:
            mismatched.append(name)
    status = ("MATCHED_STRUCTURE_ONLY_NOT_BOOT_VERIFIED" if not mismatched
              else "DIFFERENT_OR_MISSING_FIRST_STAGE_FSTAB_RULES")
    return {**base, "status": status, "partitions": comparison,
            "partition_count": len(PARTITIONS),
            "matching_partition_count": len(PARTITIONS) - len(mismatched),
            "unique_rule_variants_compared": checked,
            "mismatched_partitions": mismatched,
            "unresolved": [
                "Full ramdisk init sequence and actual runtime mounts not proven",
                "AVB root digests and rebuilt super verification not proven",
                "No AOSP host checkvintf, SELinux combined-policy or device boot proof",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics_json", type=Path,
                        help="Existing one-shot summary.json; never a raw firmware image")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.diagnostics_json.is_symlink() or not args.diagnostics_json.is_file():
            raise ValueError("Missing diagnostics summary.json")
        obj = json.loads(args.diagnostics_json.read_text(encoding="utf-8"))
        if obj.get("target") != "SM-F741N" or obj.get("donor") != "SM-F956N":
            raise ValueError("Unexpected model pairing")
        result = evaluate(obj["sections"])
        if args.output:
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("Output already exists")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Fstab check error: " + str(exc) + "\n")
    print("F741N vendor/ramdisk fstab:", result["status"])
    print("Matching partitions:", result.get("matching_partition_count", "UNKNOWN"))
    print("Unique rule variants:", result.get("unique_rule_variants_compared", "UNKNOWN"))
    print("No firmware changes; boot and flash remain unverified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
