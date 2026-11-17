"""Offline tests for Fold6/Flip6 DeX candidate report summarization."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from report_b6q_dex_candidates import summarize, format_summary


def mock_audit():
    return {
        "status": "ANALYSIS_ONLY_NO_ROM",
        "devices": [
            {
                "model": "SM-F956N",
                "partitions": [
                    {
                        "partition": "system",
                        "build_prop": {"properties": {"ro.build.version.sdk": "35"}},
                        "directory_probe": {
                            "/system/priv-app": {"present": True, "matching_names": [
                                "KnoxDesktopLauncher", "DesktopModeUiService",
                                "DesktopSystemUI", "SystemUI"]},
                            "/system/etc/permissions": {"present": True, "matching_names": [
                                "privapp-permissions-com.sec.android.app.desktoplauncher.xml"
                            ]}
                        },
                        "vintf": {
                            "/etc/vintf/manifest.xml": {
                                "parsed": True, "target_level": "8", "hal_count": 2,
                                "hal_names": ["android.hardware.graphics.composer3",
                                              "android.hardware.camera.provider"]
                            }
                        }
                    }
                ]
            },
            {
                "model": "SM-F741N",
                "partitions": [
                    {
                        "partition": "vendor",
                        "build_prop": {"properties": {
                            "ro.product.vendor.device": "b6q",
                            "ro.vendor.build.version.sdk": "34"
                        }},
                        "directory_probe": {
                            "/lib64/hw": {"present": True, "matching_names": [
                                "android.hardware.graphics.composer3-service.so"
                            ]}
                        },
                        "vintf": {
                            "/etc/vintf/manifest.xml": {
                                "parsed": True, "target_level": "8", "hal_count": 1,
                                "hal_names": ["android.hardware.graphics.composer3"]
                            }
                        }
                    }
                ]
            }
        ]
    }


class DeXReportTests(unittest.TestCase):
    def test_matches_all_three_original_dex_apks(self):
        results = summarize(mock_audit())
        hits = results["candidate_listing_matches"]["SM-F956N"]
        for name in ("KnoxDesktopLauncher", "DesktopModeUiService", "DesktopSystemUI"):
            self.assertEqual(len(hits[name]), 1)
        self.assertEqual(
            results["properties"]["SM-F741N"]["ro.product.vendor.device"], "b6q")
        self.assertEqual(
            results["properties"]["SM-F956N"]["ro.build.version.sdk"], "35")
        self.assertIn("android.hardware.graphics.composer3",
                      results["vintf"]["SM-F741N"][0]["graphics_and_display_hals"])

    def test_missing_components_are_not_claimed_absent(self):
        results = summarize(mock_audit())
        rendered = format_summary(results)
        self.assertIn("NOT SEEN (does not prove absent)", rendered)
        self.assertIn("KnoxDesktopLauncher: LISTED", rendered)
        self.assertIn("Only name evidence", rendered)

    def test_wrong_model_rejected(self):
        bad = mock_audit()
        bad["devices"][1]["model"] = "SM-F956B"
        with self.assertRaisesRegex(ValueError, "one Flip6 target"):
            summarize(bad)

    def test_wrong_report_status_rejected(self):
        bad = mock_audit()
        bad["status"] = "BUILT"
        with self.assertRaisesRegex(ValueError, "Not a DuyKhaiDeX"):
            summarize(bad)

    def test_missing_optional_directory_gracefully_handled(self):
        bad = mock_audit()
        bad["devices"][0]["partitions"][0]["directory_probe"]["/system/priv-app"] = {
            "present": False, "reason": "not found"
        }
        summary = summarize(bad)
        self.assertFalse(summary["candidate_listing_matches"]["SM-F956N"]["DesktopSystemUI"])


if __name__ == "__main__":
    unittest.main()
