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
That RubyGems execution was subsequently confirmed in the second run below.

## Second CI run and Flutter release metadata fix

Run `42171938809`, commit `b7d38b83b8418c3d1dedd0f3bbf3e9c649564e29`, verified
`Selected CocoaPods: 1.15.2`, completed all 17 vcpkg installations, and compiled/installed
both bridge-generation tools with the pinned Rust toolchain. It reached the bridge
Flutter dependency resolver and stopped because that SDK reported `0.0.0-unknown`.
The SHA-only shallow fetch had omitted Flutter's release tag; Flutter uses local tags
to determine its version, so sqflite's Flutter minimum was rejected before FFI generation.

The recipe now fetches each exact Flutter release tag, verifies its target equals the
already pinned commit, and verifies `flutter --version --machine` for both version and
revision before the expensive vcpkg build. Both SDKs are fixed; this does not upgrade
Flutter or fabricate a version file. Local syntax/fixture checks pass; a subsequent
macOS run must confirm the SDK metadata and continue the actual application build.

## Third CI run and locked local-podspec calibration

Run `42179000648`, commit `506c3141eec0d8feee44adaf13b14c4e0fd4b6c8`, passed both
Flutter SDK identity guards, vcpkg, FFI generation/header copy, and runtime
`flutter pub get --enforce-lockfile`. It stopped at `pod install --deployment` because
12 local Flutter plugin SPEC CHECKSUMS differed. The reported diff contained no pod
version or dependency changes. No Rust iOS application compilation or IPA occurred.

The original Podfile.lock and runtime pubspec.lock were both last changed upstream in
`ef827fdb34aef13cb37826b9efc62e8b9a28f1b0` on October 30. The pipeline did not update
the runtime Dart lock. The upstream machine's actual podspec files and gem environment
are not recorded, so neither changed sources nor JSON serialization differences are
claimed as the proven historical cause.

The preparation now requires exact original lockfile hashes and applies only the 12
observed SPEC CHECKSUMS substitutions. A preflight independently reads the pinned plugin
sources through Flutter's dependency metadata, checks package versions and the enforced
Dart lock hash, generates podspec JSON with CocoaPods 1.15.2, and verifies every new
checksum. It archives those JSON files and environment/source metadata. Deployment mode
still checks the whole native lock, first before vcpkg and again after bridge restoration.
Failed builds retain diagnostics so any mismatch is inspectable without losing the audit.
Independent review caught that `uni_links` is a Git dependency rather than a hosted package.
The audit now separately allows only its exact upstream URL/subdirectory and locked
`f416118d843a7e9ed117c7bb7bdc2deda5a9e86f` ref, verifies the real local Git HEAD, and
records Git provenance instead of requiring a nonexistent archive hash.

Local syntax, fixtures, and actual-upstream preparation checks are rerun for this change.
Ruby is unavailable on the Windows preparation host; the workflow's initial static-check
step now runs `ruby -c` on the embedded audit before any dependency build. Actual audit
execution, native compilation, and device acceptance remain for the next run.
