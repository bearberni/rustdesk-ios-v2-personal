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


def binary(platform=2, marker=True, cpu=0x0100000C, subtype=0):
    header = struct.pack("<8I", 0xFEEDFACF, cpu, subtype, 2, 1, 24, 0, 0)
    command = struct.pack("<6I", 0x32, 24, platform, 0x000F0000, 0x00120500, 0)
    return header + command + (b"Trusted-device credential unavailable" if marker else b"no marker")


def fat(parts, endian=">", fat64=False):
    count = len(parts)
    entry_size = 32 if fat64 else 20
    cursor = (8 + entry_size * count + 63) // 64 * 64
    table, bodies = [], []
    for data in parts:
        cpu, subtype = struct.unpack_from("<II", data, 4)
        values = (cpu, subtype, cursor, len(data), 6) + ((0,) if fat64 else ())
        table.append(struct.pack(endian + ("IIQQII" if fat64 else "IIIII"), *values))
        bodies.append((cursor, data))
        cursor = (cursor + len(data) + 63) // 64 * 64
    result = bytearray(cursor)
    result[:8] = struct.pack(endian + "II", 0xCAFEBABF if fat64 else 0xCAFEBABE, count)
    result[8:8 + entry_size * count] = b"".join(table)
    for offset, data in bodies:
        result[offset:offset + len(data)] = data
    return result


def ipa(path, bundle_id=LOCK["identity"]["bundle_id"], platform=2, marker=True, extra=None, framework=None):
    info = {"CFBundleIdentifier": bundle_id, "CFBundleDisplayName": "RustDesk V2", "CFBundleExecutable": "Runner"}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Payload/Runner.app/Info.plist", plistlib.dumps(info))
        z.writestr("Payload/Runner.app/Runner", binary(platform, marker))
        z.writestr("Payload/Runner.app/Frameworks/Flutter.framework/Info.plist", plistlib.dumps({"CFBundleExecutable": "Flutter"}))
        z.writestr("Payload/Runner.app/Frameworks/Flutter.framework/Flutter", binary() if framework is None else framework)
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

    def test_accepts_all_supported_fat_headers(self):
        for endian in (">", "<"):
            for wide in (False, True):
                with self.subTest(endian=endian, fat64=wide):
                    result = VERIFY.macho_device_arm64(fat([binary()], endian=endian, fat64=wide))
                    self.assertEqual(result["platform"], "iOS device")
                    self.assertEqual(len(result["slices"]), 1)

    def test_rejects_fat_table_truncation_and_bounds(self):
        valid = fat([binary()])
        outside = bytearray(valid)
        struct.pack_into(">I", outside, 16, len(valid))
        in_header = bytearray(valid)
        struct.pack_into(">I", in_header, 16, 0)
        for data in (valid[:20], outside, in_header):
            with self.subTest(data=data[:24]), self.assertRaises(ValueError):
                VERIFY.macho_device_arm64(data)

    def test_rejects_overlapping_fat_slices(self):
        data = fat([binary(), binary(subtype=2)])
        first_offset = struct.unpack_from(">I", data, 16)[0]
        struct.pack_into(">I", data, 36, first_offset)
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            VERIFY.macho_device_arm64(data)

    def test_rejects_fat_duplicate_architecture(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            VERIFY.macho_device_arm64(fat([binary(), binary()]))

    def test_rejects_x86_or_simulator_even_with_valid_arm64(self):
        for part in (binary(cpu=0x01000007), binary(platform=7, subtype=2)):
            with self.subTest(part=part[:32]), self.assertRaises(ValueError):
                VERIFY.macho_device_arm64(fat([binary(), part]))

    def test_rejects_fat_metadata_mismatch(self):
        data = fat([binary()])
        struct.pack_into(">I", data, 12, 2)
        with self.assertRaisesRegex(ValueError, "metadata"):
            VERIFY.macho_device_arm64(data)

    def test_rejects_fat_alignment_and_reserved_fields(self):
        misaligned = fat([binary()])
        struct.pack_into(">I", misaligned, 24, 31)
        reserved = fat([binary()], fat64=True)
        struct.pack_into(">I", reserved, 36, 1)
        for data in (misaligned, reserved):
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                VERIFY.macho_device_arm64(data)

    def test_checks_fat_framework_inside_ipa(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.ipa"
            ipa(p, framework=fat([binary()]))
            result = VERIFY.verify(p, LOCK)
            self.assertEqual(result["framework_details"][0]["format"], "fat32")
            ipa(p, framework=fat([binary(), binary(platform=7, subtype=2)]))
            with self.assertRaises(ValueError):
                VERIFY.verify(p, LOCK)

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
