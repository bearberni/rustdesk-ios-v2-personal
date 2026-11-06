#!/usr/bin/env bash
set -euo pipefail

RECIPE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$RECIPE_ROOT/build-lock.json"
BUILD_ROOT="$RECIPE_ROOT/.build"
DIST="$RECIPE_ROOT/dist"
export GIT_TERMINAL_PROMPT=0
export FLUTTER_SUPPRESS_ANALYTICS=true DART_SUPPRESS_ANALYTICS=true
export HOMEBREW_NO_AUTO_UPDATE=1 CARGO_BUILD_JOBS=3 VCPKG_MAX_CONCURRENCY=3
export VCPKG_BINARY_SOURCES=clear

fail() { printf '%s\n' "$*" >&2; exit 1; }
value() {
  python3 - "$LOCK" "$1" <<'PY'
import json, sys
item = json.load(open(sys.argv[1], encoding="utf-8"))
for key in sys.argv[2].split("."):
    item = item[key]
print(item)
PY
}
clone_commit() {
  local repository="$1" commit="$2" destination="$3"
  git init -q "$destination"
  git -C "$destination" remote add origin "$repository"
  git -C "$destination" fetch --depth=1 origin "$commit"
  git -C "$destination" -c advice.detachedHead=false checkout --detach FETCH_HEAD
  [[ "$(git -C "$destination" rev-parse HEAD)" == "$commit" ]] || fail "Commit mismatch"
}
fetch_flutter_release_tag() {
  local sdk="$1" version="$2" commit="$3"
  # Flutter determines its SDK version from local release tags. A SHA-only
  # shallow fetch otherwise leaves the framework at 0.0.0-unknown.
  git -C "$sdk" fetch --depth=1 origin "refs/tags/$version:refs/tags/$version"
  [[ "$(git -C "$sdk" rev-parse "refs/tags/$version^{commit}")" == "$commit" ]] || fail "Flutter release tag no longer matches the pinned commit"
}
verify_flutter_version() {
  local sdk="$1" version="$2" commit="$3" report="$4"
  "$sdk/bin/flutter" --disable-analytics
  "$sdk/bin/flutter" --version --machine > "$report"
  python3 - "$report" "$version" "$commit" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    result = json.load(stream)
if result.get("frameworkVersion") != sys.argv[2] or result.get("frameworkRevision") != sys.argv[3]:
    raise SystemExit(f"Unexpected Flutter identity: {result.get('frameworkVersion')} {result.get('frameworkRevision')}")
print(f"Verified Flutter SDK: {result['frameworkVersion']} {result['frameworkRevision']}")
PY
}

[[ "$(uname -s)" == Darwin ]] || fail "This build requires macOS; Windows static checks do not compile iOS."
[[ "$(uname -m)" == x86_64 ]] || fail "This recipe was prepared for the pinned Intel runner."
[[ ! -e "$BUILD_ROOT" && ! -e "$DIST" ]] || fail "Use a fresh workspace; .build/ or dist/ already exists."
export DEVELOPER_DIR="$(value tools.xcode_directory)"
[[ -d "$DEVELOPER_DIR" ]] || fail "Pinned Xcode is absent; no automatic fallback is allowed."
[[ "$(xcodebuild -version)" == $'Xcode 16.4\nBuild version 16F6' ]] || fail "Unexpected Xcode version/build."
ruby -e 'abort "Expected runner Ruby 3.3.x" unless RUBY_VERSION.start_with?("3.3.")'
mkdir -p "$BUILD_ROOT" "$DIST"
exec > >(tee "$DIST/build.log") 2>&1

SOURCE="$BUILD_ROOT/rustdesk"
TOOLS="$BUILD_ROOT/tools"
mkdir -p "$TOOLS"
clone_commit "$(value source.repository)" "$(value source.commit)" "$SOURCE"
git -C "$SOURCE" submodule update --init --recursive --depth=1
python3 "$RECIPE_ROOT/scripts/prepare_source.py" --source "$SOURCE" --lock "$LOCK" --output "$DIST/source-preparation.json"

