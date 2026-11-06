#!/usr/bin/env python3
"""Apply only the declared personal identity/signing changes to pinned public source."""
import argparse
import hashlib
import json
import plistlib
import re
import subprocess
from pathlib import Path


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, lock, output):
    source = source.resolve()
    if git(source, "rev-parse", "HEAD") != lock["source"]["commit"]:
        raise ValueError("Source commit differs from build-lock.json")
    if git(source / "libs/hbb_common", "rev-parse", "HEAD") != lock["source"]["hbb_common_commit"]:
        raise ValueError("hbb_common submodule commit differs from the pinned source")
    client = (source / "src/trusted_devices/client.rs").read_text(encoding="utf-8")
    for marker in ("request.trusted_device_v2_supported = true", "response.trusted_device_v2_supported"):
        if marker not in client:
            raise ValueError("Pinned source is missing required trusted-device V2 implementation")
    files = [source / "flutter/ios/Runner.xcodeproj/project.pbxproj",
             source / "flutter/ios/Runner/Info.plist",
             source / "flutter/ios/Runner/Runner.entitlements"]
    before = {str(p.relative_to(source)): sha(p) for p in files}
    project = files[0].read_text(encoding="utf-8")
    project, identities = re.subn(r"PRODUCT_BUNDLE_IDENTIFIER = com\.carriez\.flutterHbb;",
                                 f'PRODUCT_BUNDLE_IDENTIFIER = {lock["identity"]["bundle_id"]};', project)
    project, teams = re.subn(r"DEVELOPMENT_TEAM = HZF9JMC8YN;", 'DEVELOPMENT_TEAM = "";', project)
    if (identities, teams) != (3, 3):
        raise ValueError(f"Unexpected Xcode identity layout: bundle={identities}, team={teams}")
    info = plistlib.loads(files[1].read_bytes())
    if info.get("CFBundleIdentifier") != "$(PRODUCT_BUNDLE_IDENTIFIER)":
        raise ValueError("Unexpected Info.plist bundle identifier")
    if "CFBundleURLTypes" not in info:
        raise ValueError("Expected upstream URL scheme declaration is absent")
    info["CFBundleDisplayName"] = lock["identity"]["display_name"]
    info["CFBundleName"] = lock["identity"]["display_name"]
    del info["CFBundleURLTypes"]
    entitlements = plistlib.loads(files[2].read_bytes())
    if set(entitlements) != {"aps-environment", "com.apple.developer.networking.wifi-info"}:
        raise ValueError("Unexpected upstream entitlements; manual review required")
    # This personal controller does not register APNs or read Wi-Fi SSID information.
    # No server, password, token, certificate, provisioning profile, or Apple account is embedded.
    files[0].write_text(project, encoding="utf-8", newline="\n")
    files[1].write_bytes(plistlib.dumps(info, sort_keys=False))
    files[2].write_bytes(plistlib.dumps({}, sort_keys=False))
    report = {
        "source_commit": lock["source"]["commit"],
        "identity": lock["identity"],
        "changes": ["Three Xcode bundle IDs changed", "Upstream development team removed",
                    "Separate display name", "URL scheme registration removed",
                    "Unused APNs and Wi-Fi information entitlements removed"],
        "before_sha256": before,
        "after_sha256": {str(p.relative_to(source)): sha(p) for p in files},
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.source, json.loads(args.lock.read_text(encoding="utf-8")), args.output)
