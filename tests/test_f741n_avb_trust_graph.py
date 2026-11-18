"""Synthetic stock F741N signed BL AVB trust graph tests, fail closed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_b6q_avb_trust_graph import audit


class AVBTrustGraphTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.work = self.root / "work"
        self.work.mkdir()
        (self.work / ".b6q-prepared").write_text("ok")
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        self.chain = self.root / "f741n-bl-vbmeta-chain.json"
        self.chain.write_text(json.dumps({
            "model": "SM-F741N",
            "phase": "READ_ONLY_STOCK_BL_VBMETA_CHAIN_INSPECTION",
            "stock_bl_vbmeta": {
                "header": {
                    "algorithm_type": 2,
                    "rollback_index": 5,
                    "rollback_index_location": 0,
                    "flags": 0,
                },
                "descriptors": [
                    {"type": "hashtree", "partition": "system"},
                    {"type": "hashtree", "partition": "product"},
                    {"type": "hashtree", "partition": "system_ext"},
                    {"type": "hashtree", "partition": "vendor"},
                    {"type": "chain partition", "partition": "dtbo"},
                    {"type": "chain partition", "partition": "prism"},
                    {"type": "chain partition", "partition": "optics"},
                ],
                "chain_targets": ["dtbo", "optics", "prism"],
            },
        }))

    def test_root_bl_signed_descriptors_overlap_all_modified(self):
        r = audit(self.work, self.chain)
        self.assertEqual(r["status"],
                         "BLOCKED_STOCK_BL_ROOT_HASHTREE_COVERS_REBUILT_SYSTEM")
        self.assertEqual(r["trust_graph"]["modified_partition_signed_descriptor_overlap"],
                         ["product", "system", "system_ext"])
        self.assertFalse(r["trust_graph"]["vbmeta_system_is_bl_chain_target"])
        self.assertFalse(r["root_signature_cryptographically_checked"])
        self.assertFalse(r["flashable"])

    def test_an_unchanged_root_does_not_prove_trust(self):
        data = json.loads(self.chain.read_text())
        data["stock_bl_vbmeta"]["descriptors"] = [
            {"type": "hashtree", "partition": "vendor"},
            {"type": "chain partition", "partition": "dtbo"},
        ]
        data["stock_bl_vbmeta"]["chain_targets"] = ["dtbo"]
        self.chain.write_text(json.dumps(data))
        r = audit(self.work, self.chain)
        self.assertEqual(r["status"], "UNKNOWN_NO_DIRECT_OVERLAP_BUT_TRUST_UNPROVEN")
        self.assertFalse(r["bootable"])

    def test_missing_old_descriptor_report_not_passed(self):
        self.chain.unlink()
        r = audit(self.work, self.chain)
        self.assertEqual(r["status"], "UNKNOWN_STOCK_AVB_TRUST_GRAPH_NOT_AVAILABLE")
        self.assertFalse(r["flashable"])

    def test_mismatch_chain_report_fails_closed(self):
        d = json.loads(self.chain.read_text())
        d["stock_bl_vbmeta"]["chain_targets"] = ["vbmeta_system"]
        self.chain.write_text(json.dumps(d))
        r = audit(self.work, self.chain)
        self.assertEqual(r["status"], "UNKNOWN_INCONSISTENT_STOCK_AVB_DESCRIPTORS")
        self.assertFalse(r["flashable"])

    def test_reject_wrong_donor(self):
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F946N",
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            audit(self.work, self.chain)

    def test_reject_wrong_descriptor_source(self):
        d = json.loads(self.chain.read_text())
        d["model"] = "SM-F956N"
        self.chain.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError, "Expected authentic"):
            audit(self.work, self.chain)


if __name__ == "__main__":
    unittest.main()
