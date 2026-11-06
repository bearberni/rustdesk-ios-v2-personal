#!/usr/bin/env python3
"""Apply only the declared personal identity/signing changes to pinned public source."""
import argparse
import hashlib
import json
import plistlib
import re
import subprocess
from pathlib import Path

# Only local podspec metadata reported by run 42179000648 is calibrated.
# Native pod versions/dependencies stay fixed and --deployment remains mandatory.
PODFILE_LOCK_SHA256 = "76c1b67882800547658040acf1a051cd748188f13e2f93e8e6962a964e235966"
PUBSPEC_LOCK_SHA256 = "e4f87b5c7a0d9217ad0589dc9e60fb39b277f8bd1744ab663f06902e852c1008"
PODSPEC_CHECKSUM_UPDATES = {
    "device_info_plus": {"old": "c6fb39579d0f423935b0c9ce7ee2f44b71b9fce6", "new": "335f3ce08d2e174b9fdc3db3db0f4e3b1f66bd89"},
    "file_picker": {"old": "ce3938a0df3cc1ef404671531facef740d03f920", "new": "5f42b9d5580e30b57b4863f9d94b448016b702e5"},
    "flutter_keyboard_visibility": {"old": "0339d06371254c3eb25eeb90ba8d17dca8f9c069", "new": "4625131e43015dbbe759d9b20daaf77e0e3f6619"},
    "image_picker_ios": {"old": "c560581cceedb403a6ff17f2f816d7fea1421fc1", "new": "7fe1ff8e34c1790d6fff70a32484959f563a928a"},
    "package_info_plus": {"old": "115f4ad11e0698c8c1c5d8a689390df880f47e85", "new": "566e1b7a2f3900e4b0020914ad3fc051dcc95596"},
    "path_provider_foundation": {"old": "2b6b4c569c0fb62ec74538f866245ac84301af46", "new": "080d55be775b7414fd5a5ef3ac137b97b097e564"},
    "qr_code_scanner": {"old": "bb67d64904c3b9658ada8c402e8b4d406d5d796e", "new": "d77f94ecc9abf96d9b9b8fc04ef13f611e5a147a"},
    "sqflite": {"old": "6d358c025f5b867b29ed92fc697fd34924e11904", "new": "954affaf2567c73cda074440299a625e3b2cbf8a"},
    "uni_links": {"old": "d97da20c7701486ba192624d99bffaaffcfc298a", "new": "ed8c961e47ed9ce42b6d91e1de8049e38a4b3152"},
    "url_launcher_ios": {"old": "5334b05cef931de560670eeae103fd3e431ac3fe", "new": "694010445543906933d732453a59da0a173ae33d"},
    "video_player_avfoundation": {"old": "7c6c11d8470e1675df7397027218274b6d2360b3", "new": "2cef49524dd1f16c5300b9cd6efd9611ce03639b"},
    "wakelock_plus": {"old": "78ec7c5b202cab7761af8e2b2b3d0671be6c4ae1", "new": "fd58c82b1388f4afe3fe8aa2c856503a262a5b03"},
}


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
             source / "flutter/ios/Runner/Runner.entitlements",
             source / "flutter/ios/Podfile.lock"]
    before = {str(p.relative_to(source)): sha(p) for p in files}
    if sha(files[3]) != PODFILE_LOCK_SHA256 or sha(source / "flutter/pubspec.lock") != PUBSPEC_LOCK_SHA256:
        raise ValueError("Upstream Podfile/pubspec lock bytes differ from the reviewed commit")
    pod_lock = files[3].read_text(encoding="utf-8")
    for name, values in PODSPEC_CHECKSUM_UPDATES.items():
        pattern = rf"^  {re.escape(name)}: {values['old']}$"
        pod_lock, count = re.subn(pattern, f"  {name}: {values['new']}", pod_lock, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f"Unexpected local podspec checksum for {name}")
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
    files[3].write_text(pod_lock, encoding="utf-8", newline="\n")
    report = {
        "source_commit": lock["source"]["commit"],
        "identity": lock["identity"],
        "changes": ["Three Xcode bundle IDs changed", "Upstream development team removed",
                    "Separate display name", "URL scheme registration removed",
                    "Unused APNs and Wi-Fi information entitlements removed",
                    "Twelve local podspec checksums calibrated; all pod versions/dependencies unchanged"],
        "runtime_pubspec_lock_sha256": PUBSPEC_LOCK_SHA256,
        "podspec_checksum_updates": PODSPEC_CHECKSUM_UPDATES,
        "podspec_checksum_reference_run": 42179000648,
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
