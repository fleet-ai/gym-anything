#!/bin/bash
# Shared utility functions for Krita environment tasks

export DISPLAY=:1
export XAUTHORITY=/home/ga/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe

# ── Screenshot ──

take_screenshot() {
    local output_file="${1:-/tmp/screenshot.png}"
    DISPLAY=:1 scrot "$output_file" 2>/dev/null || \
    DISPLAY=:1 import -window root "$output_file" 2>/dev/null || \
    echo "WARNING: Failed to take screenshot"
}

# ── Window management ──

get_krita_window_id() {
    xdotool search --name "Krita" 2>/dev/null | head -1
}

is_krita_running() {
    if pgrep -u ga -f krita > /dev/null 2>&1; then
        echo "true"
    else
        echo "false"
    fi
}

ensure_krita_running() {
    local file_arg="${1:-}"
    if [ "$(is_krita_running)" = "true" ]; then
        echo "Krita is already running"
        return 0
    fi

    echo "Starting Krita..."
    if [ -n "$file_arg" ]; then
        su - ga -c "DISPLAY=:1 LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe setsid krita --nosplash '$file_arg' > /tmp/krita.log 2>&1 &"
    else
        su - ga -c "DISPLAY=:1 LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe setsid krita --nosplash --new-image RGBA,U8,1920,1080 > /tmp/krita.log 2>&1 &"
    fi

    # Wait for window to appear
    local waited=0
    while [ $waited -lt 90 ]; do
        if get_krita_window_id > /dev/null 2>&1; then
            echo "Krita window detected after ${waited}s"
            sleep 5
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done

    echo "WARNING: Krita window not detected after 90s"
    return 1
}

focus_krita() {
    local wid
    wid=$(get_krita_window_id)
    if [ -n "$wid" ]; then
        DISPLAY=:1 xdotool windowactivate "$wid" 2>/dev/null
        DISPLAY=:1 xdotool windowfocus "$wid" 2>/dev/null
        sleep 0.5
    else
        echo "WARNING: No Krita window found to focus"
    fi
}

maximize_krita() {
    local wid
    wid=$(get_krita_window_id)
    if [ -n "$wid" ]; then
        DISPLAY=:1 wmctrl -i -r "$wid" -b add,maximized_vert,maximized_horz 2>/dev/null
        sleep 0.5
    fi
}

kill_krita() {
    pkill -u ga -f krita 2>/dev/null || true
    sleep 2
    pkill -9 -u ga -f krita 2>/dev/null || true
    sleep 1
}

restart_krita() {
    local file_arg="${1:-}"
    kill_krita
    sleep 2
    ensure_krita_running "$file_arg"
    focus_krita
    maximize_krita
}

# ── Krita-specific helpers ──

krita_open_file() {
    local filepath="$1"
    focus_krita
    sleep 0.5
    # Ctrl+O to open file dialog
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+o
    sleep 2
    # Clear current path and type new path
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+a
    sleep 0.3
    DISPLAY=:1 xdotool type --clearmodifiers "$filepath"
    sleep 0.5
    DISPLAY=:1 xdotool key --clearmodifiers Return
    sleep 3
}

krita_save_as() {
    local filepath="$1"
    focus_krita
    sleep 0.5
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+shift+s
    sleep 2
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+a
    sleep 0.3
    DISPLAY=:1 xdotool type --clearmodifiers "$filepath"
    sleep 0.5
    DISPLAY=:1 xdotool key --clearmodifiers Return
    sleep 3
}

krita_export_as() {
    # Uses File > Export As (different from Save As for non-native formats)
    local filepath="$1"
    focus_krita
    sleep 0.5
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+shift+e 2>/dev/null || \
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+shift+s 2>/dev/null
    sleep 2
    DISPLAY=:1 xdotool key --clearmodifiers ctrl+a
    sleep 0.3
    DISPLAY=:1 xdotool type --clearmodifiers "$filepath"
    sleep 0.5
    DISPLAY=:1 xdotool key --clearmodifiers Return
    sleep 3
}

# ── Image info helpers ──

get_image_dimensions() {
    local filepath="$1"
    identify -format '%w %h' "$filepath" 2>/dev/null
}

get_image_format() {
    local filepath="$1"
    identify -format '%m' "$filepath" 2>/dev/null
}

get_image_colorspace() {
    local filepath="$1"
    identify -format '%[colorspace]' "$filepath" 2>/dev/null
}

# Export all functions
export -f take_screenshot
export -f get_krita_window_id
export -f is_krita_running
export -f ensure_krita_running
export -f focus_krita
export -f maximize_krita
export -f kill_krita
export -f restart_krita
export -f krita_open_file
export -f krita_save_as
export -f krita_export_as
export -f get_image_dimensions
export -f get_image_format
export -f get_image_colorspace
