# Validation status — 2026-11-06

Completed locally on Windows; these results do not establish a working iOS application.

- `build-lock.json` parsed and fixed SHA/identity guards passed.
- Workflow parsed with PyYAML 6.0.2; only `workflow_dispatch`, read-only contents permission,
  pinned official action names/commits, and the fixed Intel runner/Xcode selection passed.
- Both pinned action commits were resolved read-only against their official GitHub repositories.
- Five Python files parsed successfully with Python 3.12.
- Git for Windows Bash `-n scripts/build-ios.sh` passed.
- Five artifact-verifier fixture tests passed. They check the expected identity, device
  architecture/platform, linked marker, unsigned main app, and rejection of wrong identity,
  simulator/non-arm64/truncated binaries, signature/profile payloads, and ZIP path escape.
- The preparation script was exercised against the actual four relevant public files from
  the fixed RustDesk commit, verifying all three bundle IDs/teams, both display names,
  removed URL registration, and empty entitlements. Git/SHA lookup was mocked for that
  isolated preparation test; the real build performs actual Git/submodule checks.
- Separately, the public source's V2 commit ancestry and the pinned `hbb_common` SHA were
  verified against the existing upstream object database.

Still not run: FFI generation, Rust iOS compilation, Flutter archive, real IPA validation,
signing, installation, or real-iPhone V2 acceptance.
The first CI run must establish those build results. Its success must not be inferred
from local static/fixture checks. Signing and iPhone acceptance remain later steps.

## First CI run and CocoaPods selection fix

Run `42170454959`, commit `86eb87c2636867027a2980ded75bc8089388df8e`, passed checkout and
recipe checks, prepared the pinned source/identity, fetched both Flutter SDKs and Rust,
installed assembler/CMake dependencies, and installed CocoaPods 1.15.2.
It stopped at the CocoaPods version guard before the Rust/iOS application build.
The old guard did not print the selected value; RubyGems' unversioned launcher can select
the runner's newer installed gem through GEM_PATH despite the new bin directory's PATH priority.

The recipe now puts a local `pod` shim first in PATH and uses RubyGems' explicit
`_1.15.2_` version selector for direct commands and Flutter subprocesses. It also prints
the selected version before checking it. Shell syntax and forwarding behavior were
checked locally; a second CI run is needed to validate the actual RubyGems execution.
