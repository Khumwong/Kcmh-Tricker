#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON=$(which python3)

echo "================================================"
echo " KCMH Trigger — Installer"
echo "================================================"
echo " Project: $PROJECT_DIR"
echo " Python:  $PYTHON"
echo " Venv:    $VENV_DIR"
echo ""

# 1. ติดตั้ง dependencies
echo "[1/5] Installing system dependencies..."
sudo apt-get install -y sshpass tmux python3-venv
echo "      Done."
echo ""

# 2. สร้าง venv
echo "[2/5] Creating virtual environment..."
$PYTHON -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
echo "      Done."
echo ""

# 3. ติดตั้ง alpide-daq-program
echo "[3/5] Installing alpide-daq-program..."
ALPIDE_BIN="$PROJECT_DIR/alpide/alpide-daq-program"
if [ -f "$ALPIDE_BIN" ]; then
    sudo install -m 755 "$ALPIDE_BIN" /usr/local/bin/alpide-daq-program
    echo "      Installed to /usr/local/bin/alpide-daq-program"
else
    echo "      WARNING: $ALPIDE_BIN not found — skipping (firmware flash will not work)"
fi
echo ""

# 4. สร้าง launch scripts
echo "[4/5] Creating launcher..."
cat > "$PROJECT_DIR/launch_app.sh" <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
export QT_BEARER_POLL_TIMEOUT=0
export QT_NETWORK_DISABLE_CACHE=1
"$VENV_DIR/bin/python" main.py "\$@"
EOF
chmod +x "$PROJECT_DIR/launch_app.sh"
echo "      Done."
echo ""

# 5. สร้าง desktop icons
echo "[5/5] Creating desktop icons..."

DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"

# icon ปกติ
cat > "$DESKTOP_DIR/kcmh-trigger.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=KCMH Trigger
Exec=bash -c '$PROJECT_DIR/launch_app.sh 2>&1 | tee /tmp/kcmh.log'
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
Exec=bash -c '$PROJECT_DIR/launch_app.sh --sim 2>&1 | tee /tmp/kcmh-sim.log'
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
echo " Firmware: alpide/fx3.img + alpide/fpga-v1.0.0.bit"
echo "================================================"
