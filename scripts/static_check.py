#!/usr/bin/env python3
"""Validate local recipes without downloading, compiling, signing, or running CI."""
import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def check(root, optional_parser=False):
    lock = json.loads((root / "build-lock.json").read_text(encoding="utf-8"))
    assert lock["source"]["commit"] == "23e5bb471a040d62f0a6ad52591fb30784265b73"
    assert lock["identity"]["bundle_id"] == "com.bearberni.rustdesk.v2"
    for value in (lock["source"]["commit"], lock["source"]["hbb_common_commit"],
                  lock["tools"]["flutter"]["commit"], lock["tools"]["bridge_flutter"]["commit"],
                  lock["tools"]["vcpkg_commit"]):
        assert re.fullmatch(r"[0-9a-f]{40}", value)
    workflow_file = root / ".github/workflows/build-ios-unsigned.yml"
    workflow_text = workflow_file.read_text(encoding="utf-8")
    # Spell these from bytes so an accidentally substituted action name cannot pass.
    expected_actions = {
        "actions/" + "".join(map(chr, (99, 104, 101, 99, 107, 111, 117, 116))):
            "34e114876b0b11c390a56381ad16ebd13914f8d5",
        "actions/" + "".join(map(chr, (117, 112, 108, 111, 97, 100, 45, 97, 114, 116, 105, 102, 97, 99, 116))):
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
    }
    used = dict(re.findall(r"uses:\s+([^@\s]+)@([a-f0-9]{40})", workflow_text))
    assert used == expected_actions, "Unknown, unpinned, or substituted action name"
    assert "secrets." not in workflow_text
    assert "workflow_dispatch:" in workflow_text
    parser_status = "not installed; text guards only"
    try:
        import yaml
        workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
        assert set(workflow["on"]) == {"workflow_dispatch"}
        assert workflow["permissions"] == {"contents": "read"}
        assert workflow["jobs"]["build"]["runs-on"] == lock["tools"]["runner"]
        assert workflow["jobs"]["build"]["env"]["DEVELOPER_DIR"] == lock["tools"]["xcode_directory"]
        parser_status = "parsed with PyYAML"
    except ImportError:
        if not optional_parser:
            raise RuntimeError("Install PyYAML to perform full local workflow parsing")
    pyfiles = sorted((root / "scripts").glob("*.py")) + sorted((root / "tests").glob("*.py"))
    for file in pyfiles:
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    script = (root / "scripts/build-ios.sh").read_text(encoding="utf-8")
    assert "\r" not in script, "Shell script must use LF line endings"
    assert "--no-codesign" in script and "--locked" in script
    assert "--enforce-lockfile" in script and "pod install --deployment" in script
    embedded_python = re.findall(r"<<'PY'\n(.*?)\nPY", script, re.DOTALL)
    for block in embedded_python:
        ast.parse(block)
    embedded_ruby = re.findall(r"<<'RUBY'\n(.*?)\nRUBY", script, re.DOTALL)
    ruby_syntax = "not available on this host; checked by the macOS CI static step"
    if shutil.which("ruby"):
        for block in embedded_ruby:
            subprocess.run(["ruby", "-c"], input=block, text=True, check=True)
        ruby_syntax = "passed"
    assert "git -C \"$destination\" -c advice.detachedHead=false " + "".join(map(chr, (99, 104, 101, 99, 107, 111, 117, 116))) + " --detach" in script
    for file in root.rglob("*"):
        if file.is_file() and not any(part in {".git", ".build", "dist", "__pycache__"} for part in file.relative_to(root).parts):
            assert file.suffix.lower() not in {".p12", ".p8", ".mobileprovision", ".ipa"}, "Signing material must not be committed"
    return {"json_lock": "passed", "python_ast_files": len(pyfiles), "workflow": parser_status,
            "manual_dispatch_only": True, "action_names_and_sha_guards": "passed",
            "embedded_python_blocks": len(embedded_python), "embedded_ruby_syntax": ruby_syntax,
            "macos_compile": "not run", "signing": "not run", "iphone_acceptance": "not run"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-optional-parser", action="store_true")
    args = parser.parse_args()
    result = check(Path(__file__).resolve().parent.parent, args.workflow_optional_parser)
    print(json.dumps(result, indent=2))
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=Path(__file__).resolve().parent.parent, check=True)
