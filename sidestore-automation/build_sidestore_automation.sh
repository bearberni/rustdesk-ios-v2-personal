#!/bin/bash
# Run only on a clean GitHub macOS runner. No Apple account or signing secrets.
set -euo pipefail

SIDESTORE_REF=151d3378acadcd3b560bb69b1a8da249bf33ce8a
SIDESIGN_REF=7331ad630a600e0e31e4b434b7d8774ca86db39b
MINIMUXER_REF=decbfe190fdb94a380509fe93be7dc950e60f36b
recipe_root="${GITHUB_WORKSPACE:-$(pwd)}"
artifact_dir="${SIDESTORE_ARTIFACT_DIR:-$recipe_root/sidestore-automation-artifact}"
patch_path="${SIDESTORE_PATCH_PATH:-sidestore-automation/personal-automation.patch}"
intent_identifier="${SIDESTORE_INTENT_IDENTIFIER:-ExecuteRenewalV2Intent}"
intent_identifiers="${SIDESTORE_INTENT_IDENTIFIERS:-PrepareRenewalV2Intent,ExecuteRenewalV2Intent,FinalizeRenewalV2Intent}"
xcode_version="${SIDESTORE_XCODE:-27.2}"
case "$intent_identifier" in
  ''|*[!A-Za-z0-9_]*) echo 'Invalid Swift intent type identifier'; exit 1 ;;
esac
if [ "$intent_identifier" != ExecuteRenewalV2Intent ]; then
  echo 'This wireV2 build requires the ExecuteRenewalV2Intent core type'
  exit 1
fi
if [ "$intent_identifiers" != PrepareRenewalV2Intent,ExecuteRenewalV2Intent,FinalizeRenewalV2Intent ]; then
  echo 'This wireV2 build requires all three exact V2 metadata identifiers'
  exit 1
fi
IFS=, read -r -a required_intents <<< "$intent_identifiers"
validator_flags=()
for identifier in "${required_intents[@]}"; do
  case "$identifier" in ''|*[!A-Za-z0-9_]*) echo 'Invalid required intent identifier'; exit 1 ;; esac
  validator_flags+=(--expected-intent "$identifier")
