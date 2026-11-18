"""Synthetic fail-closed tests for F741N required HAL interface/version contracts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_b6q_vintf_contracts import inspect, parse_ver


VENDOR_MATRIX = """<compatibility-matrix version="1.0" type="device">
<hal format="hidl">
 <name>android.hidl.memory</name><version>1.0</version>
 <interface><name>IMemory</name><instance>default</instance></interface>
</hal>
<hal format="hidl" optional="true">
 <name>android.hardware.optional</name><version>1.0</version>
 <interface><name>IFoo</name><instance>default</instance></interface>
</hal>
</compatibility-matrix>"""

FRAMEWORK = """<manifest version="1.0" type="framework">
<hal format="hidl">
 <name>android.hidl.memory</name><transport>hwbinder</transport>
 <fqname>@1.1::IMemory/default</fqname>
</hal>
</manifest>"""


class VintfContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        (self.work / ".b6q-prepared").write_text("ready")
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N"
        }))
        paths = ("system/system/etc/vintf/manifest.xml",
                 "vendor/etc/vintf/compatibility_matrix.xml",
                 "system_ext/etc", "product/etc", "odm/etc")
        for path in paths:
            p = self.work / path
            p.parent.mkdir(parents=True, exist_ok=True)
            if path.endswith(".xml"):
                p.write_text(FRAMEWORK if "manifest.xml" in path else VENDOR_MATRIX)
            else:
                p.mkdir(parents=True, exist_ok=True)

    def test_hidl_minor_version_satisfies_required_lower_version(self):
        result = inspect(self.work)
        self.assertEqual(result["status"], "HAL_CONTRACTS_MATCH_PARTIAL_NOT_LIBVINTF")
        self.assertEqual(result["required_entries"], 1)
        self.assertEqual(result["matched_entries"], 1)
        self.assertFalse(result["flashable"])

    def test_wrong_interface_instance_is_mismatch(self):
        p = self.work / "system/system/etc/vintf/manifest.xml"
        p.write_text(FRAMEWORK.replace("IMemory/default", "IMemory/other"))
        result = inspect(self.work)
        self.assertEqual(result["status"], "POSSIBLE_F741N_F956N_HAL_CONTRACT_MISMATCH")
        self.assertEqual(result["possible_mismatches"][0]["reason"],
                         "REQUIRED_INTERFACE_INSTANCE_NOT_PRESENT")

    def test_version_too_low_is_mismatch_candidate(self):
        p = self.work / "system/system/etc/vintf/manifest.xml"
        p.write_text(FRAMEWORK.replace("1.1", "1.0"))
        m = self.work / "vendor/etc/vintf/compatibility_matrix.xml"
        m.write_text(VENDOR_MATRIX.replace("1.0", "1.2"))
        result = inspect(self.work)
        self.assertEqual(result["status"], "POSSIBLE_F741N_F956N_HAL_CONTRACT_MISMATCH")
        self.assertEqual(result["possible_mismatches"][0]["reason"],
                         "REQUIRED_VERSION_NOT_MET")

    def test_malformed_xml_is_not_compatibility_pass(self):
        p = self.work / "system/system/etc/vintf/manifest.xml"
        p.write_text("<manifest")
        result = inspect(self.work)
        self.assertNotEqual(result["status"], "HAL_CONTRACTS_MATCH_PARTIAL_NOT_LIBVINTF")
        self.assertTrue(result["unsupported_xml"])

    def test_unknown_regex_instance_never_counts_as_full_match(self):
        p = self.work / "vendor/etc/vintf/compatibility_matrix.xml"
        p.write_text(VENDOR_MATRIX.replace(
            "<instance>default</instance>",
            "<regex-instance>default.*</regex-instance>",
        ))
        result = inspect(self.work)
        self.assertEqual(result["status"], "INCOMPLETE_XML_HAL_CONTRACT_AUDIT")
        self.assertFalse(result["libvintf_equivalence"])

    def test_wrong_models_rejected(self):
        (self.work / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F946N"
        }))
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            inspect(self.work)

    def test_version_parser_hidl_range_and_aidl(self):
        self.assertEqual(parse_ver("1.0-3", "hidl"), (1, 0, 3))
        self.assertEqual(parse_ver("1-3", "aidl"), (0, 1, 3))
        self.assertIsNone(parse_ver("untrusted", "hidl"))


if __name__ == "__main__":
    unittest.main()
