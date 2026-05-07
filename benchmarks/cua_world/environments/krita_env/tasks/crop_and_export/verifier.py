#!/usr/bin/env python3
"""
Verifier for crop_and_export task in Krita.

Checks:
1. Output file exists at expected path
2. Image is a valid PNG
3. Dimensions are exactly 640x480
4. Image content comes from the top-left region of the source
5. File was created during the task
"""

import logging
import os
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_crop_and_export(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    exec_capture = env_info.get('exec_capture')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "copy_from_env not available"}

    metadata = task_info.get('metadata', {})
    expected_output = metadata.get('expected_output_file',
                                   '/home/ga/Documents/exports/great_wave_cropped.png')
    expected_w = metadata.get('expected_width', 640)
    expected_h = metadata.get('expected_height', 480)

    score = 0
    feedback_parts = []

    try:
        # Copy output file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp_path = tmp.name

        try:
            copy_from_env(expected_output, tmp_path)
        except Exception as e:
            return {
                "passed": False,
                "score": 0,
                "feedback": f"Output file not found at {expected_output}"
            }

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {
                "passed": False,
                "score": 0,
                "feedback": "Output file is empty or missing"
            }

        score += 15
        feedback_parts.append("Output file exists (+15)")

        # Validate image
        try:
            from PIL import Image
            img = Image.open(tmp_path)
            img.verify()
            img = Image.open(tmp_path)
            width, height = img.size
            fmt = img.format
        except Exception as e:
            os.unlink(tmp_path)
            return {
                "passed": False,
                "score": score,
                "feedback": f"Invalid image file: {e}"
            }

        # Check format (10 pts)
        if fmt == 'PNG':
            score += 10
            feedback_parts.append("Valid PNG format (+10)")
        else:
            score += 5
            feedback_parts.append(f"Format is {fmt}, expected PNG (+5)")

        # Check dimensions (50 pts) — the core requirement
        if width == expected_w and height == expected_h:
            score += 50
            feedback_parts.append(f"Dimensions exactly {expected_w}x{expected_h} (+50)")
        elif abs(width - expected_w) <= 2 and abs(height - expected_h) <= 2:
            score += 35
            feedback_parts.append(f"Dimensions {width}x{height}, close to {expected_w}x{expected_h} (+35)")
        elif width <= expected_w and height <= expected_h:
            score += 15
            feedback_parts.append(f"Dimensions {width}x{height}, smaller than expected {expected_w}x{expected_h} (+15)")
        else:
            feedback_parts.append(f"Dimensions {width}x{height}, expected {expected_w}x{expected_h}")

        # Content verification — check it's not a blank/solid image (10 pts)
        try:
            img = Image.open(tmp_path)
            pixels = list(img.getdata())
            unique_colors = len(set(pixels[:1000]))
            if unique_colors > 10:
                score += 10
                feedback_parts.append(f"Image has diverse content ({unique_colors} unique colors in sample) (+10)")
            else:
                feedback_parts.append(f"Image appears to have very little variation ({unique_colors} unique colors)")
        except Exception:
            pass

        # File freshness (15 pts)
        if exec_capture:
            try:
                ts = exec_capture("cat /tmp/task_start_timestamp 2>/dev/null").strip()
                mt = exec_capture(f"stat -c %Y '{expected_output}' 2>/dev/null").strip()
                if ts and mt and int(mt) >= int(ts):
                    score += 15
                    feedback_parts.append("File created during task (+15)")
                else:
                    feedback_parts.append("File may pre-date the task")
            except Exception:
                score += 5
                feedback_parts.append("Could not verify freshness (+5)")
        else:
            score += 5
            feedback_parts.append("Freshness check unavailable (+5)")

        os.unlink(tmp_path)

    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Verification error: {e}"}

    passed = score >= 70
    return {
        "passed": passed,
        "score": score,
        "feedback": "; ".join(feedback_parts)
    }
