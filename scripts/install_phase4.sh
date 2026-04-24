#!/usr/bin/env bash
# =============================================================================
# install_phase4.sh — Copy S11 Phase 4 files to correct project locations
# Run from: ~/projects/aa-cis/
# =============================================================================

set -euo pipefail

INFRA="$HOME/projects/aa-cis/AA-CIS-Infra"
APP="$HOME/projects/aa-cis/AA-CIS-App"
SRC="$HOME/projects/aa-cis/phase4_files"  # where you extracted the files

echo "🚀 Installing S11 Phase 4 files..."

# --- Lambda module ---
echo "📁 Lambda module..."
cp "$SRC/modules/lambda/main.tf"      "$INFRA/modules/lambda/main.tf"
cp "$SRC/modules/lambda/variables.tf" "$INFRA/modules/lambda/variables.tf"
cp "$SRC/modules/lambda/outputs.tf"   "$INFRA/modules/lambda/outputs.tf"

# --- Step Functions module ---
echo "📁 Step Functions module..."
cp "$SRC/modules/step_functions/main.tf"      "$INFRA/modules/step_functions/main.tf"
cp "$SRC/modules/step_functions/variables.tf" "$INFRA/modules/step_functions/variables.tf"
cp "$SRC/modules/step_functions/outputs.tf"   "$INFRA/modules/step_functions/outputs.tf"

# --- envs/dev ---
echo "📁 envs/dev..."
cp "$SRC/envs/dev/main.tf" "$INFRA/envs/dev/main.tf"

# Append Phase 4 variables to existing variables.tf
if ! grep -q "database_url" "$INFRA/envs/dev/variables.tf" 2>/dev/null; then
  cat "$SRC/envs/dev/variables_phase4_additions.tf" >> "$INFRA/envs/dev/variables.tf"
  echo "   ✅ Appended Phase 4 variables"
else
  echo "   ⏭ Phase 4 variables already present"
fi

# Append Phase 4 outputs to existing outputs.tf
if ! grep -q "state_machine_arn" "$INFRA/envs/dev/outputs.tf" 2>/dev/null; then
  cat "$SRC/envs/dev/outputs_phase4.tf" >> "$INFRA/envs/dev/outputs.tf"
  echo "   ✅ Appended Phase 4 outputs"
else
  echo "   ⏭ Phase 4 outputs already present"
fi

# --- App: packaging script ---
echo "📁 App scripts..."
mkdir -p "$APP/scripts"
cp "$SRC/scripts/package_lambdas.sh" "$APP/scripts/package_lambdas.sh"
chmod +x "$APP/scripts/package_lambdas.sh"

echo ""
echo "✅ All files installed."
echo ""
echo "Next:"
echo "  1. Add tfvars for new variables (database_url, redis_url, etc.)"
echo "  2. cd $APP && bash scripts/package_lambdas.sh"
echo "  3. cd $INFRA/envs/dev && terraform init && terraform plan"