done
case "$xcode_version" in 27.2|27.1) ;; *) echo 'Xcode must be 27.2 or 27.1'; exit 1 ;; esac
case "$patch_path" in /*) ;; *) patch_path="$recipe_root/$patch_path" ;; esac
mkdir -p "$artifact_dir"
# Capture setup, git, dependency resolution, archive and package output, including failures.
exec > >(tee "$artifact_dir/build-full.log") 2>&1
echo "Starting unsigned SideStore build from pinned upstream $SIDESTORE_REF"
if [ "$(uname -s)" != Darwin ]; then echo 'A macOS xcode-27 runner is required'; exit 1; fi
if [ ! -f "$patch_path" ]; then echo "Missing reviewed patch: $patch_path"; exit 1; fi
for required_recipe in validate_sidestore_automation.py test_validate_sidestore_automation.py run_coredata_migration.sh verify_coredata_migration.swift; do
  if [ ! -f "$recipe_root/sidestore-automation/$required_recipe" ]; then
    echo "Missing reviewed recipe dependency: $required_recipe"; exit 1
  fi
done

selected_xcode=''
for candidate in "/Applications/Xcode_${xcode_version}.app" "/Applications/Xcode_${xcode_version}_Release_Candidate.app"; do
  if [ -x "$candidate/Contents/Developer/usr/bin/xcodebuild" ]; then selected_xcode="$candidate"; break; fi
done
if [ -z "$selected_xcode" ]; then
  echo "Requested Xcode $xcode_version not installed; no implicit SDK downgrade is allowed."
  ls -d /Applications/Xcode*.app || true
  exit 1
fi
export DEVELOPER_DIR="$selected_xcode/Contents/Developer"
xcodebuild -version | tee "$artifact_dir/xcode-version.txt"
xcodebuild -showsdks | tee "$artifact_dir/xcode-sdks.txt"
sdk_version="$(xcrun --sdk iphoneos --show-sdk-version)"
if [ "${sdk_version%%.*}" -lt 27 ]; then echo "iOS SDK 27+ required, got $sdk_version"; exit 1; fi
export SDK_OBSERVED="$sdk_version"
if ! command -v ldid >/dev/null 2>&1; then brew install ldid; fi

source_parent="${RUNNER_TEMP:-$recipe_root}"
source_dir="$(mktemp -d "$source_parent/sidestore-personal.XXXXXX")"
git -C "$source_dir" init
git -C "$source_dir" remote add origin https://github.com/SideStore/SideStore.git
git -C "$source_dir" fetch --depth 1 origin "$SIDESTORE_REF"
git -C "$source_dir" checkout --detach FETCH_HEAD
test "$(git -C "$source_dir" rev-parse HEAD)" = "$SIDESTORE_REF"
git -C "$source_dir" submodule update --init --recursive --depth 1
test "$(git -C "$source_dir/Dependencies/SideSign" rev-parse HEAD)" = "$SIDESIGN_REF"
test "$(git -C "$source_dir/Dependencies/minimuxer" rev-parse HEAD)" = "$MINIMUXER_REF"
git -C "$source_dir" submodule status --recursive | tee "$artifact_dir/submodules.txt"

# Root supplies one reviewed patch. Scope is explicit; unrelated signing/pairing code is excluded.
git -C "$source_dir" apply --numstat "$patch_path" > "$artifact_dir/patch-numstat.txt"
python3 - "$artifact_dir/patch-numstat.txt" <<'PY'
from pathlib import Path
import sys
rows = Path(sys.argv[1]).read_text().splitlines()
if not rows:
    raise SystemExit('The automation patch is empty')
allowed_sources = {
    'SideStore/Core/Automation/AutomationRefreshIntent.swift',
    'SideStore/Core/Automation/AutomationRefreshCoordinator.swift',
    'SideStore/Core/Automation/AutomationProfileEvidence.swift',
    'SideStore/Core/Automation/AutomationRefreshPolicy.swift',
    'AltStore/Managing Apps/AppManager.swift',
    'SideStore/Core/Operations/PipelineOperations/RefreshAppOperation.swift',
    'SideStore/Core/Operations/PipelineRunner.swift',
    'SideStore/Core/Operations/PipelineOperations/PreflightChecksOperation.swift',
    'SideStore/Core/Operations/PipelineOperations/UpdateAppCertificateOperation.swift',
    'Package.swift',
    'AutomationTests/AutomationRefreshPolicyTests.swift',
    'AutomationTests/AutomationDiagnosticsTests.swift',
    'AutomationTests/AutomationPortConfigurationTests.swift',
    'AutomationTests/UpgradeStorageTests.swift',
    'SideStore/Core/Automation/AutomationPortConfiguration.swift',
    'SideStore/Core/Automation/AutomationUpgradeStorage.swift',
    'SideStore/Core/DeviceApi/MinimuxerWrapper.swift',
    'SideStore/Core/Bonjour/BonjourDiscoveryManager.swift',
    'AltStore/AppDelegate.swift',
    'AltStore/LaunchViewController.swift',
    'AltStore/Intents/Legacy/IntentHandler.swift',
    'AltStore/Intents/App Intents/RefreshAllAppsIntent.swift',
    'AltStore/Core/Intents/ViewAppIntentHandler.swift',
    'SideStore/MaintenanceManager.swift',
    'SQLite3/module.modulemap',
    'SQLite3/shim.h',
}
for row in rows:
    added, removed, name = row.split('\t', 2)
    if added == '-' or removed == '-' or name not in allowed_sources:
        raise SystemExit('Patch changes a file outside the reviewed intent scope: ' + name)
PY
git -C "$source_dir" apply --check "$patch_path"
git -C "$source_dir" apply "$patch_path"
cp "$patch_path" "$artifact_dir/applied.patch"
git -C "$source_dir" diff --stat | tee "$artifact_dir/patch-stat.txt"
python3 - "$source_dir/SideStore/Core/Automation" "$intent_identifier" <<'PY'
from pathlib import Path
import re, sys
pattern = re.compile(r'\b(?:struct|class)\s+' + re.escape(sys.argv[2]) + r'(?:\s|:)')
if not any(pattern.search(p.read_text()) for p in Path(sys.argv[1]).rglob('*.swift')):
    raise SystemExit('Expected intent is absent after applying patch: ' + sys.argv[2])
PY

export SOURCE_DIR="$source_dir" SIDESTORE_REF SIDESIGN_REF MINIMUXER_REF
export PATCH_PATH="$patch_path" INTENT_IDENTIFIER="$intent_identifier" INTENT_IDENTIFIERS="$intent_identifiers"
export PERSONAL_VERSION="0.7.0-personalautomation.${GITHUB_RUN_NUMBER:-1}+151d3378"
python3 - "$artifact_dir/provenance.json" <<'PY'
from pathlib import Path
import os, hashlib, json, subprocess, sys
patch = Path(os.environ['PATCH_PATH']).read_bytes()
def run(*args): return subprocess.check_output(args, text=True).strip()
d = {
  'upstream_repository': 'SideStore/SideStore',
  'upstream_commit': os.environ['SIDESTORE_REF'],
  'SideSign_commit': os.environ['SIDESIGN_REF'],
  'minimuxer_commit': os.environ['MINIMUXER_REF'],
  'recipe_commit': os.environ.get('GITHUB_SHA'),
  'patch_sha256': hashlib.sha256(patch).hexdigest(),
  'requested_intent_identifier': os.environ['INTENT_IDENTIFIER'],
  'required_registered_intent_identifiers': os.environ['INTENT_IDENTIFIERS'].split(','),
  'marketing_version': os.environ['PERSONAL_VERSION'],
  'observed_iphoneos_sdk': os.environ['SDK_OBSERVED'],
  'xcode_version': run('xcodebuild', '-version'),
  'Apple_credentials_uploaded': False,
  'valid_device_code_signing_performed': False,
  'on_device_import_or_runtime_verified': False,
}
Path(sys.argv[1]).write_text(json.dumps(d, indent=2) + '\n')
PY

cd "$source_dir"
# Pure policy-state tests have no Apple signing or device dependencies.
swift test 2>&1 | tee "$artifact_dir/swift-policy-tests.log"

# Synthetic official-model17_6->17_7 gate; contains no real phone data.
bash "$recipe_root/sidestore-automation/run_coredata_migration.sh" "$source_dir" "$artifact_dir/coredata-migration"
python3 "$recipe_root/sidestore-automation/test_validate_sidestore_automation.py" 2>&1 | tee "$artifact_dir/identity-validator-tests.log"
cp AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved "$artifact_dir/Package.resolved.before"
xcodebuild -resolvePackageDependencies -project AltStore.xcodeproj -scheme SideStore -onlyUsePackageVersionsFromResolvedFile
cp AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved "$artifact_dir/Package.resolved.after"
python3 - "$artifact_dir/Package.resolved.before" "$artifact_dir/Package.resolved.after" <<'PY'
from pathlib import Path
import json, sys
def pins(path):
    d = json.loads(Path(path).read_text())
    return {p['identity']: {k: p.get(k) for k in ('kind', 'location', 'state')} for p in d['pins']}
if pins(sys.argv[1]) != pins(sys.argv[2]):
    raise SystemExit('Swift Package pins changed; no automatic dependency upgrade allowed')
print('All resolved Swift Package revisions match the pinned source')
PY

# Official Makefile disables code signing and uses placeholder team identity.
# Do not supply BUNDLE_ID_SUFFIX: personal signing will apply the same user's suffix on device.
make -B build BUILD_CONFIG=Release MARKETING_VERSION="$PERSONAL_VERSION"
make fakesign
make ipa
cp SideStore.ipa "$artifact_dir/SideStore-personalautomation-unsigned.ipa"
cp SideStore.xcarchive/Products/Applications/SideStore.app/Info.plist "$artifact_dir/Info.plist"
python3 "$recipe_root/sidestore-automation/validate_sidestore_automation.py" \
  "$artifact_dir/SideStore-personalautomation-unsigned.ipa" \
  "${validator_flags[@]}" \
  --expected-source-suffix 151d3378 \
  --output-dir "$artifact_dir"
echo 'Unsigned IPA and intent metadata are ready. Actual personal signing and phone acceptance remain pending.'
