#!/usr/bin/env python3
"""Plan a DuyKhaiDeX F956N->F741N system-port using real super metadata.

Inputs are the JSON written by inspect_super_f741n_f956n.py plus
target/b6q/port-plan.json. This script NEVER extracts, repacks or flashes images.
A positive space estimate does NOT imply boot, DeX or framework compatibility.
"""
import argparse
import json
from pathlib import Path

EXPECTED = {"SM-F741N": "hardware_target", "SM-F956N": "system_donor"}
EXPECTED_GROUP = "qti_dynamic_partitions"
MIB = 1024 * 1024


def normalize(name):
    if name.endswith(("_a", "_b")):
        return name[:-2]
    return name


def partition_index(device):
    found = {}
    for item in device["partitions"]:
        name = normalize(item["name"])
        if name in found:
            raise ValueError(f"Duplicate normalized partition {name} in {device['model']}")
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            raise ValueError(f"Invalid partition size for {name} in {device['model']}")
        found[name] = item
    return found


def report_from_data(metadata, plan):
    if plan.get("status") != "ANALYSIS_ONLY_NOT_FLASHABLE":
        raise ValueError("Port plan is not marked as analysis-only")
    specs = plan.get("system_partition_sources", {})
    if not specs:
        raise ValueError("Port plan has no selected partitions")
    devices = {}
    for device in metadata.get("devices", []):
        model = device["model"]
        if model not in EXPECTED or model in devices:
            raise ValueError(f"Unexpected or duplicated model: {model}")
        if device.get("role") != EXPECTED[model]:
            raise ValueError(f"Wrong role for {model}")
        if device.get("checksums_valid") is not True:
            raise ValueError(f"Unverified metadata for {model}")
        if not str(device.get("header_version", "")).startswith("10."):
            raise ValueError(f"Unsupported LP metadata version for {model}")
        devices[model] = device
    if set(devices) != set(EXPECTED):
        raise ValueError("Need verified F741N AND F956N super metadata")
    target = devices["SM-F741N"]
    donor = devices["SM-F956N"]
    indexes = {name: partition_index(devices[name]) for name in EXPECTED}

    def group(device):
        matches = [g for g in device["groups"] if g["name"] == EXPECTED_GROUP]
        if len(matches) != 1:
            raise ValueError(f"Missing/nonunique {EXPECTED_GROUP} for {device['model']}")
        cap = matches[0]["maximum_bytes"]
        if not isinstance(cap, int) or cap <= 0:
            raise ValueError(f"Invalid group maximum for {device['model']}")
        return cap

    target_limit = group(target)
    donor_limit = group(donor)
    hybrid = []
    total = 0
    for partition, model in specs.items():
        if model not in devices:
            raise ValueError(f"Invalid firmware source for {partition}: {model}")
        if partition not in indexes["SM-F741N"]:
            raise ValueError(f"Partition {partition} absent on actual F741N layout")
        if partition not in indexes[model]:
            raise ValueError(f"Partition {partition} missing in source {model}")
        item = indexes[model][partition]
        if item["group"] != EXPECTED_GROUP:
            raise ValueError(f"Unexpected partition group for {partition} on {model}")
        size = item["bytes"]
        hybrid.append({"partition": partition, "source": model,
                       "current_image_bytes": size})
        total += size

    target_partitions = set(indexes["SM-F741N"])
    if set(specs) != target_partitions:
        raise ValueError("Plan partition set differs from F741N super layout: "
                         + str(sorted(target_partitions ^ set(specs))))
    available = target_limit - total
    return {
        "status": "CAPACITY_ESTIMATE_ONLY_NOT_BUILDABLE",
        "target_model": "SM-F741N", "donor_model": "SM-F956N",
        "target_group": EXPECTED_GROUP,
        "target_group_max_bytes": target_limit,
        "donor_group_max_bytes": donor_limit,
        "group_limit_delta_bytes": donor_limit - target_limit,
        "hybrid_partitions": hybrid,
        "hybrid_total_image_bytes": total,
        "estimated_remaining_bytes": available,
        "capacity_estimate_pass": available > 0,
        "checks_needed_before_build": [
            "Actual F741N super block-device sizes, reserved metadata, sparse layout and valid image packing",
            "Filesystem rebuild may change partition sizes: recalculate from final images",
            "Framework/vendor VINTF, SELinux, shipping API and native library compatibility",
            "DeX framework patches must be rebased from Fold5 to the exact Fold6 APK/JAR resources",
            "SM-F741N boot chain, device tree, kernel ABI, and verified recovery files",
        ],
        "note": "A positive size estimate is NOT proof of bootability or DeX compatibility.",
    }


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path,
                        default=root / "out/reports/f741n-f956n-super-metadata.json")
    parser.add_argument("--plan", type=Path, default=root / "target/b6q/port-plan.json")
    parser.add_argument("--output", type=Path,
                        default=root / "out/reports/f741n-f956n-port-capacity.json")
    args = parser.parse_args(argv)
    try:
        metadata = json.loads(args.metadata.read_text())
        plan = json.loads(args.plan.read_text())
        report = report_from_data(metadata, plan)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Port analysis failed: {exc}\n")

    print("DuyKhaiDeX F741N + F956N capacity analysis (not buildable yet)")
    for part in report["hybrid_partitions"]:
        print(f"  {part['partition']:<13} {part['source']:<8} "
              f"{part['current_image_bytes'] / MIB:,.1f} MiB")
    print(f"F741N group limit: {report['target_group_max_bytes'] / MIB:,.1f} MiB")
    print(f"Fold6 minus Flip6 group limit: {report['group_limit_delta_bytes'] / MIB:,.1f} MiB")
    print(f"Hybrid estimated total: {report['hybrid_total_image_bytes'] / MIB:,.1f} MiB")
    print(f"Estimated free capacity: {report['estimated_remaining_bytes'] / MIB:,.1f} MiB")
    print("Capacity estimate: " + ("PASS" if report["capacity_estimate_pass"] else "FAIL"))
    print("NOT A BOOTABLE ROM, no partition images modified or flashed.")
    print(f"Report: {args.output}")
    return 0 if report["capacity_estimate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
