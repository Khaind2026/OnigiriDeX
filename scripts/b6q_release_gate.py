#!/usr/bin/env python3
"""Make a fail-closed F741N/F956N ROM release-gate report from actual evidence.

This is a decision engine, not a ROM builder, Odin packager, AVB signer or
device flasher. No single positive source-level check proves bootability.
"""
import argparse
import json
from pathlib import Path
import sys


def gate(status, detail, next_action):
    return {"status": status, "evidence": detail, "next_action": next_action}


def evaluate(sections):
    if not isinstance(sections, dict):
        raise ValueError("Missing DuyKhaiDeX diagnostics sections")

    staged = sections.get("stock_stage_validation", {})
    boot = sections.get("boot_chain", {})
    work = sections.get("rom_work_tree", {})
    fstab = sections.get("fstab_consistency", {})
    if not isinstance(fstab, dict) or not fstab.get("status"):
        # Older ZIPs predate the first-stage comparison integration.
        try:
            from compare_b6q_first_stage_fstab import evaluate as compare
            fstab = compare(sections)
        except (ValueError, KeyError, TypeError, ImportError):
            fstab = {"status": "UNKNOWN_INSUFFICIENT_FSTAB_EVIDENCE"}
    host = sections.get("host_checkvintf", {})
    selinux = sections.get("selinux_inputs", {})
    avb = sections.get("avb_descriptor_summary", {})
    preview = sections.get("super_preview", {})
    gates = {}

    stage_ok = staged.get("result") == "OK_IMAGE_SIZE_AND_FS_ONLY"
    gates["source_partition_stage"] = gate(
        "PASS_OFFLINE" if stage_ok else "BLOCKED_UNKNOWN",
        "Staged original partition image sizes and filesystem types only",
        "Validate staged original F741N/F956N images before repacking",
    )
    boot_ok = boot.get("result") == "STOCK_IMAGE_HASHES_MATCH_STAGE_MANIFEST_NOT_BOOT_VERIFIED"
    gates["stock_f741n_boot_checksum"] = gate(
        "PASS_OFFLINE" if boot_ok else "BLOCKED_UNKNOWN",
        "Manifest hash agreement of original F741N boot images, not ROM startup",
        "Check exact F741N stock boot assets and matching build revision",
    )
    fstab_ok = fstab.get("status") == "MATCHED_STRUCTURE_ONLY_NOT_BOOT_VERIFIED"
    gates["first_stage_fstab_metadata"] = gate(
        "PASS_OFFLINE" if fstab_ok else "BLOCKED_UNKNOWN",
        str(fstab.get("status", "No first-stage fstab comparison")),
        "Compare target F741N vendor_boot fstab against target vendor partition",
    )
    markers = work.get("markers", {}) if isinstance(work, dict) else {}
    patched = bool(markers.get(".b6q-prepared") and markers.get(".b6q-dex-patched"))
    gates["dex_source_patch"] = gate(
        "PASS_SOURCE_ONLY" if patched else "BLOCKED_UNKNOWN",
        "Local DeX patch marker, NOT an APK/JAR runtime or screen output test",
        "Inspect DeX patch build logs and enable a controlled target device test",
    )
    gates["aosp_checkvintf"] = gate(
        "PASS_HOST_ONLY" if host.get("status") == "HOST_VINTF_CHECK_PASSED_RUNTIME_UNVERIFIED"
        else "BLOCKED_NOT_VERIFIED",
        host.get("status", "No official checkvintf run"),
        "Provide/build official host checkvintf and check full FCM/SKU/APEX/kernel data",
    )
    se_state = selinux.get("status", "NO_SELINUX_INSPECTION")
    compile_report = sections.get("selinux_host_compile", {})
    if not isinstance(compile_report, dict):
        compile_report = {}
    compiler_state = compile_report.get("status", "NOT_RUN")
    if compiler_state == "HOST_SELINUX_COMPILE_PASSED_RUNTIME_UNVERIFIED":
        se_gate_state = "BLOCKED_HOST_COMPILED_DEVICE_POLICY_NOT_VERIFIED"
    elif compiler_state == "HOST_SELINUX_COMPILE_FAILED":
        se_gate_state = "BLOCKED_HOST_SELINUX_COMPILE_FAILED"
    else:
        se_gate_state = "BLOCKED_NOT_COMPILED"
    gates["combined_selinux_policy"] = gate(
        se_gate_state,
        {"policy_mapping": se_state, "host_compile": compiler_state,
         "host_neverallow": compile_report.get("neverallow_check", "NOT_RUN")},
        "Resolve actual secilc failures, verify policy and mapping with AOSP init semantics, and validate combined policy on SM-F741N",
    )

    impacted = avb.get("modified_partition_overlap") or []
    if impacted:
        avb_state = "BLOCKED_STOCK_SIGNED_HASHTREES_OVERLAP_MODIFIED_PARTITIONS"
    else:
        avb_state = "BLOCKED_AVB_CHAIN_UNPROVEN"
    gates["avb_trust_chain"] = gate(
        avb_state,
        {"signed_stock_root_hashtree_overlap": impacted,
         "engineering_preview_no_avb": True},
        "Establish legitimate device-specific unlocked-bootloader/AVB policy and verify built partition digests and rollback behavior; stock Samsung signatures cannot be assumed to authenticate rebuilt data",
    )

    gates["super_preview_integrity"] = gate(
        "PASS_PREVIEW_PRESENT_NOT_FOR_FLASH" if preview.get("present") else "BLOCKED_PREVIEW_MISSING",
        {"present": bool(preview.get("present")),
         "hash_recomputed": bool(preview.get("hash_recomputed", False))},
        "Only after boot/AVB/VINTF/SELinux proofs, re-hash and review final super layout; never flash the existing preview",
    )
    adb_evidence = sections.get("adb_device_bootstate", {})
    if not isinstance(adb_evidence, dict):
        adb_evidence = {}
    device_state = adb_evidence.get("status", "NOT_RUN")
    if device_state == "DEVICE_REPORTS_LOCKED_CUSTOM_ROM_BLOCKED":
        bootloader_gate_status = "BLOCKED_DEVICE_REPORTS_LOCKED"
    elif device_state == "DEVICE_REPORTS_UNLOCKED_NOT_ATTESTED":
        bootloader_gate_status = "BLOCKED_UNLOCKED_REPORTED_ROLLBACK_UNVERIFIED"
    else:
        bootloader_gate_status = "BLOCKED_DEVICE_EVIDENCE_MISSING"
    gates["bootloader_state_and_rollback"] = gate(
        bootloader_gate_status,
        "Read-only bootloader property result: " + device_state +
        "; rollback indices and OEM trust not cryptographically verified",
        "Verify actual F741N bootloader state, rollback compatibility and exact firmware revision before any recoverable test",
    )
    gates["recovery_and_hardware_validation"] = gate(
        "BLOCKED_DEVICE_EVIDENCE_MISSING",
        "No tested device-specific restore, boot, radio, folding-state, DeX or HDMI Hz results",
        "Validate stock recovery path and controlled F741N hardware checks before release",
    )

    order = [
        "avb_trust_chain",
        "aosp_checkvintf",
        "combined_selinux_policy",
        "bootloader_state_and_rollback",
        "recovery_and_hardware_validation",
    ]
    blockers = [key for key, item in gates.items()
                if item["status"].startswith("BLOCKED")]
    return {
        "target": "SM-F741N", "donor": "SM-F956N",
        "rom_name": "DuyKhaiDeX",
        "status": "BLOCKED_FOR_RELEASE_UNVERIFIED_BOOT_AND_AVB",
        "release_allowed": False, "odin_ap_allowed": False,
        "flashable": False, "bootable": False,
        "gates": gates, "blockers": blockers,
        "critical_path_order": order,
        "notes": [
            "PASS_OFFLINE and PASS_SOURCE_ONLY are not permission to flash",
            "Stock F741N BL/CP/boot/DTBO and hardware-specific partitions must not be replaced with F956N",
            "Signed Samsung AVB descriptors for stock dynamic partitions do not authenticate a rebuilt F956N-derived super",
            "No Android handset test or signed flashable artifact has been produced",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path, help="JSON summary from one-shot diagnostics")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.summary.read_text(encoding="utf-8"))
        if data.get("target") != "SM-F741N" or data.get("donor") != "SM-F956N":
            raise ValueError("Unsupported ROM device pairing")
        result = evaluate(data["sections"])
        if args.output:
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("Refusing to overwrite existing report")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, "Release gate failed: " + str(error) + "\n")
    print("DuyKhaiDeX F741N gate:", result["status"])
    for key in result["critical_path_order"]:
        entry = result["gates"][key]
        print(" -", key, ":", entry["status"])
    print("No flashable Odin AP was built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
