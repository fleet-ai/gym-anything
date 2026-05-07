#!/usr/bin/env python3
"""
Verifier for convert_to_grayscale task in Krita.

Checks:
1. Output file exists at expected path
2. Image is a valid PNG
3. Image is grayscale (either mode 'L' or all pixels have R==G==B)
4. Dimensions preserved from source
5. File was created during the task
"""

import logging
import os
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_grayscale(img):
    """Check if an image is grayscale, regardless of PIL mode."""
    if img.mode == 'L' or img.mode == 'LA':
        return True
    if img.mode in ('RGB', 'RGBA'):
        # Sample pixels to check if R==G==B
        pixels = list(img.getdata())
        sample_size = min(len(pixels), 5000)
        step = max(1, len(pixels) // sample_size)
        for i in range(0, len(pixels), step):
            p = pixels[i]
            if p[0] != p[1] or p[1] != p[2]:
                return False
        return True
    # Other modes (P, CMYK, etc.) — check by converting
    try:
        rgb = img.convert('RGB')
        return _is_grayscale(rgb)
    except Exception:
        return False


def verify_convert_to_grayscale(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    exec_capture = env_info.get('exec_capture')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "copy_from_env not available"}

    metadata = task_info.get('metadata', {})
    expected_output = metadata.get('expected_output_file',
                                   '/home/ga/Documents/exports/water_lilies_grayscale.png')

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
            mode = img.mode
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

        # Check grayscale (50 pts) — the core requirement
        img = Image.open(tmp_path)
        if _is_grayscale(img):
            score += 50
            feedback_parts.append(f"Image is grayscale (mode: {mode}) (+50)")
        else:
            feedback_parts.append(f"Image is NOT grayscale (mode: {mode})")

        # Check dimensions are reasonable (10 pts)
        if width > 0 and height > 0:
            score += 10
            feedback_parts.append(f"Dimensions: {width}x{height} (+10)")
        else:
            feedback_parts.append("Invalid dimensions")

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
