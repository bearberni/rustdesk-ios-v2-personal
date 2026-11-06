#!/usr/bin/env python3
"""Verify an unsigned device IPA structurally; this is not a runtime trust test."""
import argparse
import hashlib
import json
import plistlib
import stat
import struct
import zipfile
from pathlib import Path, PurePosixPath


def macho_device_arm64(data):
    if len(data) < 32:
        raise ValueError("Executable is too short")
    magic, cpu, _, filetype, count, size, _, _ = struct.unpack_from("<8I", data)
    if magic != 0xFEEDFACF or cpu != 0x0100000C or filetype not in (2, 6):
        raise ValueError("Expected a thin arm64 Mach-O executable or framework")
    offset, platforms = 32, []
    if 32 + size > len(data) or count > 10000:
        raise ValueError("Invalid Mach-O load-command range")
    for _ in range(count):
        if offset + 8 > 32 + size:
            raise ValueError("Truncated Mach-O load command")
        command, length = struct.unpack_from("<II", data, offset)
        if length < 8 or offset + length > 32 + size:
            raise ValueError("Invalid Mach-O load-command length")
        if command == 0x32:
            if length < 24:
                raise ValueError("Invalid LC_BUILD_VERSION")
            platforms.append(struct.unpack_from("<I", data, offset + 8)[0])
        elif command == 0x25:
            platforms.append(2)  # LC_VERSION_MIN_IPHONEOS, older engine frameworks
        offset += length
    if not platforms or any(p != 2 for p in platforms):
        raise ValueError("Not an iPhone device binary (simulator/macOS binaries are rejected)")
    return {"architecture": "arm64", "platform": "iOS device"}


def verify(ipa, lock):
    with zipfile.ZipFile(ipa) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
                raise ValueError("Unsafe ZIP path")
            if not path.parts or path.parts[0] != "Payload":
                raise ValueError("IPA must contain only Payload at ZIP root")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Unexpected symlink in iOS app bundle; review packaging")
        infos = [n for n in names if n.startswith("Payload/") and
                 len(PurePosixPath(n).parts) == 3 and n.endswith(".app/Info.plist")]
        if len(infos) != 1:
            raise ValueError("Expected exactly one application bundle")
        app = infos[0].rsplit("/", 1)[0]
        info = plistlib.loads(archive.read(infos[0]))
        identity = lock["identity"]
        if info.get("CFBundleIdentifier") != identity["bundle_id"]:
            raise ValueError("IPA has an unexpected bundle ID")
        if info.get("CFBundleDisplayName") != identity["display_name"]:
            raise ValueError("IPA has an unexpected display name")
        if "CFBundleURLTypes" in info:
            raise ValueError("Personal app must not register the App Store URL scheme")
        if any(n.startswith(app + "/_CodeSignature/") or n == app + "/embedded.mobileprovision" for n in names):
            raise ValueError("Expected an unsigned, unprovisioned main application")
        executable = info.get("CFBundleExecutable", "")
        if not executable or "/" in executable or "\\" in executable:
            raise ValueError("Invalid CFBundleExecutable")
        data = archive.read(app + "/" + executable)
        platform = macho_device_arm64(data)
        if b"Trusted-device credential unavailable" not in data:
            raise ValueError("Linked executable lacks the expected V2 implementation marker")
        frameworks = []
        for name in names:
            if name.startswith(app + "/Frameworks/") and name.endswith(".framework/Info.plist"):
                frame_info = plistlib.loads(archive.read(name))
                frame_exe = frame_info.get("CFBundleExecutable")
                if not frame_exe or "/" in frame_exe or "\\" in frame_exe:
                    raise ValueError("Invalid framework executable")
                frame_binary = name.rsplit("/", 1)[0] + "/" + frame_exe
                macho_device_arm64(archive.read(frame_binary))
                frameworks.append(frame_binary)
        if not any(n.endswith("/Flutter.framework/Flutter") for n in frameworks):
            raise ValueError("Flutter framework is missing")
    return {
        "schema_version": 1,
        "checks": {"ipa_layout": True, "separate_identity": True, "no_url_scheme": True,
                   "main_app_unsigned": True, "linked_v2_marker": True,
                   "device_binaries": True},
        "identity": identity,
        "main_executable": executable,
        "main_executable_sha256": hashlib.sha256(data).hexdigest(),
        "binary": platform,
        "framework_binaries": frameworks,
        "limitations": ["No macOS/iOS runtime test is implied", "IPA still requires normal signing",
                        "V2 enrollment and reconnect must be accepted on a real iPhone"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ipa", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.ipa, json.loads(args.lock.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("IPA static verification passed; real-device acceptance is still required.")
