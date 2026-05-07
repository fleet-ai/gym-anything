#!/bin/bash
# Setup script for create_layered_composition task

echo "=== Setting up Create Layered Composition Task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Clean previous output
rm -f /home/ga/Documents/exports/illustration_project.kra

# Ensure exports directory exists
mkdir -p /home/ga/Documents/exports
chown -R ga:ga /home/ga/Documents/exports

# Record task start timestamp
date +%s > /tmp/task_start_timestamp

# Start Krita fresh with no file (agent will create new document)
kill_krita
sleep 2
ensure_krita_running
sleep 5

# Focus and maximize
focus_krita
maximize_krita

# Take initial screenshot
take_screenshot /tmp/task_start_screenshot.png

echo "=== Task Setup Complete ==="
echo "Task: Create 1920x1080 image with 5 named layers and save as /home/ga/Documents/exports/illustration_project.kra"
