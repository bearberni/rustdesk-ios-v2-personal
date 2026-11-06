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


def _thin_device_arm64(data):
    if len(data) < 32:
        raise ValueError("Executable is too short")
    magic, cpu, _, filetype, count, size, _, _ = struct.unpack_from("<8I", data)
    if magic != 0xFEEDFACF or cpu != 0x0100000C or filetype not in (2, 6):
        raise ValueError("Expected a thin arm64 Mach-O executable or framework")
    offset, platforms, signature = 32, [], False
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
        elif command == 0x1D:
            signature = True  # LC_CODE_SIGNATURE; framework ad-hoc signatures can exist
        offset += length
    if not platforms or any(p != 2 for p in platforms):
        raise ValueError("Not an iPhone device binary (simulator/macOS binaries are rejected)")
    return {"architecture": "arm64", "platform": "iOS device",
            "cpu_subtype": struct.unpack_from("<I", data, 8)[0],
            "embedded_code_signature": signature}


def macho_device_arm64(data):
    """Accept thin or FAT arm64 iOS device binaries; never ignore other slices."""
    formats = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
               b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
    magic = bytes(data[:4])
    if magic not in formats:
        result = _thin_device_arm64(data)
        return {**result, "format": "thin", "slices": [{**result, "offset": 0, "bytes": len(data)}]}
    endian, fat64 = formats[magic]
    if len(data) < 8:
        raise ValueError("Truncated FAT header")
    count = struct.unpack_from(endian + "I", data, 4)[0]
    entry_size = 32 if fat64 else 20
    table_end = 8 + count * entry_size
    if not 1 <= count <= 64 or table_end > len(data):
        raise ValueError("Invalid or truncated FAT architecture table")
    records, identities = [], set()
    for index in range(count):
        values = struct.unpack_from(endian + ("IIQQII" if fat64 else "IIIII"), data, 8 + index * entry_size)
        cpu, subtype, start, size, alignment = values[:5]
        if cpu != 0x0100000C:
            raise ValueError("FAT contains a non-arm64 architecture (x86/simulator slices are rejected)")
        if fat64 and values[5] != 0:
            raise ValueError("Invalid FAT64 reserved field")
        if (cpu, subtype) in identities:
            raise ValueError("Duplicate FAT architecture")
        identities.add((cpu, subtype))
        if alignment > (63 if fat64 else 31) or start % (1 << alignment):
            raise ValueError("Invalid FAT slice alignment")
        if start < table_end or size < 32 or start > len(data) or size > len(data) - start:
            raise ValueError("FAT slice is out of bounds or overlaps its header")
        records.append((start, size, cpu, subtype))
    previous_end = table_end
    for start, size, _, _ in sorted(records):
        if start < previous_end:
            raise ValueError("Overlapping FAT slices")
        previous_end = start + size
    slices = []
    for start, size, cpu, subtype in records:
        part = data[start:start + size]
        if struct.unpack_from("<II", part, 4) != (cpu, subtype):
            raise ValueError("FAT architecture metadata differs from the slice header")
        detail = _thin_device_arm64(part)
        slices.append({**detail, "offset": start, "bytes": size})
    return {"architecture": "arm64", "platform": "iOS device", "format": "fat64" if fat64 else "fat32",
            "embedded_code_signature": any(p["embedded_code_signature"] for p in slices), "slices": slices}


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
        if platform["embedded_code_signature"]:
            raise ValueError("Expected an unsigned main executable without LC_CODE_SIGNATURE")
        if b"Trusted-device credential unavailable" not in data:
            raise ValueError("Linked executable lacks the expected V2 implementation marker")
        frameworks, framework_details = [], []
        for name in names:
            if name.startswith(app + "/Frameworks/") and name.endswith(".framework/Info.plist"):
                frame_info = plistlib.loads(archive.read(name))
                frame_exe = frame_info.get("CFBundleExecutable")
                if not frame_exe or "/" in frame_exe or "\\" in frame_exe:
                    raise ValueError("Invalid framework executable")
                frame_binary = name.rsplit("/", 1)[0] + "/" + frame_exe
                detail = macho_device_arm64(archive.read(frame_binary))
                frameworks.append(frame_binary)
                framework_details.append({"binary": frame_binary, **detail})
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
        "ipa_sha256": hashlib.sha256(Path(ipa).read_bytes()).hexdigest(),
        "ipa_bytes": Path(ipa).stat().st_size,
        "binary": platform,
        "framework_binaries": frameworks,
        "framework_details": framework_details,
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
