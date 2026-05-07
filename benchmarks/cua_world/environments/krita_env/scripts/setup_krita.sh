#!/bin/bash
# Setup script for Krita environment
# Do NOT use set -e — robust error handling needed

echo "=== Setting up Krita Environment ==="

# Wait for desktop to be ready
sleep 5

# ── Section 1: Create directories ──
echo "Creating directories..."
mkdir -p /home/ga/Documents/krita
mkdir -p /home/ga/Documents/exports
mkdir -p /home/ga/Pictures
mkdir -p /home/ga/.config
mkdir -p /home/ga/.local/share/krita
mkdir -p /home/ga/.cache/krita

# ── Section 2: Pre-configure Krita (suppress dialogs, disable OpenGL) ──
echo "Configuring Krita..."

cat > /home/ga/.config/kritarc << 'KRITARC'
[General]
LogUsage=false
ShowRootLayer=false
mdi_viewmode=0
showCanvasMessages=false

[KisToolTransform]
filterId=Bicubic

[theme]
Theme=Krita dark
KRITARC

cat > /home/ga/.config/kritadisplayrc << 'DISPLAYRC'
[General]
canvasState=OPENGL_SUCCESS
EnableOpenGL=false
LogUsage=false
DISPLAYRC

chown -R ga:ga /home/ga/.config /home/ga/.local /home/ga/.cache

# ── Section 3: Download real artwork from public sources ──
echo "Downloading sample images from Wikimedia Commons (public domain)..."

# Van Gogh — Starry Night (1889, public domain)
wget -q --timeout=30 -O /home/ga/Documents/krita/starry_night.jpg \
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ea/Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg/1280px-Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg" \
    2>/dev/null && echo "  Downloaded Starry Night" || echo "  WARNING: Failed to download Starry Night"

# NASA Hubble — Pillars of Creation (public domain, US government)
wget -q --timeout=30 -O /home/ga/Documents/krita/pillars_of_creation.jpg \
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/68/Pillars_of_creation_2014_HST_WFC3-UVIS_full-res_denoised.jpg/1280px-Pillars_of_creation_2014_HST_WFC3-UVIS_full-res_denoised.jpg" \
    2>/dev/null && echo "  Downloaded Pillars of Creation" || echo "  WARNING: Failed to download Pillars of Creation"

# Hokusai — The Great Wave off Kanagawa (1831, public domain)
wget -q --timeout=30 -O /home/ga/Documents/krita/great_wave.jpg \
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Tsunami_by_hokusai_19th_century.jpg/1280px-Tsunami_by_hokusai_19th_century.jpg" \
    2>/dev/null && echo "  Downloaded Great Wave" || echo "  WARNING: Failed to download Great Wave"

# Vermeer — Girl with a Pearl Earring (1665, public domain)
wget -q --timeout=30 -O /home/ga/Documents/krita/girl_pearl_earring.jpg \
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0f/1665_Girl_with_a_Pearl_Earring.jpg/800px-1665_Girl_with_a_Pearl_Earring.jpg" \
    2>/dev/null && echo "  Downloaded Girl with Pearl Earring" || echo "  WARNING: Failed to download Girl with Pearl Earring"

# Monet — Water Lilies (1906, public domain)
wget -q --timeout=30 -O /home/ga/Documents/krita/water_lilies.jpg \
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Claude_Monet_-_Water_Lilies_-_1906%2C_Ryerson.jpg/1280px-Claude_Monet_-_Water_Lilies_-_1906%2C_Ryerson.jpg" \
    2>/dev/null && echo "  Downloaded Water Lilies" || echo "  WARNING: Failed to download Water Lilies"

chown -R ga:ga /home/ga/Documents

# ── Section 4: Convert images to PNG working copies ──
echo "Preparing PNG working copies..."
for img in starry_night pillars_of_creation great_wave girl_pearl_earring water_lilies; do
    if [ -f "/home/ga/Documents/krita/${img}.jpg" ]; then
        convert "/home/ga/Documents/krita/${img}.jpg" "/home/ga/Documents/krita/${img}.png" 2>/dev/null && \
            echo "  Converted ${img}.jpg → PNG" || echo "  WARNING: Failed to convert ${img}"
    fi