clone_commit https://github.com/flutter/flutter.git "$(value tools.flutter.commit)" "$TOOLS/flutter"
clone_commit https://github.com/flutter/flutter.git "$(value tools.bridge_flutter.commit)" "$TOOLS/flutter-bridge"
fetch_flutter_release_tag "$TOOLS/flutter" "$(value tools.flutter.version)" "$(value tools.flutter.commit)"
fetch_flutter_release_tag "$TOOLS/flutter-bridge" "$(value tools.bridge_flutter.version)" "$(value tools.bridge_flutter.commit)"
# Match the upstream patch used for the pinned 3.24.5 SDK.
git -C "$TOOLS/flutter" apply --check "$SOURCE/.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff"
git -C "$TOOLS/flutter" apply "$SOURCE/.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff"
verify_flutter_version "$TOOLS/flutter" "$(value tools.flutter.version)" "$(value tools.flutter.commit)" "$DIST/flutter-main-sdk.json"
verify_flutter_version "$TOOLS/flutter-bridge" "$(value tools.bridge_flutter.version)" "$(value tools.bridge_flutter.commit)" "$DIST/flutter-bridge-sdk.json"

export RUSTUP_TOOLCHAIN="$(value tools.rust)"
rustup toolchain install "$RUSTUP_TOOLCHAIN" --profile minimal --component rustfmt --target aarch64-apple-ios
export PATH="$TOOLS/flutter/bin:$HOME/.cargo/bin:$PATH"
flutter --disable-analytics
flutter precache --ios
brew install nasm yasm pkg-config ninja

# Keep tool installation local to this ephemeral workspace.
python3 -m venv "$TOOLS/python"
"$TOOLS/python/bin/python" -m pip install "cmake==$(value tools.cmake)"
export PATH="$TOOLS/python/bin:$PATH"
export GEM_HOME="$TOOLS/gems"
export GEM_PATH="$GEM_HOME:$(ruby -e 'puts Gem.default_path.join(":")')"
export PATH="$GEM_HOME/bin:$PATH"
gem install cocoapods --version "$(value tools.cocoapods)" --no-document --install-dir "$GEM_HOME"
# A RubyGems launcher can select a newer preinstalled gem from GEM_PATH even
# when this GEM_HOME/bin directory is first in PATH. Force the version for
# both our commands and Flutter's subprocesses with the supported selector.
mkdir -p "$TOOLS/pinned-bin"
cat > "$TOOLS/pinned-bin/pod" <<POD
#!/usr/bin/env bash
set -euo pipefail
exec "$GEM_HOME/bin/pod" "_$(value tools.cocoapods)_" "\$@"
POD
chmod +x "$TOOLS/pinned-bin/pod"
export PATH="$TOOLS/pinned-bin:$PATH"
hash -r
SELECTED_POD_VERSION="$(pod --version)"
printf 'Selected CocoaPods: %s\n' "$SELECTED_POD_VERSION"
[[ "$SELECTED_POD_VERSION" == "$(value tools.cocoapods)" ]] || fail "Unexpected CocoaPods version"

export VCPKG_ROOT="$TOOLS/vcpkg"
clone_commit https://github.com/microsoft/vcpkg.git "$(value tools.vcpkg_commit)" "$VCPKG_ROOT"
"$VCPKG_ROOT/bootstrap-vcpkg.sh" -disableMetrics
(
  cd "$SOURCE"
  "$VCPKG_ROOT/vcpkg" install --triplet "$(value tools.vcpkg_triplet)" --x-install-root="$VCPKG_ROOT/installed"
)

cargo install cargo-expand --version "$(value tools.cargo_expand)" --locked
cargo install flutter_rust_bridge_codegen --version "$(value tools.bridge_codegen)" --features uuid --locked

# Upstream generates the default bridge with Flutter 3.22.3 and extended_text 13.
# Keep this temporary resolver result for provenance, then restore the runtime lockfiles.
cp "$SOURCE/flutter/pubspec.yaml" "$BUILD_ROOT/runtime-pubspec.yaml"
cp "$SOURCE/flutter/pubspec.lock" "$BUILD_ROOT/runtime-pubspec.lock"
python3 - "$SOURCE/flutter/pubspec.yaml" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
old = "extended_text: 14.0.0"
if s.count(old) != 1:
    raise SystemExit("Unexpected bridge dependency declaration")
