#!/bin/bash
# Setup script for convert_to_grayscale task

echo "=== Setting up Convert to Grayscale Task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Clean previous output
rm -f /home/ga/Documents/exports/water_lilies_grayscale.png

# Verify source file exists and is color
if [ -f "/home/ga/Documents/krita/water_lilies.png" ]; then
    dims=$(get_image_dimensions "/home/ga/Documents/krita/water_lilies.png")
    cs=$(get_image_colorspace "/home/ga/Documents/krita/water_lilies.png")
    echo "Source image: water_lilies.png (${dims}, colorspace: ${cs})"
else
    echo "WARNING: Source image not found"
fi

# Record task start timestamp
date +%s > /tmp/task_start_timestamp

# Ensure Krita is running with the source image
kill_krita
sleep 2
ensure_krita_running "/home/ga/Documents/krita/water_lilies.png"
sleep 5

# Focus and maximize
focus_krita
maximize_krita

# Take initial screenshot
take_screenshot /tmp/task_start_screenshot.png

echo "=== Task Setup Complete ==="
echo "Task: Convert water_lilies.png to grayscale and export to /home/ga/Documents/exports/water_lilies_grayscale.png"
