"""Fixture tests protect packaging checks; they do not emulate a working RustDesk client."""
import importlib.util
import plistlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/verify_artifact.py"
SPEC = importlib.util.spec_from_file_location("verify_artifact", MODULE)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
LOCK = {"identity": {"bundle_id": "com.bearberni.rustdesk.v2", "display_name": "RustDesk V2", "version": "1.5.1"}}


def binary(platform=2, marker=True, cpu=0x0100000C):
    header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, 2, 1, 24, 0, 0)
    command = struct.pack("<6I", 0x32, 24, platform, 0x000F0000, 0x00120500, 0)
    return header + command + (b"Trusted-device credential unavailable" if marker else b"no marker")


def ipa(path, bundle_id=LOCK["identity"]["bundle_id"], platform=2, marker=True, extra=None):
    info = {"CFBundleIdentifier": bundle_id, "CFBundleDisplayName": "RustDesk V2", "CFBundleExecutable": "Runner"}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Payload/Runner.app/Info.plist", plistlib.dumps(info))
        z.writestr("Payload/Runner.app/Runner", binary(platform, marker))
        z.writestr("Payload/Runner.app/Frameworks/Flutter.framework/Info.plist", plistlib.dumps({"CFBundleExecutable": "Flutter"}))
        z.writestr("Payload/Runner.app/Frameworks/Flutter.framework/Flutter", binary())
        if extra:
            z.writestr(*extra)


class ArtifactTests(unittest.TestCase):
    def test_accepts_only_expected_static_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.ipa"
            ipa(p)
            result = VERIFY.verify(p, LOCK)
            self.assertTrue(result["checks"]["linked_v2_marker"])

    def test_rejects_simulator(self):
        with self.assertRaisesRegex(ValueError, "simulator"):
            VERIFY.macho_device_arm64(binary(platform=7))

    def test_rejects_non_arm64_and_truncation(self):
        for data in (binary(cpu=0x01000007), binary()[:45]):
            with self.subTest(data=data[:16]), self.assertRaises(ValueError):
                VERIFY.macho_device_arm64(data)

    def test_rejects_wrong_bundle_and_missing_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.ipa"
            for kwargs in ({"bundle_id": "com.carriez.flutterHbb"}, {"marker": False}):
                with self.subTest(kwargs=kwargs):
                    ipa(p, **kwargs)
                    with self.assertRaises(ValueError):
                        VERIFY.verify(p, LOCK)

    def test_rejects_profile_signature_and_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.ipa"
            for entry in ("Payload/Runner.app/embedded.mobileprovision", "Payload/Runner.app/_CodeSignature/CodeResources", "Payload/../escape"):
                with self.subTest(entry=entry):
                    ipa(p, extra=(entry, b"fixture"))
                    with self.assertRaises(ValueError):
                        VERIFY.verify(p, LOCK)


if __name__ == "__main__":
    unittest.main()
