"""Offline tests for fail-closed F741N ROM release readiness."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from b6q_release_gate import evaluate


def sections():
    return {
        "stock_stage_validation": {"result": "OK_IMAGE_SIZE_AND_FS_ONLY"},
        "boot_chain": {"result": "STOCK_IMAGE_HASHES_MATCH_STAGE_MANIFEST_NOT_BOOT_VERIFIED"},
        "rom_work_tree": {"markers": {
            ".b6q-prepared": True, ".b6q-dex-patched": True}},
        "fstab_consistency": {"status": "MATCHED_STRUCTURE_ONLY_NOT_BOOT_VERIFIED"},
        "host_checkvintf": {
            "status": "HOST_VINTF_CHECK_PASSED_RUNTIME_UNVERIFIED"
        },
        "selinux_inputs": {
            "status": "SELINUX_FILES_PRESENT_COMBINED_POLICY_NOT_VERIFIED"
        },
        "avb_descriptor_summary": {
            "modified_partition_overlap": ["product", "system", "system_ext"]
        },
        "super_preview": {"present": True, "hash_recomputed": True},
    }


class ReleaseReadinessTests(unittest.TestCase):
    def test_all_offline_gates_cannot_claim_flashability(self):
        report = evaluate(sections())
        self.assertFalse(report["release_allowed"])
        self.assertFalse(report["odin_ap_allowed"])
        self.assertFalse(report["flashable"])
        self.assertFalse(report["bootable"])
        self.assertEqual(report["gates"]["first_stage_fstab_metadata"]["status"],
                         "PASS_OFFLINE")
        self.assertEqual(report["gates"]["dex_source_patch"]["status"],
                         "PASS_SOURCE_ONLY")
        self.assertIn("BLOCKED_STOCK_SIGNED_HASHTREES_OVERLAP_MODIFIED_PARTITIONS",
                      report["gates"]["avb_trust_chain"]["status"])

    def test_missing_checkvintf_is_a_blocker(self):
        evidence = sections()
        evidence["host_checkvintf"]["status"] = "NOT_RUN_CHECKVINTF_MISSING"
        report = evaluate(evidence)
        self.assertEqual(report["gates"]["aosp_checkvintf"]["status"],
                         "BLOCKED_NOT_VERIFIED")
        self.assertFalse(report["release_allowed"])

    def test_missing_fstab_evidence_is_not_a_pass(self):
        evidence = sections()
        evidence["fstab_consistency"] = {"status": "UNKNOWN_INSUFFICIENT_FSTAB_EVIDENCE"}
        report = evaluate(evidence)
        self.assertEqual(report["gates"]["first_stage_fstab_metadata"]["status"],
                         "BLOCKED_UNKNOWN")

    def test_avb_missing_evidence_still_blocks(self):
        evidence = sections()
        evidence["avb_descriptor_summary"] = {}
        report = evaluate(evidence)
        self.assertEqual(report["gates"]["avb_trust_chain"]["status"],
                         "BLOCKED_AVB_CHAIN_UNPROVEN")
        self.assertFalse(report["odin_ap_allowed"])

    def test_empty_evidence_never_authorizes_release(self):
        report = evaluate({})
        self.assertTrue(report["blockers"])
        self.assertFalse(report["flashable"])
        self.assertEqual(report["target"], "SM-F741N")


if __name__ == "__main__":
    unittest.main()
