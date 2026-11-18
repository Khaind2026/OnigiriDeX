#!/usr/bin/env python3
"""Conservative OFFLINE F741N device-matrix vs F956N framework HAL audit.

This is deliberately NOT libvintf and never certifies Android compatibility.
It checks mandatory HAL package/format/version/interface/instance where XML is
unambiguous, reporting unsupported layouts as UNKNOWN rather than PASS.
No firmware/image modifications, external downloads, or device commands.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from run_b6q_checkvintf import checked_work_tree, map_partitions

MAX_XML = 4 * 1024 * 1024
MAX_XML_FILES = 150
FQ_HIDL = re.compile(r"^@(\d+)\.(\d+)::([^/]+)/(.+)$")
FQ_AIDL = re.compile(r"^([^/@]+)/([^/]+)$")
HIDL_VER = re.compile(r"^(\d+)\.(\d+)(?:-(\d+))?$")
AIDL_VER = re.compile(r"^(\d+)(?:-(\d+))?$")


def tag(element):
    return element.tag.rsplit("}", 1)[-1]


def children(element, name):
    return [c for c in element if tag(c) == name]


def plain(element, name):
    return [(c.text or "").strip() for c in children(element, name)]


def parse_ver(string, kind):
    string = string.strip()
    m = (HIDL_VER if kind == "hidl" else AIDL_VER).fullmatch(string)
    if not m:
        return None
    if kind == "hidl":
        return (int(m.group(1)), int(m.group(2)),
                int(m.group(3)) if m.group(3) else int(m.group(2)))
    return (0, int(m.group(1)), int(m.group(2)) if m.group(2) else int(m.group(1)))


def specs(hal):
    """Extract interface-level tuples; supports new-style FQ names as well."""
    kinds = hal.get("format", "hidl").lower()
    if kinds not in ("hidl", "aidl"):
        return [], True
    names = plain(hal, "name")
    if len(names) != 1 or not names[0]:
        return [], True
    versions = [parse_ver(v, kinds) for v in plain(hal, "version")]
    uncertain = any(v is None for v in versions)
    if not versions:
        # A HIDL FQNAME contains a version, but old-style <interface>
        # without <version> does not. Distinguish these two layouts.
        if children(hal, "interface") or not plain(hal, "fqname"):
            uncertain = True
        versions = [None]
    requirements = []
    for interface in children(hal, "interface"):
        interfaces = plain(interface, "name")
        instances = plain(interface, "instance")
        regexes = plain(interface, "regex-instance")
        if len(interfaces) != 1 or not interfaces[0]:
            uncertain = True
            continue
        if regexes:
            uncertain = True  # libvintf regex matching required
        if not instances and not regexes:
            uncertain = True
        for instance in instances:
            if not instance:
                uncertain = True
                continue
            for v in versions:
                requirements.append((names[0], kinds, v, interfaces[0], instance))
    for fq in plain(hal, "fqname"):
        if kinds == "hidl":
            matched = FQ_HIDL.fullmatch(fq)
            if not matched:
                uncertain = True
                continue
            ver = (int(matched.group(1)), int(matched.group(2)),
                   int(matched.group(2)))
            iface, instance = matched.group(3), matched.group(4)
        else:
            matched = FQ_AIDL.fullmatch(fq)
            if not matched:
                uncertain = True
                continue
            iface, instance = matched.group(1), matched.group(2)
            if not versions or versions == [None]:
                uncertain = True
            ver = versions[0] if versions else None
        requirements.append((names[0], kinds, ver, iface, instance))
    if not requirements:
        uncertain = True
    return requirements, uncertain


def unexplained_hal_reasons(hal):
    """Classify why a HAL XML entry cannot be fully checked offline.

    Only static reason codes are for public status; source HAL names/paths stay
    in the local detailed report. This is not AOSP libvintf validation.
    """
    reasons = set()
    kind = hal.get("format", "hidl").lower()
    if kind not in ("hidl", "aidl"):
        return ["UNSUPPORTED_HAL_FORMAT"]
    names = plain(hal, "name")
    if len(names) != 1 or not names[0]:
        reasons.add("MISSING_OR_DUPLICATE_HAL_NAME")
    versions = plain(hal, "version")
    if not versions:
        reasons.add("VERSION_NOT_EXPLICIT")
    elif any(parse_ver(v, kind) is None for v in versions):
        reasons.add("UNSUPPORTED_VERSION_SYNTAX")
    for iface in children(hal, "interface"):
        if len(plain(iface, "name")) != 1:
            reasons.add("MISSING_OR_DUPLICATE_INTERFACE_NAME")
        if plain(iface, "regex-instance"):
            reasons.add("REGEX_INSTANCE_NEEDS_LIBVINTF")
        if not plain(iface, "instance") and not plain(iface, "regex-instance"):
            reasons.add("INSTANCE_NOT_EXPLICIT")
    for fq in plain(hal, "fqname"):
        if not (FQ_HIDL if kind == "hidl" else FQ_AIDL).fullmatch(fq):
            reasons.add("UNSUPPORTED_FQNAME_SYNTAX")
    if not children(hal, "interface") and not plain(hal, "fqname"):
        reasons.add("INTERFACE_NOT_EXPLICIT")
    if not reasons:
        reasons.add("UNMODELED_HAL_RULE")
    return sorted(reasons)


def compatible_version(required, offered, kind):
    """Return True, False or None when matching semantics cannot be asserted."""
    if required is None or offered is None:
        return None
    if kind == "hidl":
        if required[0] != offered[0]:
            return False
        # A provided HIDL minor version supports lower minor revisions.
        return offered[1] >= required[1]
    # For AIDL version ranges, newer versions may need libvintf semantics;
    # avoid falsely classifying newer-than-allowed as incompatible.
    if offered[1] < required[1]:
        return False
    if offered[1] > required[2]:
        return None
    return True


def parse_xml(path, expected):
    if path.is_symlink() or path.stat().st_size > MAX_XML:
        raise ValueError("Unsafe XML input")
    root = ET.fromstring(path.read_bytes())
    if tag(root) != expected:
        raise ValueError("Unexpected VINTF XML root type")
    return root


def inspect(work):
    checked_work_tree(work)
    roots = map_partitions(work)
    framework, required = [], []
    unknown_inputs = []
    parsed = {"manifest": 0, "device_matrix": 0}
    for part in ("system", "system_ext", "product", "vendor", "odm"):
        folder = roots[part] / "etc/vintf"
        if not folder.is_dir() or folder.is_symlink():
            continue
        files = sorted(folder.glob("*.xml")) + sorted((folder / "manifest").glob("*.xml"))
        if len(files) > MAX_XML_FILES:
            raise ValueError("Excessive VINTF XML count")
        for path in files:
            name = path.name
            if part in ("vendor", "odm") and name.startswith("compatibility_matrix"):
                expected, role = "compatibility-matrix", "device_matrix"
            elif part in ("system", "system_ext", "product") and (
                    name == "manifest.xml" or path.parent.name == "manifest"):
                expected, role = "manifest", "manifest"
            else:
                continue
            try:
                root = parse_xml(path, expected)
                actual_type = root.attrib.get("type", "")
                correct_type = "device" if role == "device_matrix" else "framework"
                if actual_type and actual_type != correct_type:
                    continue
                parsed[role] += 1
                for hal in children(root, "hal"):
                    if role == "device_matrix" and hal.attrib.get("optional") == "true":
                        continue
                    rows, unknown = specs(hal)
                    dest = required if role == "device_matrix" else framework
                    dest.extend(rows)
                    if unknown:
                        pkg = plain(hal, "name")
                        unknown_inputs.append({
                            "role": role, "hal": pkg[0] if pkg else "UNKNOWN",
                            "issue": "UNSUPPORTED_XML_HAL_LAYOUT",
                            "reasons": unexplained_hal_reasons(hal),
                            "source_file": str(path.relative_to(work)),
                        })
            except (ET.ParseError, OSError, ValueError) as exc:
                unknown_inputs.append({
                    "role": role, "file": path.name,
                    "issue": "VINTF_XML_PARSE_OR_FORMAT_ERROR",
                    "reasons": ["XML_PARSE_OR_FORMAT_ERROR"],
                    "source_file": str(path.relative_to(work)),
                })
    matched, absent, unresolved = [], [], []
    for name, kind, version, iface, instance in sorted(set(required), key=str):
        same = [entry for entry in framework
                if entry[0] == name and entry[1] == kind
                and entry[3] == iface and entry[4] == instance]
        key = {"hal": name, "format": kind, "interface": iface,
               "instance": instance, "version": version}
        if not same:
            if name in [r["hal"] for r in unknown_inputs if r["role"] == "manifest"
                        and "hal" in r]:
                unresolved.append({**key, "reason": "FRAMEWORK_HAL_PARSE_UNCERTAIN"})
            else:
                absent.append({**key, "reason": "REQUIRED_INTERFACE_INSTANCE_NOT_PRESENT"})
            continue
        results = [compatible_version(version, entry[2], kind) for entry in same]
        if True in results:
            matched.append(key)
        elif None in results:
            unresolved.append({**key, "reason": "VERSION_SEMANTICS_UNKNOWN"})
        else:
            absent.append({**key, "reason": "REQUIRED_VERSION_NOT_MET"})
    if parsed["device_matrix"] == 0 or parsed["manifest"] == 0:
        status = "UNKNOWN_MISSING_DEVICE_MATRIX_OR_FRAMEWORK_MANIFEST"
    elif unknown_inputs or unresolved or not required:
        status = "INCOMPLETE_XML_HAL_CONTRACT_AUDIT"
    elif absent:
        status = "POSSIBLE_F741N_F956N_HAL_CONTRACT_MISMATCH"
    else:
        status = "HAL_CONTRACTS_MATCH_PARTIAL_NOT_LIBVINTF"
    # Provide strictly allowlisted reason counts to the public status bridge.
    # This can explain INCOMPLETE even when all required HALs matched.
    reason_counts = {}
    role_reason_counts = {}
    for item in unknown_inputs:
        for reason in item.get("reasons", ["UNMODELED_HAL_RULE"]):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            key = item["role"] + "__" + reason
            role_reason_counts[key] = role_reason_counts.get(key, 0) + 1
    # Evidence for missing source files or unmatched required interface
    # requirements is kept separate from unrelated XML layout uncertainty.
    incomplete_causes = []
    if unknown_inputs:
        incomplete_causes.append("UNMODELED_XML_HAL_ENTRIES")
    if unresolved:
        incomplete_causes.append("REQUIRED_HAL_VERSION_OR_INTERFACE_UNKNOWN")
    if absent:
        incomplete_causes.append("POSSIBLE_MISSING_REQUIRED_HAL_CONTRACT")
    if parsed["device_matrix"] == 0 or parsed["manifest"] == 0:
        incomplete_causes.append("MISSING_COMPATIBILITY_XML_SOURCE")
    if not required:
        incomplete_causes.append("NO_EXPLICIT_REQUIRED_INTERFACE_ENTRIES")
    # Even perfect name/interface/instance matches do not validate Android
    # framework FCM selection, APEX, kernel config or HAL runtime services.
    return {
        "target": "SM-F741N", "donor": "SM-F956N",
        "phase": "F741N_REQUIRED_DEVICE_HAL_CONTRACTS_VS_F956N_FRAMEWORK",
        "status": status, "parsed_sources": parsed,
        "required_entries": len(set(required)), "matched_entries": len(matched),
        "possible_mismatches": absent[:100], "uncertain_requirements": unresolved[:100],
        "unsupported_xml": unknown_inputs[:100],
        "unsupported_xml_total": len(unknown_inputs),
        "unsupported_reason_counts": dict(sorted(reason_counts.items())),
        "unsupported_role_reason_counts": dict(sorted(role_reason_counts.items())),
        "incomplete_cause_codes": incomplete_causes,
        "required_fully_matched": bool(required) and len(matched) == len(set(required))
                                   and not unresolved and not absent,
        "libvintf_equivalence": False, "kernel_check_performed": False,
        "runtime_verified": False, "flashable": False, "bootable": False,
    }


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path,
                        default=root / "out/target/b6q/SM-F741N/work_dir")
    parser.add_argument("--output", type=Path,
                        default=root / "out/b6q/analysis/f741n-required-hal-contracts.json")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Output already exists")
        result = inspect(args.work_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, "VINTF contract audit failed: " + str(exc) + "\n")
    print("F741N required framework HAL contracts:", result["status"])
    print("Matched:", result["matched_entries"], "/", result["required_entries"])
    print("Never equivalent to full checkvintf. NO ODIN AP; DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
