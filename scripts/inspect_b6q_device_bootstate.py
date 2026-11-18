#!/usr/bin/env python3
"""Optional READ-ONLY F741N bootloader status snapshot over authorized ADB.

Only safe getprop calls are sent; never requests root/unlock, never writes
partitions, never captures IMEI, subscriber IDs, account data or device serial.
The report never authorizes flashing or represents cryptographic evidence.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

PROPERTIES = (
    "ro.product.model",
    "ro.product.vendor.model",
    "ro.boot.vbmeta.device_state",
    "ro.boot.verifiedbootstate",
    "ro.boot.flash.locked",
    "ro.boot.veritymode",
    "ro.boot.bootloader",
    "ro.build.version.incremental",
)


def exec_adb(adb, args, timeout=12):
    return subprocess.run(
        [str(adb), *args],
        capture_output=True, text=True, check=False, timeout=timeout,
    )


def inspect(adb=None):
    report = {
        "model_expected": "SM-F741N",
        "phase": "OPTIONAL_READ_ONLY_ADB_BOOTLOADER_STATUS",
        "status": "NOT_RUN",
        "flashable": False, "bootable": False,
        "trusted_attestation": False,
        "device_identifier_included": False,
        "notes": [
            "Unauthenticated getprop is not a cryptographic bootloader attestation",
            "No root, flashing, unlocking, wiping, firmware edits or device recovery actions",
            "Device state should be verified manually before a controlled hardware test",
        ],
    }
    binary = adb or shutil.which("adb")
    if not binary:
        report["status"] = "NOT_RUN_ADB_UNAVAILABLE"
        return report
    try:
        devices = exec_adb(binary, ["devices"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        report["status"] = "NOT_RUN_ADB_ERROR"
        report["reason"] = type(exc).__name__
        return report
    if devices.returncode != 0:
        report["status"] = "NOT_RUN_ADB_ERROR"
        return report
    # The device serial is parsed transiently to count devices, not written
    # into the report, logs, or emitted anywhere.
    rows = [line.split() for line in devices.stdout.splitlines()[1:]
            if line.strip()]
    authorized = [r for r in rows if len(r) >= 2 and r[1] == "device"]
    if len(authorized) != 1 or len(rows) != 1:
        report["status"] = "NOT_RUN_EXACTLY_ONE_AUTHORIZED_DEVICE_REQUIRED"
        report["connected_count"] = len(rows)
        report["authorized_count"] = len(authorized)
        return report
    properties = {}
    for name in PROPERTIES:
        try:
            response = exec_adb(binary, ["shell", "getprop", name])
        except (OSError, subprocess.TimeoutExpired):
            report["status"] = "NOT_RUN_PROPERTY_QUERY_FAILED"
            return report
        if response.returncode:
            report["status"] = "NOT_RUN_PROPERTY_QUERY_FAILED"
            return report
        value = response.stdout.strip()
        if len(value) > 128:
            report["status"] = "NOT_RUN_UNEXPECTED_PROPERTY_LENGTH"
            return report
        properties[name] = value
    model = properties.get("ro.product.vendor.model") or properties.get("ro.product.model")
    if model != "SM-F741N":
        report["status"] = "NOT_RUN_NON_F741N_DEVICE"
        # Do not disclose model details of unrelated connected devices.
        return report
    report["properties"] = properties
    if (properties.get("ro.boot.vbmeta.device_state") == "unlocked"
            or properties.get("ro.boot.flash.locked") == "0"):
        report["status"] = "DEVICE_REPORTS_UNLOCKED_NOT_ATTESTED"
    elif (properties.get("ro.boot.vbmeta.device_state") == "locked"
          or properties.get("ro.boot.flash.locked") == "1"):
        report["status"] = "DEVICE_REPORTS_LOCKED_CUSTOM_ROM_BLOCKED"
    else:
        report["status"] = "DEVICE_BOOTLOADER_STATE_UNKNOWN"
    return report


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=None)
    parser.add_argument("--output", type=Path,
                        default=root / "out/b6q/analysis/f741n-adb-bootloader-status.json")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Refusing to overwrite existing report")
        report = inspect(args.adb)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError) as error:
        parser.exit(1, "F741N ADB status audit error: " + str(error) + "\n")
    print("F741N ADB Verified Boot property inspection:", report["status"])
    print("No serial or personal data collected; no device changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
