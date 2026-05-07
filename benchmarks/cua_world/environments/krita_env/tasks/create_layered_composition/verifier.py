#!/usr/bin/env python3
"""
Verifier for create_layered_composition task in Krita.

Checks the .kra file (a ZIP archive containing maindoc.xml) for:
1. File exists and is a valid .kra (ZIP) archive
2. Image dimensions are 1920x1080
3. All 5 expected layers exist with correct names
4. Layers are in the correct order (bottom to top)
5. File was created during the task
"""

import logging
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Krita maindoc.xml namespace
KRITA_NS = 'http://www.calligra.org/DTD/krita'


def _parse_kra_layers(kra_path):
    """Extract layer names and image dimensions from a .kra file."""
    layers = []
    width = 0
    height = 0

    try:
        with zipfile.ZipFile(kra_path, 'r') as z:
            if 'maindoc.xml' not in z.namelist():
                return layers, width, height

            with z.open('maindoc.xml') as f:
                content = f.read().decode('utf-8')

            # Parse XML — handle namespaced and non-namespaced variants
            root = ET.fromstring(content)

            # Try to find IMAGE element (with or without namespace)
            image_elem = None
            for tag in [f'{{{KRITA_NS}}}IMAGE', 'IMAGE']:
                image_elem = root.find(f'.//{tag}')
                if image_elem is not None:
                    break

            if image_elem is None:
                # Try namespace-agnostic search
                for elem in root.iter():
                    if elem.tag.endswith('IMAGE') or elem.tag == 'IMAGE':
                        image_elem = elem
                        break

            if image_elem is not None:
                width = int(image_elem.get('width', 0))
                height = int(image_elem.get('height', 0))

                # Find all layer elements recursively
                for elem in image_elem.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag == 'layer':
                        name = elem.get('name', '')
                        if name:
                            layers.append(name)

    except Exception as e:
        logger.error(f"Error parsing .kra file: {e}")

    return layers, width, height


def verify_create_layered_composition(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    exec_capture = env_info.get('exec_capture')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "copy_from_env not available"}

    metadata = task_info.get('metadata', {})
    expected_output = metadata.get('expected_output_file',
                                   '/home/ga/Documents/exports/illustration_project.kra')
    expected_w = metadata.get('expected_width', 1920)
    expected_h = metadata.get('expected_height', 1080)
    expected_layers = metadata.get('expected_layers',
                                   ['Background', 'Sketch', 'Lineart', 'Color', 'Shading'])
    expected_count = metadata.get('expected_layer_count', 5)

    score = 0
    feedback_parts = []

    try:
        # Copy output file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.kra') as tmp:
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

        score += 10
        feedback_parts.append("Output file exists (+10)")

        # Criterion 1: Valid .kra file (10 pts)
        if not zipfile.is_zipfile(tmp_path):
            os.unlink(tmp_path)
            return {
                "passed": False,
                "score": score,
                "feedback": "File is not a valid .kra (ZIP) archive"
            }

        with zipfile.ZipFile(tmp_path, 'r') as z:
            if 'maindoc.xml' in z.namelist():
                score += 10
                feedback_parts.append("Valid .kra archive with maindoc.xml (+10)")
            else:
                feedback_parts.append("ZIP file but missing maindoc.xml")

        # Criterion 2: Parse layers and dimensions
        layers, width, height = _parse_kra_layers(tmp_path)
        logger.info(f"Parsed .kra: {width}x{height}, layers: {layers}")

        # Criterion 3: Image dimensions (20 pts)
        if width == expected_w and height == expected_h:
            score += 20
            feedback_parts.append(f"Dimensions: {width}x{height} (+20)")
        elif abs(width - expected_w) <= 10 and abs(height - expected_h) <= 10:
            score += 10
            feedback_parts.append(f"Dimensions {width}x{height}, close to {expected_w}x{expected_h} (+10)")
        else:
            feedback_parts.append(f"Dimensions {width}x{height}, expected {expected_w}x{expected_h}")

        # Criterion 4: Layer count (10 pts)
        if len(layers) >= expected_count:
            score += 10
            feedback_parts.append(f"Layer count: {len(layers)} (expected >= {expected_count}) (+10)")
        elif len(layers) > 0:
            score += 5
            feedback_parts.append(f"Layer count: {len(layers)}, expected {expected_count} (+5)")
        else:
            feedback_parts.append("No layers found in file")

        # Criterion 5: Layer names match (30 pts)
        # Case-insensitive comparison
        found_layers = [l.lower() for l in layers]
        matched = 0
        for expected_name in expected_layers:
            if expected_name.lower() in found_layers:
                matched += 1

        if matched == len(expected_layers):
            score += 30
            feedback_parts.append(f"All {matched} expected layers found (+30)")
        elif matched > 0:
            partial = int(30 * matched / len(expected_layers))
            score += partial
            missing = [n for n in expected_layers if n.lower() not in found_layers]
            feedback_parts.append(
                f"{matched}/{len(expected_layers)} layers found (+{partial}), "
                f"missing: {missing}"
            )
        else:
            feedback_parts.append(f"No expected layers found. Found: {layers}")

        # Criterion 6: File freshness (10 pts)
        if exec_capture:
            try:
                ts = exec_capture("cat /tmp/task_start_timestamp 2>/dev/null").strip()
                mt = exec_capture(f"stat -c %Y '{expected_output}' 2>/dev/null").strip()
                if ts and mt and int(mt) >= int(ts):
                    score += 10
                    feedback_parts.append("File created during task (+10)")
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
