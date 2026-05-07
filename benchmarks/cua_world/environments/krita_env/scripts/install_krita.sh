#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

echo "=== Installing Krita Environment ==="

# ── Section 1: System utilities ──
echo "Installing system utilities..."
apt-get update
apt-get install -y \
    scrot wmctrl xdotool imagemagick \
    python3-pip python3-pil \
    wget curl unzip jq

# ── Section 2: Mesa/OpenGL for software rendering ──
echo "Installing OpenGL libraries for software rendering..."
apt-get install -y \
    libgl1-mesa-glx libgl1-mesa-dri mesa-utils \
    libglu1-mesa libosmesa6 libegl1-mesa

# Set software rendering globally (no GPU in container)
echo 'export LIBGL_ALWAYS_SOFTWARE=1' >> /etc/environment
echo 'export GALLIUM_DRIVER=llvmpipe' >> /etc/environment

# ── Section 3: Krita ──
echo "Installing Krita..."
apt-get install -y software-properties-common
add-apt-repository -y ppa:ubuntuhandbook1/krita || true
apt-get update
apt-get install -y krita || {
    echo "PPA install failed, trying default repo..."
    apt-get install -y krita
}

# Verify installation
KRITA_BIN=$(which krita)
if [ -z "$KRITA_BIN" ]; then
    echo "ERROR: krita binary not found after install"
    exit 1
fi
echo "Krita installed at: $KRITA_BIN"

# ── Section 4: Python dependencies for verifiers ──
echo "Installing Python dependencies..."
pip3 install --break-system-packages Pillow 2>/dev/null || pip3 install Pillow

# ── Section 5: Cleanup ──
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "=== Krita Installation Complete ==="
