#!/usr/bin/env bash
# =============================================================================
# package_lambdas.sh — AA-CIS S11 Phase 4 (v8 - no cd in function)
# =============================================================================

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$APP_DIR/dist/lambdas"
BUILD_DIR="$APP_DIR/dist/build"
VENV_PIP="$APP_DIR/.venv/bin/pip"

if [[ ! -f "$VENV_PIP" ]]; then
  echo "⚠ venv not found, using system pip"
  VENV_PIP="$(which pip3 2>/dev/null || which pip 2>/dev/null)"
fi
[[ -z "$VENV_PIP" ]] && { echo "❌ No pip found"; exit 1; }

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

package_lambda "ingestion"        "ingestion"  asyncpg structlog "pydantic>=2.0" openpyxl pandas openai boto3
package_lambda "seo_intelligence" "seo"        asyncpg structlog "pydantic>=2.0" httpx
package_lambda "validation"       "validation" asyncpg structlog "pydantic>=2.0"
package_lambda "export"           "export"     asyncpg structlog "pydantic>=2.0" httpx

rm -rf "$BUILD_DIR"

echo ""
echo "✅ Done:"
ls -lh "$DIST_DIR/"
package_lambda "content_generation" "content" langchain langchain-core langgraph anthropic

# AA-78: brand_brief_parser — flat layout (absolute imports, no services/ nesting)
package_brand_brief_parser() {
  local ZIP_PATH="$DIST_DIR/brand_brief_parser.zip"
  local TMP_DIR="$BUILD_DIR/brand_brief_parser"
  rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
  echo "🔨 Packaging brand_brief_parser → brand_brief_parser.zip"
  "$VENV_PIP" install --quiet --target "$TMP_DIR" --ignore-installed --no-compile \
    "python-docx==1.1.2" "psycopg2-binary==2.9.9" "pydantic==2.7.1" "boto3" || true
  cp "$APP_DIR/services/acp_brand_brief_parser"/*.py "$TMP_DIR/"
  find "$TMP_DIR" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  pushd "$TMP_DIR" > /dev/null
  zip -r -q "$ZIP_PATH" .
  popd > /dev/null
  rm -rf "$TMP_DIR"
  echo "   ✅ brand_brief_parser.zip ($(du -sh "$ZIP_PATH" | cut -f1))"
}
package_brand_brief_parser

# AA-49 H-1: acp-s4-evaluate — flat layout, stdlib + boto3 only (boto3 in Lambda runtime)
package_acp_s4_evaluate() {
  local ZIP_PATH="$DIST_DIR/acp-s4-evaluate.zip"
  local TMP_DIR="$BUILD_DIR/acp-s4-evaluate"
  rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
  echo "🔨 Packaging acp_s4_evaluate → acp-s4-evaluate.zip"
  cp "$APP_DIR/services/acp_s4_evaluate/handler.py" "$TMP_DIR/"
  find "$TMP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  pushd "$TMP_DIR" > /dev/null
  zip -r -q "$ZIP_PATH" .
  popd > /dev/null
  rm -rf "$TMP_DIR"
  echo "   ✅ acp-s4-evaluate.zip ($(du -sh "$ZIP_PATH" | cut -f1))"
}
package_acp_s4_evaluate

# AA-163: acp-s3-campaign-planner — flat layout + acp_shared layer + langfuse
package_acp_s3_campaign_planner() {
  local ZIP_PATH="$DIST_DIR/acp-s3-campaign-planner.zip"
  local TMP_DIR="$BUILD_DIR/acp-s3-campaign-planner"
  rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
  echo "🔨 Packaging acp_s3 → acp-s3-campaign-planner.zip"
  "$VENV_PIP" install --quiet --target "$TMP_DIR" --ignore-installed --no-compile \
    "boto3>=1.34.0" "psycopg2-binary>=2.9" "pydantic>=2.0" "fpdf2>=2.7.9" "langfuse<3.0.0" || true
  # Service files — flat layout so `import handler`, `import planner`, etc. work
  cp "$APP_DIR/services/acp_s3"/*.py "$TMP_DIR/"
  cp -r "$APP_DIR/services/acp_s3/prompts" "$TMP_DIR/prompts"
  # api.schemas needed by run_context.py (sys.path at /var/task covers this)
  mkdir -p "$TMP_DIR/api/schemas"
  touch "$TMP_DIR/api/__init__.py" "$TMP_DIR/api/schemas/__init__.py"
  cp "$APP_DIR/api/schemas/run_context.py" "$TMP_DIR/api/schemas/"
  # acp_shared package for AcpTracer (AA-163)
  cp -r "$APP_DIR/services/acp_shared" "$TMP_DIR/acp_shared"
  find "$TMP_DIR" -name "*.dist-info"  -type d -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -name "__pycache__"  -type d -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -name "*.pyc"        -delete 2>/dev/null || true
  pushd "$TMP_DIR" > /dev/null
  zip -r -q "$ZIP_PATH" .
  popd > /dev/null
  rm -rf "$TMP_DIR"
  echo "   ✅ acp-s3-campaign-planner.zip ($(du -sh "$ZIP_PATH" | cut -f1))"
}
package_acp_s3_campaign_planner
