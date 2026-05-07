#!/bin/bash
# Setup script for resize_image task

echo "=== Setting up Resize Image Task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Clean previous output
rm -f /home/ga/Documents/exports/banner_1280x720.png

# Verify source file exists
if [ -f "/home/ga/Documents/krita/pillars_of_creation.png" ]; then
    dims=$(get_image_dimensions "/home/ga/Documents/krita/pillars_of_creation.png")
    echo "Source image: pillars_of_creation.png (${dims})"
else
    echo "WARNING: Source image not found"
fi

# Record task start timestamp
date +%s > /tmp/task_start_timestamp

# Ensure Krita is running with the source image
kill_krita
sleep 2
ensure_krita_running "/home/ga/Documents/krita/pillars_of_creation.png"
sleep 5

# Focus and maximize
focus_krita
maximize_krita

# Take initial screenshot
take_screenshot /tmp/task_start_screenshot.png

echo "=== Task Setup Complete ==="
echo "Task: Resize image to 1280x720 and save as /home/ga/Documents/exports/banner_1280x720.png"
