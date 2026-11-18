#!/usr/bin/env python3
"""Read-only F956N framework vs F741N vendor VINTF/fstab triage.

Reads the existing extracted DuyKhaiDeX b6q work tree. XML name comparison is
only a diagnostic: full Android libvintf/FCM, SKU, APEX and boot ramdisk checks
remain necessary before considering a ROM bootable. No writes to firmware.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

MODEL = "SM-F741N"
DONOR = "SM-F956N"
MAX_XML = 2 * 1024 * 1024
MAX_XML_FILES = 160
MOUNT_HINTS = ("first_stage_mount", "logical", "avb", "slotselect", "system", "vendor", "product", "odm")
PARTITION_VINTF = {
    "system": "system/system/etc/vintf",
    "system_ext": "system_ext/etc/vintf",
    "product": "product/etc/vintf",
    "vendor": "vendor/etc/vintf",
    "odm": "odm/etc/vintf",
}
PROPS = {
    "system": "system/system/build.prop",
    "vendor": "vendor/build.prop",
}
PROP_KEYS = {
    "ro.build.version.sdk",
    "ro.build.version.release",
    "ro.product.vendor.device",
    "ro.vendor.build.version.sdk",
    "ro.product.first_api_level",
    "ro.board.first_api_level",
}


def collect_xml(folder: Path):
    if not folder.is_dir() or folder.is_symlink():
        return []
    found = []
    for current, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
        for name in sorted(files):
            file = Path(current) / name
            if name.endswith(".xml") and not file.is_symlink() and file.is_file():
                if len(found) >= MAX_XML_FILES:
                    raise ValueError("Excessive VINTF XML file count")
                if file.stat().st_size > MAX_XML:
                    raise ValueError("Oversized VINTF XML: " + str(file))
                found.append(file)
    return found


def get_hal_names(element):
    result = set()
    for hal in element.findall(".//hal"):
        name = hal.findtext("name")
        if name and name.strip():
            result.add(name.strip())
    return result


def parse_vintf(file: Path, root: Path):
    try:
        xml = ET.fromstring(file.read_bytes())
    except ET.ParseError as error:
        return {"file": str(file.relative_to(root)), "parsed": False, "error": str(error)}
    if xml.tag not in ("manifest", "compatibility-matrix"):
        return {"file": str(file.relative_to(root)), "parsed": False,
                "error": "not a VINTF manifest or compatibility-matrix"}
    required, optional = set(), set()
    for hal in xml.findall("./hal"):
        name = hal.findtext("name")
        if not name or not name.strip():
            continue
        name = name.strip()
        if xml.tag == "compatibility-matrix" and hal.get("optional") == "true":
            optional.add(name)
        else:
            required.add(name)
    return {
        "file": str(file.relative_to(root)),
        "parsed": True, "kind": xml.tag,
        "level": xml.attrib.get("level"),
        "target_level": xml.attrib.get("target-level"),
        "required_hal_names": sorted(required),
        "optional_hal_names": sorted(optional),
        "hal_count": len(required | optional),
    }


def props_file(file: Path):
    if not file.is_file() or file.is_symlink():
        return {"present": False}
    if file.stat().st_size > MAX_XML:
        raise ValueError("Unexpectedly large build.prop")
    result = {}
    for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k in PROP_KEYS:
            result[k] = v
    return {"present": True, "properties": result}


def fstab_probe(root: Path):
    records = []
    for label in ("vendor", "odm"):
        folder = root / label / "etc"
        if not folder.is_dir() or folder.is_symlink():
            continue
        for current, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
            for name in sorted(files):
                if not name.startswith("fstab."):
                    continue
                file = Path(current) / name
                if file.is_symlink() or not file.is_file():
                    continue
                if file.stat().st_size > MAX_XML:
                    raise ValueError("Oversized fstab: " + str(file))
                rules = []
                for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if any(keyword in stripped for keyword in MOUNT_HINTS):
                        columns = stripped.split()
                        rules.append({"device": columns[0], "mountpoint": columns[1]
                                      if len(columns) > 1 else None,
                                      "mentions_avb": "avb" in stripped,
                                      "mentions_first_stage": "first_stage_mount" in stripped,
                                      "mentions_logical": "logical" in stripped})
                records.append({"file": str(file.relative_to(root)), "matching_rules": rules[:100]})
    return records


def analyze(root: Path):
    if root.is_symlink() or not root.is_dir() or not (root / ".b6q-prepared").is_file():
        raise ValueError("Existing verified b6q prepared work tree not found; run port_b6q.sh prepare")
    origin = root / "port-origin.json"
    if origin.is_symlink() or not origin.is_file():
        raise ValueError("b6q port-origin.json missing")
    meta = json.loads(origin.read_text(encoding="utf-8"))
    if meta.get("target") != MODEL or meta.get("donor") != DONOR:
        raise ValueError("Unexpected target/donor in b6q work tree")
    entries = {}
    for partition, relative in PARTITION_VINTF.items():
        entries[partition] = [parse_vintf(f, root) for f in collect_xml(root / relative)]
    framework = set()
    vendor = set()
    framework_files = []
    for part, data in entries.items():
        for record in data:
            if not record.get("parsed"):
                continue
            if part in ("system", "system_ext", "product") and record["kind"] == "compatibility-matrix":
                framework.update(record["required_hal_names"])
                framework_files.append(record["file"])
            if part in ("vendor", "odm") and record["kind"] == "manifest":
                vendor.update(record["required_hal_names"])
    # This is a broad list of candidate mismatches, NOT a checkvintf result:
    # multiple FCM levels, optional requirements, SKU and APEX fragments apply.
    candidates = sorted(framework - vendor)
    properties = {p: props_file(root / path) for p, path in PROPS.items()}
    mounts = fstab_probe(root)
    return {
        "target": MODEL, "donor": DONOR,
        "phase": "READ_ONLY_VINTF_FSTAB_TRIAGE",
        "status": "NEEDS_FULL_VINTF_AND_FIRST_STAGE_MOUNT_VERIFICATION",
        "flashable": False,
        "vintf_xml": entries,
        "framework_matrix_files": framework_files,
        "framework_required_hal_names": sorted(framework),
        "device_manifest_hal_names": sorted(vendor),
        "candidate_missing_hal_names_unverified": candidates,
        "properties": properties,
        "fstab_probes": mounts,
        "unresolved": [
            "Full Android checkvintf with assembled FCM level, SKU and all XML/APEX fragments has NOT been run",
            "Exact HAL interface/version/instance requirements have NOT been checked",
            "F741N vendor_boot/init_boot first-stage fstab and boot mounting have NOT been inspected",
            "SELinux policy compatibility and services.jar patch boot behavior have NOT been validated",
            "AVB0 parsing does not validate stock signatures or rebuilt super hashtrees",
            "No F741N handset boot or DeX hardware validation",
        ],
        "notes": [
            "Missing HAL names are investigation candidates, not confirmed incompatibilities",
            "This reads prepared files; it does not modify files, create an Odin AP, or flash",
            "Never install F956N kernel, bootloader, dtbo or modem on F741N",
        ]
    }


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path,
                        default=repo / "out/target/b6q/SM-F741N/work_dir")
    parser.add_argument("--output", type=Path,
                        default=repo / "out/b6q/analysis/f741n-f956n-vintf-mount-triage.json")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Report exists, refusing overwrite: " + str(args.output))
        result = analyze(args.work_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(1, "F741N/F956N VINTF/mount triage failed: " + str(error) + "\n")
    print("Target F741N vendor/odm HAL names:", len(result["device_manifest_hal_names"]))
    print("Donor F956N framework FCM required HAL names:", len(result["framework_required_hal_names"]))
    print("Missing-name candidates (NOT confirmed failures):",
          len(result["candidate_missing_hal_names_unverified"]))
    for name in result["candidate_missing_hal_names_unverified"][:30]:
        print("  CANDIDATE:", name)
    print("Stock vendor/odm fstab files:", len(result["fstab_probes"]))
    print("STATUS:", result["status"])
    print("Report:", args.output)
    print("READ ONLY. NO ODIN AP. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
