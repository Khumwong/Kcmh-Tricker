#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON=$(which python3)

echo "================================================"
echo " KCMH Trigger — Installer"
echo "================================================"
echo " Project: $PROJECT_DIR"
echo " Python:  $PYTHON"
echo ""

# 1. ติดตั้ง dependencies
echo "[1/3] Installing Python dependencies..."
$PYTHON -m pip install -r "$PROJECT_DIR/requirements.txt"
echo "      Done."
echo ""

# 2. สร้าง launch scripts
echo "[2/3] Creating launcher..."
cat > "$PROJECT_DIR/launch_app.sh" <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
export QT_BEARER_POLL_TIMEOUT=0
export QT_NETWORK_DISABLE_CACHE=1
$PYTHON main.py "\$@"
EOF
chmod +x "$PROJECT_DIR/launch_app.sh"
echo "      Done."
echo ""

# 3. สร้าง desktop icons
echo "[3/3] Creating desktop icons..."

DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"

# icon ปกติ
cat > "$DESKTOP_DIR/kcmh-trigger.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=KCMH Trigger
Exec=$PROJECT_DIR/launch_app.sh
Icon=$PROJECT_DIR/images/scan-eye.svg
Terminal=false
Categories=Utility;
EOF
chmod +x "$DESKTOP_DIR/kcmh-trigger.desktop"

# icon sim
cat > "$DESKTOP_DIR/kcmh-trigger-sim.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=KCMH Trigger (Sim)
Exec=$PROJECT_DIR/launch_app.sh --sim
Icon=$PROJECT_DIR/images/view.svg
Terminal=false
Categories=Utility;
EOF
chmod +x "$DESKTOP_DIR/kcmh-trigger-sim.desktop"

echo "      Done."
echo ""
echo "================================================"
echo " Installation complete!"
echo " Icons created on Desktop:"
echo "   - KCMH Trigger       (real hardware)"
echo "   - KCMH Trigger (Sim) (simulation mode)"
echo "================================================"
