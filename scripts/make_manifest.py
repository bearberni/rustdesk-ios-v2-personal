#!/usr/bin/env python3
"""Write public build provenance and artifact hashes, never arbitrary environment values."""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def main():
    parser = argparse.ArgumentParser()
    for name in ("recipe", "source", "dist", "tools"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads((args.recipe / "build-lock.json").read_text(encoding="utf-8"))
    source = args.source
    files = {p.relative_to(args.dist).as_posix(): {"sha256": digest(p), "bytes": p.stat().st_size}
             for p in sorted(args.dist.rglob("*"))
             if p.is_file() and p.name not in {"build.log", "manifest.json", "SHA256SUMS"}}
    # build.log is actively written by tee; do not record a hash before it is closed.
    core = source / "target/aarch64-apple-ios/release/liblibrustdesk.a"
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "build_lock": lock,
        "source_commit": command("git", "-C", str(source), "rev-parse", "HEAD"),
        "submodules": command("git", "-C", str(source), "submodule", "status", "--recursive").splitlines(),
        "source_diff_stat": command("git", "-C", str(source), "diff", "--stat"),
        "lockfile_sha256": {p: digest(source / p) for p in ("Cargo.lock", "flutter/pubspec.lock", "flutter/ios/Podfile.lock")},
        "native_core_sha256": digest(core),
        "tools": {
            "xcode": command("xcodebuild", "-version"),
            "iphoneos_sdk": command("xcrun", "--sdk", "iphoneos", "--show-sdk-version"),
            "rustc": command("rustc", "--version", "--verbose"),
            "cargo": command("cargo", "--version"),
            "flutter": command(str(args.tools / "flutter/bin/flutter"), "--version", "--machine"),
            "bridge_flutter": command(str(args.tools / "flutter-bridge/bin/flutter"), "--version", "--machine"),
            "bridge_codegen": command("flutter_rust_bridge_codegen", "--version"),
            "cargo_expand": command("cargo", "expand", "--version"),
            "cocoapods": command("pod", "--version"),
            "cmake": command("cmake", "--version"),
            "ruby": command("ruby", "--version"),
            "python": sys.version,
        },
        "runner": {key: os.environ.get(key) for key in ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH")},
        "github": {key: os.environ.get(key) for key in ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
        "artifacts": files,
        "status": {"signed": False, "static_artifact_checks": True, "real_device_acceptance": "pending"},
        "reproducibility_limits": ["Hosted runner image and Homebrew/Ruby transitive dependencies can change",
                                   "Temporary Flutter 3.22.3 bridge resolution is recorded as bridge-pubspec.lock",
                                   "No claim of byte-for-byte reproducibility or arbitrary-Xcode compatibility"],
    }
    manifest_path = args.dist / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lines = [f'{entry["sha256"]}  {name}' for name, entry in files.items()]
    lines.append(f"{digest(manifest_path)}  manifest.json")
    (args.dist / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
