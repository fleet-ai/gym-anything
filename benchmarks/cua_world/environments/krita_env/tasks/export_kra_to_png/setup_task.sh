#!/bin/bash
# Setup script for export_kra_to_png task

echo "=== Setting up Export KRA to PNG Task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Clean previous output
rm -f /home/ga/Documents/exports/starry_night.png

# Verify source .kra file exists
if [ ! -f "/home/ga/Documents/krita/starry_night.kra" ]; then
    echo "WARNING: starry_night.kra not found, creating from PNG..."
    if [ -f "/home/ga/Documents/krita/starry_night.png" ]; then
        su - ga -c "QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 krita /home/ga/Documents/krita/starry_night.png --export --export-filename /home/ga/Documents/krita/starry_night.kra" 2>/dev/null || true
    fi
fi

# Record source file dimensions for verification
if [ -f "/home/ga/Documents/krita/starry_night.kra" ]; then
    echo "Source .kra file found"
else
    echo "WARNING: Could not create .kra file"
fi

# Record task start timestamp
date +%s > /tmp/task_start_timestamp

# Ensure Krita is running
ensure_krita_running
sleep 5

# Focus and maximize
focus_krita
maximize_krita

# Take initial screenshot
take_screenshot /tmp/task_start_screenshot.png

echo "=== Task Setup Complete ==="
echo "Task: Export /home/ga/Documents/krita/starry_night.kra as PNG to /home/ga/Documents/exports/starry_night.png"
