#!/usr/bin/env bash
# AA-59: Scan for plaintext secrets in codebase
# Usage: bash scripts/scan_secrets.sh

echo "=== Scanning for potential plaintext secrets ==="

FOUND=0

# AWS Access Keys
echo "Checking AWS Access Keys..."
if grep -r "AKIA[A-Z0-9]\{16\}" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.env" --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir=".venv" . 2>/dev/null | grep -v ".example"; then
  echo "⚠️  Found potential AWS Access Key"
  FOUND=1
fi

# Anthropic/OpenAI keys
echo "Checking API keys..."
if grep -r "sk-ant-\|sk-proj-" --include="*.py" --include="*.ts" --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir=".venv" . 2>/dev/null; then
  echo "⚠️  Found potential Anthropic/OpenAI key"
  FOUND=1
fi

# DATABASE_URL with password
echo "Checking DATABASE_URL..."
if grep -r "postgresql://.*:.*@" --include="*.py" --include="*.env" --exclude-dir=".git" --exclude-dir=".venv" --exclude="*.example" . 2>/dev/null | grep -v "localhost\|test\|example\|127.0.0.1"; then
  echo "⚠️  Found potential DATABASE_URL with password"
  FOUND=1
fi

# Check Lambda handler files for hardcoded secrets (sanity check)
echo "Checking Lambda handler files..."
for f in services/*/handler.py; do
  if grep -n "password\|secret\|api_key\s*=" "$f" 2>/dev/null | grep -v "get_secret\|SECRET_ARN\|os.environ\|#\|import"; then
    echo "⚠️  Potential hardcoded secret in $f"
    FOUND=1
  fi
done

if [ $FOUND -eq 0 ]; then
  echo "✅ No plaintext secrets found"
else
  echo ""
  echo "⚠️  Review the findings above."
  echo "   All secrets must use os.environ or boto3 Secrets Manager."
fi
