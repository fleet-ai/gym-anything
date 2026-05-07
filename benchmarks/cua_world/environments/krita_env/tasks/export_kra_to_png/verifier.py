#!/usr/bin/env python3
"""
Verifier for export_kra_to_png task in Krita.

Checks:
1. Output PNG file exists at expected path
2. File is a valid PNG image
3. Image dimensions are non-zero and reasonable
4. File was created during the task (not pre-existing)
"""

import logging
import os
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_export_kra_to_png(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    exec_capture = env_info.get('exec_capture')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "copy_from_env not available"}

    metadata = task_info.get('metadata', {})
    expected_output = metadata.get('expected_output_file', '/home/ga/Documents/exports/starry_night.png')
    source_file = metadata.get('source_file', '/home/ga/Documents/krita/starry_night.kra')

    score = 0
    feedback_parts = []

    try:
        # Criterion 1: Output file exists (30 pts)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp_path = tmp.name

        try:
            copy_from_env(expected_output, tmp_path)
        except Exception as e:
            logger.error(f"Failed to copy output file: {e}")
            return {
                "passed": False,
                "score": 0,
                "feedback": f"Output file not found at {expected_output}"
            }

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {
                "passed": False,
                "score": 0,
                "feedback": f"Output file is empty or missing at {expected_output}"
            }

        score += 30
        feedback_parts.append("File exists at expected path (+30)")

        # Criterion 2: Valid PNG format (30 pts)
        try:
            from PIL import Image
            img = Image.open(tmp_path)
            img.verify()
            # Re-open after verify (verify closes the file)
            img = Image.open(tmp_path)
            width, height = img.size
            fmt = img.format

            if fmt == 'PNG':
                score += 30
                feedback_parts.append(f"Valid PNG format confirmed (+30)")
            else:
                score += 10
                feedback_parts.append(f"Image is valid but format is {fmt}, not PNG (+10)")
        except Exception as e:
            feedback_parts.append(f"Failed to validate image format: {e}")
            os.unlink(tmp_path)
            return {"passed": False, "score": score, "feedback": "; ".join(feedback_parts)}

        # Criterion 3: Reasonable dimensions (20 pts)
        if width > 0 and height > 0:
            score += 20
            feedback_parts.append(f"Image dimensions: {width}x{height} (+20)")
        else:
            feedback_parts.append(f"Invalid dimensions: {width}x{height}")

        # Criterion 4: File freshness — created during task (20 pts)
        if exec_capture:
            try:
                timestamp_str = exec_capture("cat /tmp/task_start_timestamp 2>/dev/null").strip()
                file_mtime = exec_capture(f"stat -c %Y '{expected_output}' 2>/dev/null").strip()
                if timestamp_str and file_mtime:
                    task_start = int(timestamp_str)
                    file_time = int(file_mtime)
                    if file_time >= task_start:
                        score += 20
                        feedback_parts.append("File created during task (+20)")
                    else:
                        feedback_parts.append("File appears to pre-date the task")
                else:
                    score += 10
                    feedback_parts.append("Could not verify file freshness, partial credit (+10)")
            except Exception:
                score += 10
                feedback_parts.append("Could not verify file freshness, partial credit (+10)")
        else:
            score += 10
            feedback_parts.append("exec_capture not available, partial credit (+10)")

        os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Verification error: {e}")
        return {"passed": False, "score": 0, "feedback": f"Verification error: {e}"}

    passed = score >= 70
    return {
        "passed": passed,
        "score": score,
        "feedback": "; ".join(feedback_parts)
    }