p.write_text(s.replace(old, "extended_text: 13.0.0"), encoding="utf-8")
PY
(
  export PATH="$TOOLS/flutter-bridge/bin:$PATH"
  flutter --disable-analytics
  cd "$SOURCE/flutter"
  flutter pub get
  cp pubspec.lock "$DIST/bridge-pubspec.lock"
  cd "$SOURCE"
  flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart --c-output ./flutter/macos/Runner/bridge_generated.h
  cp flutter/macos/Runner/bridge_generated.h flutter/ios/Runner/bridge_generated.h
)
cp "$BUILD_ROOT/runtime-pubspec.yaml" "$SOURCE/flutter/pubspec.yaml"
cp "$BUILD_ROOT/runtime-pubspec.lock" "$SOURCE/flutter/pubspec.lock"
(
  cd "$SOURCE/flutter"
  flutter pub get --enforce-lockfile
  cd ios
  pod install --deployment
)

(
  cd "$SOURCE"
  cargo build --locked --features flutter,hwcodec --release --target aarch64-apple-ios --lib
)
[[ -s "$SOURCE/target/aarch64-apple-ios/release/liblibrustdesk.a" ]] || fail "Native core is missing"
(
  cd "$SOURCE/flutter"
  flutter build ipa --release --no-codesign --no-pub --build-name "$(value identity.version)" --build-number "${GITHUB_RUN_NUMBER:-1}"
)

# Flutter 3.24.5 explicitly skips IPA export when --no-codesign is selected.
# Package the archived .app without changing or claiming to sign its contents.
ARCHIVE_APP="$(python3 - "$SOURCE/flutter/build/ios/archive" <<'PY'
from pathlib import Path
import sys
apps = list(Path(sys.argv[1]).glob("*.xcarchive/Products/Applications/*.app"))
if len(apps) != 1:
    raise SystemExit(f"Expected exactly one archived device app, found {len(apps)}")
print(apps[0])
PY
)"
mkdir -p "$BUILD_ROOT/package/Payload"
ditto "$ARCHIVE_APP" "$BUILD_ROOT/package/Payload/$(basename "$ARCHIVE_APP")"
(
  cd "$BUILD_ROOT/package"
  /usr/bin/zip -q -r -y "$DIST/RustDesk-V2-unsigned.ipa" Payload
)
python3 "$RECIPE_ROOT/scripts/verify_artifact.py" --ipa "$DIST/RustDesk-V2-unsigned.ipa" --lock "$LOCK" --output "$DIST/verification.json"

# Include corresponding source and these recipes with the modified AGPL application.
# Large outputs, caches, git metadata, and installed SDKs/dependencies are excluded.
mkdir -p "$SOURCE/personal-build-recipes"
cp "$RECIPE_ROOT/build-lock.json" "$RECIPE_ROOT/README.md" "$RECIPE_ROOT/NOTICE.md" "$SOURCE/personal-build-recipes/"
cp "$RECIPE_ROOT/LICENSE" "$SOURCE/personal-build-recipes/"
cp -R "$RECIPE_ROOT/scripts" "$SOURCE/personal-build-recipes/"
cp -R "$RECIPE_ROOT/tests" "$SOURCE/personal-build-recipes/"
cp -R "$RECIPE_ROOT/.github" "$SOURCE/personal-build-recipes/"
COPYFILE_DISABLE=1 tar -czf "$DIST/RustDesk-V2-corresponding-source.tar.gz" \
  --exclude='.git' --exclude='rustdesk/target' --exclude='rustdesk/flutter/build' \
  --exclude='rustdesk/flutter/.dart_tool' --exclude='rustdesk/flutter/ios/Pods' \
  --exclude='rustdesk/flutter/ios/.symlinks' --exclude='__pycache__' \
  -C "$BUILD_ROOT" rustdesk
cp "$SOURCE/LICENCE" "$DIST/UPSTREAM-LICENCE" 2>/dev/null || cp "$SOURCE/LICENSE" "$DIST/UPSTREAM-LICENSE"
python3 "$RECIPE_ROOT/scripts/make_manifest.py" --recipe "$RECIPE_ROOT" --source "$SOURCE" --dist "$DIST" --tools "$TOOLS"
printf '%s\n' "Unsigned artifacts prepared. Normal signing and real-iPhone acceptance remain required."