done

# Record image dimensions for verifiers
echo "Recording image dimensions..."
for img in /home/ga/Documents/krita/*.png; do
    if [ -f "$img" ]; then
        dims=$(identify -format '%w %h' "$img" 2>/dev/null)
        basename=$(basename "$img" .png)
        echo "${basename} ${dims}" >> /home/ga/Documents/krita/image_dimensions.txt
    fi
done

chown -R ga:ga /home/ga/Documents

# ── Section 5: Create .kra file from Starry Night using Krita CLI ──
echo "Creating sample .kra file..."
export DISPLAY=:1
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe

if [ -f "/home/ga/Documents/krita/starry_night.png" ]; then
    # Use offscreen rendering to avoid needing the display
    su - ga -c "QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 krita /home/ga/Documents/krita/starry_night.png --export --export-filename /home/ga/Documents/krita/starry_night.kra" 2>/dev/null && \
        echo "  Created starry_night.kra" || echo "  WARNING: CLI .kra creation failed, will retry during warm-up"
fi

chown -R ga:ga /home/ga/Documents

# ── Section 6: Create launch script ──
cat > /home/ga/launch_krita.sh << 'LAUNCH'
#!/bin/bash
export DISPLAY=:1
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export XAUTHORITY=/home/ga/.Xauthority

if [ -n "$1" ]; then
    setsid krita --nosplash "$1" > /tmp/krita.log 2>&1 &
else
    setsid krita --nosplash --new-image RGBA,U8,1920,1080 > /tmp/krita.log 2>&1 &
fi
echo $! > /tmp/krita.pid
LAUNCH
chmod +x /home/ga/launch_krita.sh
chown ga:ga /home/ga/launch_krita.sh

# ── Section 7: Warm-up launch to initialize Krita state ──
echo "Performing warm-up launch..."
su - ga -c "DISPLAY=:1 LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe setsid krita --nosplash --new-image RGBA,U8,800,600 > /tmp/krita_warmup.log 2>&1 &"

# Wait for Krita window to appear
WAITED=0
while [ $WAITED -lt 120 ]; do
    if xdotool search --name "Krita" 2>/dev/null | head -1 > /dev/null; then
        echo "  Krita window detected after ${WAITED}s"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ $WAITED -ge 120 ]; then
    echo "  WARNING: Krita window not detected after 120s"
fi

# Let Krita fully initialize
sleep 10

# If .kra file wasn't created via CLI, try saving from the running instance
if [ ! -f "/home/ga/Documents/krita/starry_night.kra" ] && [ -f "/home/ga/Documents/krita/starry_night.png" ]; then
    echo "  Retrying .kra creation via running Krita..."
    pkill -u ga krita 2>/dev/null || true
    sleep 3
    su - ga -c "DISPLAY=:1 LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe setsid krita --nosplash /home/ga/Documents/krita/starry_night.png > /tmp/krita_kra.log 2>&1 &"
    sleep 15
    # Use xdotool to save as .kra (Ctrl+Shift+S → type filename → Enter)
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+shift+s 2>/dev/null
    sleep 3
    DISPLAY=:1 xdotool type --clearmodifiers '/home/ga/Documents/krita/starry_night.kra' 2>/dev/null
    sleep 1
    DISPLAY=:1 xdotool key --clearmodifiers Return 2>/dev/null
    sleep 5
fi

# Kill warm-up instance
pkill -u ga krita 2>/dev/null || true
sleep 3
pkill -9 -u ga krita 2>/dev/null || true
sleep 2

chown -R ga:ga /home/ga/Documents

# ── Section 8: Take verification screenshot ──
echo "Taking setup verification screenshot..."
DISPLAY=:1 scrot /tmp/setup_screenshot.png 2>/dev/null || true

echo "=== Krita Setup Complete ==="
echo "Launch:  su - ga -c '/home/ga/launch_krita.sh [file]'"
echo "Images:  /home/ga/Documents/krita/"
echo "Exports: /home/ga/Documents/exports/"
