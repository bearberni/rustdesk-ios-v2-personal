# Personal SideStore repair build recipe

This candidate updates the existing personal build branch only. Root owns the
reviewed source patch, remote upload and build trigger. This directory does not
publish a store app, request Apple credentials, modify main, or claim phone success.

## Exact selected upstream and dependency identity

- SideStore: `151d3378acadcd3b560bb69b1a8da249bf33ce8a`
- Minimuxer: `decbfe190fdb94a380509fe93be7dc950e60f36b`
- SideSign: `7331ad630a600e0e31e4b434b7d8774ca86db39b`
- Personal version: `0.7.0-personalautomation.<run>+151d3378`

The source patch is reviewed against this base. It includes the separately
reviewed official local-service filtering and the task-specific automation,
port recovery, diagnostics and data-preservation integration. It must not be
applied to another ref. CI validates all three checked-out commits and the
new baseline's Swift package pins; it never silently upgrades a dependency.

## Required files and trigger

Keep the existing `.github/workflows/build-sidestore-automation.yml` unchanged.
On `sidestore-automation-no-menus`, upload these files under `sidestore-automation/`:

- `build_sidestore_automation.sh`
- `validate_sidestore_automation.py`
- `test_validate_sidestore_automation.py`
- `run_coredata_migration.sh`
- `verify_coredata_migration.swift`
- this `README.md`

Root supplies `personal-automation.patch` last, or includes all files in one
reviewed atomic commit. Only the patch path triggers the current push workflow.
Use the current branch head as a lease; do not overwrite unrelated remote work.
The patch allowlist is an exact named-file set in the build script, not an
arbitrary environment-supplied path allowance. Root must compare it with the
final staged plus working/untracked source patch before upload.

## Ordered gates on the macOS runner

1. Select `/Applications/Xcode_27.2.app` and confirm the actual device SDK.
2. Check source/submodule pins and apply only the reviewed allowlisted patch.
3. Run the complete dependency-free Swift package test suite; preserve its log.
4. Run the real synthetic CoreData17_6-to17_7 migration gate using the two flat
   recipe files. Compile official models, preserve generated synthetic SQLite
   fixtures and JSON evidence. These tests never open actual phone data.
5. Run the artifact-identity validator's synthetic positive/rejection tests.
6. Resolve only the pinned Swift packages, then use the official Makefile's
   build/fakesign/ipa path with unchanged base bundle identity.
7. Validate actual arm64 main-app Mach-O entitlements, bundle/group/URL identity,
   device platform, personal source suffix, no embedded provisioning profile,
   and real compiled String-based V2 action/parameter/protocol metadata.

No gate hard-codes a test count. CI success requires all gates plus archive and
package validation, not an expected number printed in a log.

## Preservation and acceptance boundary

The unsigned base identity remains `com.SideStore.SideStore`; main executable
fakesign identity must be `XYZ0123456.com.SideStore.SideStore`, team placeholder
`XYZ0123456`, and App Group `group.com.SideStore.SideStore`. There must be no
personal team/profile in the public artifact. `ALTAppGroups` was removed from
151's Info.plist; if present it must match, while the actual signed group is
always checked. URL schemes and document/log access remain compatible.

The three compiled V2 actions must return String, runID parameters must remain
required String, and the execute action must retain long-running, progress and
cancellation protocols. Metadata registration is not proof of phone discovery.

These checks allow an in-place personal signing attempt; they do not prove that
the signer retained the same team, account, pairing, Keychain, filesystem or
actual device database. Install with the same existing Apple account over the
existing app, never delete it first. Root must retain phone acceptance as pending
until configuration/data preservation and the full dual-app renewal plus QuanX
restoration are actually verified on that iPhone.
