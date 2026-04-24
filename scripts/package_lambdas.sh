#!/usr/bin/env bash
# =============================================================================
# package_lambdas.sh — AA-CIS S11 Phase 4 (v8 - no cd in function)
# =============================================================================

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$APP_DIR/dist/lambdas"
BUILD_DIR="$APP_DIR/dist/build"
VENV_PIP="$APP_DIR/.venv/bin/pip"

[[ ! -f "$VENV_PIP" ]] && { echo "❌ venv pip not found: $VENV_PIP"; exit 1; }

echo "📦 AA-CIS Lambda Packager v8"
echo "App dir: $APP_DIR"
echo ""

rm -rf "$BUILD_DIR"
rm -f "$DIST_DIR"/*.zip 2>/dev/null || true
mkdir -p "$DIST_DIR" "$BUILD_DIR"

package_lambda() {
  local SERVICE=$1
  local ZIP_NAME=$2
  shift 2
  local DEPS=("$@")

  local ZIP_PATH="$DIST_DIR/${ZIP_NAME}.zip"
  local TMP_DIR="$BUILD_DIR/${ZIP_NAME}"

  rm -rf "$TMP_DIR"
  mkdir -p "$TMP_DIR/services"

  echo "🔨 Packaging $SERVICE → ${ZIP_NAME}.zip"

  # Install deps into TMP_DIR
  if [[ ${#DEPS[@]} -gt 0 ]]; then
    "$VENV_PIP" install \
      --quiet \
      --target "$TMP_DIR" \
      --ignore-installed \
      --no-compile \
      "${DEPS[@]}" || true
  fi

  # Copy service + shared
  cp -r "$APP_DIR/services/$SERVICE/." "$TMP_DIR/services/$SERVICE/"
  cp -r "$APP_DIR/shared/." "$TMP_DIR/shared/"

  # Cleanup
  find "$TMP_DIR" -name "*.dist-info"     -type d -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -name "__pycache__"     -type d -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -name "*.pyc"           -delete 2>/dev/null || true
  find "$TMP_DIR" -path "*/pandas/tests*" -exec rm -rf {} + 2>/dev/null || true

  # Zip using pushd/popd — no cd that changes shell's working dir permanently
  pushd "$TMP_DIR" > /dev/null
  zip -r -q "$ZIP_PATH" .
  popd > /dev/null

  rm -rf "$TMP_DIR"

  local SIZE
  SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
  echo "   ✅ ${ZIP_NAME}.zip ($SIZE)"
}

package_lambda "ingestion"        "ingestion"  asyncpg structlog "pydantic>=2.0" openpyxl pandas
package_lambda "seo_intelligence" "seo"        asyncpg structlog "pydantic>=2.0" httpx
package_lambda "validation"       "validation" asyncpg structlog "pydantic>=2.0"
package_lambda "export"           "export"     asyncpg structlog "pydantic>=2.0" httpx

rm -rf "$BUILD_DIR"

echo ""
echo "✅ Done:"
ls -lh "$DIST_DIR/"
