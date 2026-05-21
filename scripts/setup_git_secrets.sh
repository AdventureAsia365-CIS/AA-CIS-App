#!/usr/bin/env bash
# AA-59: Install git-secrets hooks for AA-CIS-App
# Run once per developer: bash scripts/setup_git_secrets.sh

set -e

# Check git-secrets installed
if ! command -v git-secrets &> /dev/null; then
  echo "Installing git-secrets..."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    brew install git-secrets
  else
    # Linux/WSL2
    git clone https://github.com/awslabs/git-secrets.git /tmp/git-secrets
    cd /tmp/git-secrets && sudo make install && cd -
    rm -rf /tmp/git-secrets
  fi
fi

# Install hooks
git secrets --install -f
git secrets --register-aws

# Add custom patterns
git secrets --add 'AKIA[A-Z0-9]{16}'                          # AWS Access Key
git secrets --add '[0-9a-zA-Z/+]{40}'                         # AWS Secret Key pattern
git secrets --add 'sk-[a-zA-Z0-9]{32,}'                       # OpenAI / Anthropic keys
git secrets --add 'cis_[a-zA-Z0-9_\-]{20,}'                   # CIS API keys

echo "✅ git-secrets installed and configured for AA-CIS-App"
echo "   Hooks active: pre-commit, commit-msg, prepare-commit-msg"
