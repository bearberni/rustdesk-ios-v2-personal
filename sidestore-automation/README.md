# Personal SideStore automation build recipe

This recipe is an isolated build on branch `sidestore-automation-no-menus` in the existing personal repository. It does not fork, open a PR, push to SideStore, publish a release, change the default branch, or request Apple credentials.

Before upload, root supplies the flat file `sidestore-automation/personal-automation.patch`, then confirms the main Swift type is `ExecuteRenewalV2Intent`. This wireV2 recipe requires three exact actual compiler-registered action IDs: `PrepareRenewalV2Intent`, `ExecuteRenewalV2Intent`, and `FinalizeRenewalV2Intent`. A legacy or mixed V1/V2 identifier list fails closed before building. The validator accepts repeated `--expected-intent` flags or comma-separated IDs, and CI always supplies all three V2 IDs.

The patch scope is an exact eleven-path allowlist: four `SideStore/Core/Automation/Automation{RefreshIntent,RefreshCoordinator,ProfileEvidence,RefreshPolicy}.swift` files; the reviewed `AltStore/Managing Apps/AppManager.swift`, `SideStore/Core/Operations/PipelineOperations/RefreshAppOperation.swift`, `SideStore/Core/Operations/PipelineRunner.swift`, `SideStore/Core/Operations/PipelineOperations/PreflightChecksOperation.swift`, and `SideStore/Core/Operations/PipelineOperations/UpdateAppCertificateOperation.swift`; root `Package.swift`; and `AutomationTests/AutomationRefreshPolicyTests.swift`. The preflight file's actual directory was checked in the pinned source tree and is `PipelineOperations`, not `StandaloneOperations`. The certificate operation change is restricted by the reviewed patch to the automation-only pre-captured serial path; certificate behavior and the manual branch remain outside this task's intended changes. The recipe does not permit arbitrary signing, pairing, dependency, project-setting or other pipeline edits. After applying the patch, CI first runs the dependency-free policy-state `swift test` package before the Xcode archive; the build log records the actual current test count. No source Swift is supplied by this recipe.

Upload `.github/workflows/build-sidestore-automation.yml` to that exact repository path on branch `sidestore-automation-no-menus`, then this directory's recipe files to `sidestore-automation/`. Upload `personal-automation.patch` last: only a push to that exact branch modifying `sidestore-automation/personal-automation.patch` starts the authorized build. Other file uploads do not trigger it. `workflow_dispatch` is also retained if GitHub exposes it for the branch; the push trigger avoids having to put a new dispatch workflow on the default branch. There is no schedule, and permission is only `contents: read`.

The recipe checks out SideStore commit `6032424a0e56c1c319762e786099bdd9186a238b` and its exact SideSign/minimuxer gitlinks, applies the patch, selects an observed iOS 27 SDK on the public `xcode-27` runner, and runs the official `make build fakesign ipa` packaging route. Default Xcode request is 27.2; a manual 27.1 input is supported if a runner rollout lacks 27.2. It never silently falls back to a 26 SDK. The first CI run remains the real SDK and compilation verification.

Release build keeps the original `com.SideStore.SideStore` bundle ID. `MARKETING_VERSION` becomes `0.7.0-personalautomation.<run>+6032424a`. No personal team suffix is pre-added: the installed SideStore should apply the same signing account's suffix when normally signing the IPA. A different bundle/app-group identity can create a separate installation or lose shared data. Do not delete the installed SideStore first. Official SideStore FAQ allows in-place nightly/test installs but does not guarantee data preservation in unofficial builds, so phone acceptance and fallback still matter.

Artifact contents:

- `SideStore-personalautomation-unsigned.ipa`, with only upstream fake signing for entitlement retention, requiring ordinary personal signing on the phone.
- Complete setup/build log, observed Xcode/SDK versions, exact source/submodule/patch provenance and package pins.
- Actual app `Info.plist` in raw and JSON form.
- Raw and decoded main-app `Metadata.appintents`, candidate identifier paths, and an IPA validation report. The exact real action identifier should be obtained from this metadata, not guessed from a source title.

Validation checks native arm64 thin/FAT Mach-O, one device app, unchanged base bundle ID, visible personal version, absence of personal provisioning profiles, and all three registered IDs in the main app's actual `extract.actionsdata` action map. It does not accept a mere type-name string in a description. The metadata schema was checked against the official 0.7.0-alpha IPA (official release digest `e334f86e6ceeab2e0d886c07611246533f474bb18838cf13ebc09ed1f0d622b5`). It does not claim Apple-valid device signing, iPhone installation, OS-policy acceptance, pairing health, or automatic runtime success. A missing/unrecognized action metadata format is a build diagnostic, not permission to claim action discovery.

Sources:

- [Pinned official Makefile](https://github.com/SideStore/SideStore/blob/6032424a0e56c1c319762e786099bdd9186a238b/Makefile)
- [Pinned official CI](https://github.com/SideStore/SideStore/blob/6032424a0e56c1c319762e786099bdd9186a238b/.github/workflows/pr.yml)
- [GitHub xcode-27 public runner announcement](https://github.com/actions/runner-images/issues/14404)
- [Runner SDK inventory](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)
- [SideStore in-place update FAQ](https://docs.sidestore.io/docs/faq)
