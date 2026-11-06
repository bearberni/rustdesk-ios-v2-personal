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

At the initial preparation stage, FFI generation, Rust iOS compilation, Flutter archive,
real IPA validation, signing, installation, and real-iPhone acceptance had not run.
Subsequent CI results below establish specific later progress; they must not be inferred
from the original fixture tests. Signing and iPhone acceptance remain later steps.

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

## Fourth CI run, recovered IPA, and FAT framework verification

Run `42188989343`, commit `ecb0b2f931c02e7b62a95a1c79788ee9ca9f2b90`, passed Ruby syntax,
the actual local-podspec audits (including Git uni_links provenance), both deployment checks,
FFI generation, and the real Rust iOS core build. `rustdesk` finished release compilation
in 11m17s. Xcode then successfully archived Runner.xcarchive with bundle ID
`com.bearberni.rustdesk.v2`, display name `RustDesk V2`, deployment minimum 15.0,
version 1.5.1, and build number 4.

The CI run failed in the old artifact verifier before corresponding-source packaging and
manifest production. Its thin-only requirement incorrectly rejected App.framework, a valid
FAT32 container holding one arm64 iOS-device slice. All other 19 frameworks and the main
executable are thin arm64 iOS-device binaries. The failure diagnostics artifact was recovered
with ZIP SHA256 `36b00a29ca6079fdcd114496408bb9f67df7b49d73bd15c2bf87a71c08f7b104`,
matching the GitHub artifact digest.

The IPA was extracted byte-for-byte, not repackaged, modified, or signed:

```text
bytes: 27105035
SHA256: 08d1b073f573221527bf6461b16340787243e6c6519b3194d8f48be55cb32d5c
```

The verifier now safely parses FAT32/FAT64 in both byte orders, validates every slice's
architecture and iOS-device load commands, and rejects bad tables, bounds, overlapping
slices/header, duplicate records, inconsistent headers, alignment errors, simulator/x86
slices, and invalid reserved fields. It does not ignore unwanted architectures merely
because an arm64 slice is present. The main executable must have no embedded signature;
framework ad-hoc signatures may already exist and are left unchanged for normal signing.

Thirteen fixture tests and local static checks passed. The corrected verifier then passed
on the actual original IPA: all 21 binaries, separate identity, absent URL registration,
unsigned main app, and linked V2 marker were checked. That is a local static artifact result,
not a successful original CI run or a real-device result.

The diagnostics do not contain the runner's native .a or generated FFI files. No native .a
hash or claim of retaining those generated files is made. Any separately prepared source
package must distinguish the fixed source/recipes/reconstruction inputs from files actually
retained by this run. At artifact recovery, normal signing, iOS launch, and V2
enrollment/reconnect acceptance had not run; subsequent acceptance is recorded separately.

## Fifth CI run: complete workflow and downloaded artifacts

[Run 42198548001](https://github.com/bearberni/rustdesk-ios-v2-personal/actions/runs/42198548001),
recipe commit `ea5253f99de5223bc24e726bc20d806d29a62bb1`, completed every build,
verification, corresponding-source, manifest, and upload step successfully. Artifact
`RustDesk-V2-unsigned-5` has 35,308,677 ZIP bytes and SHA256
`1df1362243820efbdc7e9ddd223b2c5e6f98499fa36e1c246a341d997d470a88`.

Independent checks of the downloaded bytes matched all 34 manifest file hashes/sizes and
all 35 SHA256SUMS entries. Local verification of the actual IPA exactly matched the CI
report for the main executable and all 20 frameworks. Build 5 has version 1.5.1, deployment
minimum 15.0, 27,105,033 IPA bytes, and SHA256
`39e82dec3d9d514c979a4d5bbd85ede6646562a1989f29610b4fa688c0260dcd`.

The corresponding-source tar contains 1,432 members, including the six actual generated
FFI files from this runner. Cargo/Dart locks match the pinned Git bytes. The prepared Pod
lock and modified source match the CI preparation/audit reports; both generated C headers
are identical. The producer records the native library hash, but its .a is not retained in
the artifact and was not independently rehashed after download.

Build 5 has not been signed, installed, or accepted on an iPhone. These are complete CI
and downloaded-artifact results. Device acceptance for a different binary does not transfer.
Later documentation-only commits describe this run; the validated producer remains the
recipe commit named above.
