# RustDesk V2 personal iOS build

Build recipes for an independent **RustDesk V2** iPhone app. The App Store RustDesk app
can remain installed. This is a personal build, not an upstream release.

**Current validation:** Python/YAML/shell static validation can run on Windows.
No macOS compile, signing, installation, or real-iPhone trust acceptance has been completed
as part of preparing these recipes. A passing fixture test is not an iOS build result.

## Fixed source and tools

`build-lock.json` is the source of truth. RustDesk is fixed to
`23e5bb471a040d62f0a6ad52591fb30784265b73` (stable `1.5.1`), including
trusted-device V2 commit `350966b331bb873650668549b3fa4a42e81e6a81`.
The pinned tree contains the actual V2 client implementation; its inclusion was checked
using both Git ancestry and source inspection. The `hbb_common` submodule is
`fae47e024dd83cef6aaecde0aa7d11731df11649`.

The recipe follows the upstream iOS/bridge tools: Flutter 3.24.5; iOS Rust 1.75.0;
Flutter 3.22.3 for bridge generation; cargo-expand 1.0.95; bridge codegen 1.80.1;
the pinned vcpkg commit and `arm64-ios` triplet; CMake 4.3.0; CocoaPods 1.15.2.
The target iOS deployment minimum is 15.0. The workflow selects **macos-15-intel** and
**Xcode 16.4, build 16F6**, confirmed present in the reviewed official runner inventory.
It fails if that exact Xcode is unavailable instead of silently using a newer one.
Upstream generates the bridge on Linux. This single-job recipe generates it on macOS
with the same pinned bridge tools. That host adaptation has not yet been compiled and
is one item for the first macOS run to validate. The separate upstream macOS-desktop
Rust 1.81 setting is not treated as an iOS or bridge minimum.

Hosted image updates, Homebrew packages, Ruby transitive gems, and temporary bridge
dependency resolution remain moving inputs. The latter is retained as `bridge-pubspec.lock`.
Runtime Cargo/Dart/Pod locks are retained and enforced. The manifest records actual
tool versions, image version, submodules, lockfile hashes, and artifact hashes.
This is a pinned starting point, not a promise of byte-identical output or compatibility
between old Flutter and every new Xcode. First compilation may expose upstream toolchain issues;
any necessary change should be reviewed and recorded rather than silently upgrading everything.

## Personal application changes

Only the prepared copy of upstream source is changed:

- Bundle ID: `com.bearberni.rustdesk.v2`, consistently in Debug, Release, and Profile.
- Display name: `RustDesk V2`; upstream development team is removed.
- URL scheme registration is removed, so this app does not compete with the App Store app
  for `rustdesk://` links. Connect using the normal numeric-ID field.
- APNs and Wi-Fi-info entitlements are removed. The inspected controller implementation
  does not register APNs or query Wi-Fi SSID information. No App Group or Keychain Access
  Group is introduced. Actual signing/device validation is still required.

Server settings, keys, passwords, and tokens are never embedded. The personal app has its
own configuration storage. Configure it manually and create a new V2 trust grant;
do not copy the App Store app's config/token directory. A changed device ID is not guaranteed.

## Run manually when authorized

1. Put these recipes in the intended GitHub repository's default branch.
2. In **Actions**, choose **Build RustDesk V2 unsigned iOS**, then **Run workflow**.
3. The workflow uses only manual dispatch, read-only repository permission, and pinned
   official actions. It has no push trigger, signing secrets, release publishing, or install step.
4. Review the run and download its artifact before the seven-day retention ends.

The build freshly fetches and verifies fixed commits; generates the FFI bridge; builds
the Rust static library; builds the Flutter device archive; then packages and verifies an IPA.
It does not reuse a prebuilt Rust core or a cached generated bridge.
Both Flutter release tags are fetched and checked against their fixed commits, and
the SDK's own reported version/revision is verified before native dependency builds.

Flutter 3.24.5's `flutter build ipa --no-codesign` skips IPA export. This recipe explicitly
packages the archived application as `Payload/<app>.app` inside `RustDesk-V2-unsigned.ipa`.
The ZIP packaging does **not** sign the app or make it installable by itself.

Output includes:

- `RustDesk-V2-unsigned.ipa`, requiring a separate normal signing/install process;
- `verification.json` with ZIP identity, iOS-device/arm64, unsigned-main-app, and linked-V2-marker checks;
- `manifest.json` and `SHA256SUMS` with source/tool/artifact provenance;
- `source-preparation.json`, bridge resolver lock, upstream license, and corresponding modified source;
- public build log. No signing credentials or personal server configuration are requested.

Signing needs an Apple account and provisioning compatible with the chosen installation
method. The workflow deliberately does not request these credentials. Free Personal Team
renewal limits and paid membership terms are separate from compiling an IPA.

## Real-device acceptance

After normal signing/installing the independent app:

1. Confirm both app icons exist and the App Store app still works.
2. In RustDesk V2, manually configure the intended ID/relay server and verified public key.
3. Connect by numeric ID using the permanent password. Confirm the connection information
   says encrypted connection, then check **Trust this device** in the TOTP prompt.
4. Confirm a new V2 grant is present on the controlled PC.
5. Disconnect, force quit, reopen, and reconnect: the trusted connection should omit TOTP.
6. Revoke only this new grant on the PC, then reconnect and confirm TOTP is required again.

These are acceptance criteria, not completed results. Keep the existing App Store installation
and host security settings during this validation. No server migration is required by this build.

## Local static checks

Requires Python 3 and PyYAML for full workflow parsing:

```text
python scripts/static_check.py
bash -n scripts/build-ios.sh
```

These checks do not download toolchains or compile iOS. A local macOS build can be started
explicitly with `bash scripts/build-ios.sh` in a fresh workspace that has the exact selected
Xcode, Intel architecture, Ruby 3.3, Homebrew, rustup, Git, Python, and zip available.
The script stops if `.build/` or `dist/` already exists; it does not delete previous results.

## Primary references

- [Pinned RustDesk iOS build job](https://github.com/rustdesk/rustdesk/blob/23e5bb471a040d62f0a6ad52591fb30784265b73/.github/workflows/flutter-build.yml#L789)
- [Pinned bridge job](https://github.com/rustdesk/rustdesk/blob/23e5bb471a040d62f0a6ad52591fb30784265b73/.github/workflows/bridge.yml)
- [V2 implementation and mixed-version behavior](https://github.com/rustdesk/rustdesk/pull/16548)
- [Runner inventory reviewed for Xcode availability](https://github.com/actions/runner-images/blob/42d27e4a2c1232e5640a88ed42a974c8918ecd28/images/macos/macos-15-Readme.md)
- [Flutter 3.24.5 skips IPA export without signing](https://github.com/flutter/flutter/blob/3.24.5/packages/flutter_tools/lib/src/commands/build_ios.dart#L420)
