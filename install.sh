#!/bin/bash
# hermes-semantic-search installer
# Usage: bash install.sh

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_AGENT="$HERMES_HOME/hermes-agent"
VENV_PYTHON="$HERMES_AGENT/venv/bin/python"
PLUGIN_DIR="$HERMES_HOME/plugins/semantic-search"
SCRIPTS_DIR="$HERMES_HOME/scripts"

echo "=== hermes-semantic-search installer ==="

# 1. Check prerequisites
if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: Hermes venv not found at $VENV_PYTHON"
  echo "  Make sure hermes-agent is installed at $HERMES_AGENT"
  exit 1
fi

if ! curl -s http://127.0.0.1:11434/api/tags 2>/dev/null | grep -q "bge-m3"; then
  echo "WARNING: bge-m3 model not found in Ollama."
  echo "  Run: ollama pull bge-m3"
  echo "  (continuing anyway — you can pull it later)"
fi

# 2. Install sqlite-vec into Hermes venv
echo ""
echo "[1/5] Installing sqlite-vec..."
"$VENV_PYTHON" -m pip install --quiet sqlite-vec
echo "  ✓ sqlite-vec installed"

# 3. Copy scripts
echo ""
echo "[2/5] Installing scripts..."
mkdir -p "$SCRIPTS_DIR"
cp scripts/semantic_index.py "$SCRIPTS_DIR/semantic_index.py"
cp scripts/session_finalize_hook.py "$SCRIPTS_DIR/session_finalize_hook.py"
cp scripts/semantic_index_cron.sh "$SCRIPTS_DIR/semantic_index_cron.sh"
chmod +x "$SCRIPTS_DIR/semantic_index_cron.sh"
echo "  ✓ scripts installed to $SCRIPTS_DIR"

# 4. Install plugin
echo ""
echo "[3/5] Installing plugin..."
mkdir -p "$PLUGIN_DIR"
cp plugin/__init__.py "$PLUGIN_DIR/__init__.py"
cp plugin/plugin.yaml "$PLUGIN_DIR/plugin.yaml"
echo "  ✓ plugin installed to $PLUGIN_DIR"

# 5. Enable plugin in config.yaml
echo ""
echo "[4/5] Enabling plugin..."
CONFIG="$HERMES_HOME/config.yaml"
if grep -q "semantic-search" "$CONFIG" 2>/dev/null; then
  echo "  ✓ already enabled in config.yaml"
else
  if grep -q "^plugins:" "$CONFIG" 2>/dev/null; then
    # plugins section exists — add under enabled:
    if grep -q "  enabled:" "$CONFIG" 2>/dev/null; then
      sed -i.bak '/  enabled:/a\  - semantic-search' "$CONFIG"
    else
      sed -i.bak '/^plugins:/a\  enabled:\n  - semantic-search' "$CONFIG"
    fi
  else
    # no plugins section — append
    printf '\nplugins:\n  enabled:\n  - semantic-search\n' >> "$CONFIG"
  fi
  echo "  ✓ added to $CONFIG"
fi

# 6. Register session-end hook
echo ""
echo "[5/5] Registering session-end hook..."
CLI_CONFIG="$HERMES_HOME/cli-config.yaml"
if grep -q "session_finalize_hook" "$CLI_CONFIG" 2>/dev/null; then
  echo "  ✓ hook already registered in cli-config.yaml"
else
  if [ ! -f "$CLI_CONFIG" ]; then
    cat > "$CLI_CONFIG" <<EOF
hooks:
  - event: on_session_finalize
    command: $VENV_PYTHON $SCRIPTS_DIR/session_finalize_hook.py
EOF
  else
    cat >> "$CLI_CONFIG" <<EOF

hooks:
  - event: on_session_finalize
    command: $VENV_PYTHON $SCRIPTS_DIR/session_finalize_hook.py
EOF
  fi
  echo "  ✓ hook registered in $CLI_CONFIG"
fi

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Next steps:"
echo "  1. Run initial index (background, ~1-2 min for 300 sessions):"
echo "     $VENV_PYTHON $SCRIPTS_DIR/semantic_index.py index"
echo ""
echo "  2. Check stats:"
echo "     $VENV_PYTHON $SCRIPTS_DIR/semantic_index.py stats"
echo ""
echo "  3. Restart Hermes — the 'semantic_session_search' tool will be available."
echo ""
echo "  4. (Optional) Set up hourly cron via Hermes:"
echo "     Ask Hermes: 'set up hourly cron for semantic index'"
