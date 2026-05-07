#!/bin/bash
# Setup script for crop_and_export task

echo "=== Setting up Crop and Export Task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Clean previous output
rm -f /home/ga/Documents/exports/great_wave_cropped.png

# Verify source file exists and record dimensions
if [ -f "/home/ga/Documents/krita/great_wave.png" ]; then
    dims=$(get_image_dimensions "/home/ga/Documents/krita/great_wave.png")
    echo "Source image: great_wave.png (${dims})"
    echo "$dims" > /tmp/source_dimensions.txt
else
    echo "WARNING: Source image not found"
fi

# Record task start timestamp
date +%s > /tmp/task_start_timestamp

# Ensure Krita is running with the source image
kill_krita
sleep 2
ensure_krita_running "/home/ga/Documents/krita/great_wave.png"
sleep 5

# Focus and maximize
focus_krita
maximize_krita

# Take initial screenshot
take_screenshot /tmp/task_start_screenshot.png

echo "=== Task Setup Complete ==="
echo "Task: Crop great_wave.png to 640x480 from top-left and export to /home/ga/Documents/exports/great_wave_cropped.png"
