#!/bin/bash
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This gate requires macOS CoreData and Xcode; it has not run on Windows." >&2
  exit 2
fi
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: bash run_coredata_migration.sh SIDESTORE_SOURCE [RESULT_PARENT]" >&2
  exit 2
fi
SOURCE_DIR="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULT_PARENT="$SCRIPT_DIR/results"
if [ "$#" -eq 2 ]; then RESULT_PARENT="$2"; fi
mkdir -p "$RESULT_PARENT"
RESULT_PARENT="$(cd "$RESULT_PARENT" && pwd)"
RUN_DIR="$(mktemp -d "$RESULT_PARENT/coredata-17_6-to-17_7.XXXXXX")"
MODEL_DIR="$SOURCE_DIR/AltStore/Core/Model/AltStore.xcdatamodeld"

xcrun momc "$MODEL_DIR/AltStore 17_6.xcdatamodel" "$RUN_DIR/Old.mom"
xcrun momc "$MODEL_DIR/AltStore 17_7.xcdatamodel" "$RUN_DIR/New.mom"
xcrun --sdk macosx swift "$SCRIPT_DIR/verify_coredata_migration.swift" \
  "$RUN_DIR/Old.mom" "$RUN_DIR/New.mom" "$RUN_DIR/fixtures"
echo "Synthetic migration evidence: $RUN_DIR"
