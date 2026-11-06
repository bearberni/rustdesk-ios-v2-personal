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

Not run: macOS dependency installation, FFI generation, Rust iOS compilation, Flutter archive,
real IPA validation, signing, installation, or real-iPhone V2 acceptance.
The first CI run must establish those build results. Its success must not be inferred
from local static/fixture checks. Signing and iPhone acceptance remain later steps.
