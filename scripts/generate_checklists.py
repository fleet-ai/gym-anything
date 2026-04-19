#!/usr/bin/env python3
"""Generate missing vlm_checklist.json files for gym-anything tasks.

Uses the paper's checklist generation prompt (Appendix C.3, Listing 5)
with Gemini Pro via OpenRouter to generate structured checklists.

Usage:
    OPENROUTER_API_KEY=... python scripts/generate_checklists.py \
        --env-dir benchmarks/cua_world/environments \
        --concurrency 10 --dry-run

    # Only for validated envs
    OPENROUTER_API_KEY=... python scripts/generate_checklists.py \
        --env-dir benchmarks/cua_world/environments \
        --envs-file ~/validated_envs.txt \
        --concurrency 10
"""

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

import requests

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = "google/gemini-2.5-flash-preview"  # cheapest capable model for generation
API_URL = "https://openrouter.ai/api/v1/chat/completions"

CHECKLIST_PROMPT = """You are generating a verification checklist for an AI agent benchmark task. This checklist will be used by a VLM (vision-language model) to score agent trajectories by examining screenshots.

Task ID: {task_id}
Task Description: {task_desc}
Privileged Information: {pi_text}

Generate a checklist with two sections:

1. **task_completion** (5-8 items, points must sum to exactly 100):
   Each item represents a sub-goal or evidence of progress. Items should be ordered from earliest to latest.
   - CRITICAL: ONLY include items that are explicitly required by the task description. Do NOT add extra steps.
   - Assign more points to harder items
   - Each item must be visually verifiable from screenshots
   - Include what visual evidence the VLM should look for

2. **integrity** (3-4 items):
   Each item checks for cheating/shortcuts. Common checks:
   - Agent used the GUI, not terminal commands
   - Agent interacted with the actual application
   - Agent didn't copy-paste expected answers
   - Results come from genuine software interaction

Also produce a "privileged_info_for_vlm" field: a concise text with ONLY verified facts that helps the VLM judge correctness.

Respond with ONLY a JSON object:
{{
    "task_id": "{task_id}",
    "task_completion": [
        {{
            "id": "short_snake_case_id",
            "description": "What this item checks",
            "points": 20,
            "visual_evidence": "What the VLM should look for"
        }}
    ],
    "integrity": [
        {{
            "id": "short_snake_case_id",
            "description": "What this integrity check verifies",
            "visual_evidence": "What the VLM should look for"
        }}
    ],
    "privileged_info_for_vlm": "Verified facts for the VLM"
}}"""


def load_pi(task_dir: Path) -> str:
    pi_path = task_dir / "validated_pi.json"
    if not pi_path.exists():
        return "No privileged information available."
    try:
        data = json.loads(pi_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("summary", json.dumps(data, indent=2)[:2000])
        return str(data)[:2000]
    except Exception:
        return "No privileged information available."


def generate_checklist(task_dir: Path, task_id: str, task_desc: str, pi_text: str) -> dict:
    prompt = CHECKLIST_PROMPT.format(task_id=task_id, task_desc=task_desc, pi_text=pi_text)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.1,
    }

    for attempt in range(3):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            # Parse JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            checklist = json.loads(content.strip())
            # Validate structure
            if "task_completion" not in checklist or "integrity" not in checklist:
                return {"error": "missing required fields"}
            # Validate points sum to 100
            points_sum = sum(item.get("points", 0) for item in checklist["task_completion"])
            if points_sum != 100:
                # Auto-fix: scale to 100
                for item in checklist["task_completion"]:
                    item["points"] = round(item["points"] * 100 / points_sum)
                # Fix rounding
                diff = 100 - sum(item["points"] for item in checklist["task_completion"])
                if diff != 0:
                    checklist["task_completion"][-1]["points"] += diff
            return checklist
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return {"error": str(e)}
    return {"error": "max retries exceeded"}


def process_task(task_dir: Path) -> dict:
    task_json_path = task_dir / "task.json"
    checklist_path = task_dir / "vlm_checklist.json"

    if checklist_path.exists():
        return {"status": "skip", "task": task_dir.name}

    if not task_json_path.exists():
        return {"status": "error", "task": task_dir.name, "error": "no task.json"}

    try:
        task_data = json.loads(task_json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "task": task_dir.name, "error": f"bad task.json: {e}"}

    task_id = task_data.get("id", task_dir.name)
    task_desc = task_data.get("description", "")
    if not task_desc:
        return {"status": "error", "task": task_dir.name, "error": "no description"}

    pi_text = load_pi(task_dir)
    checklist = generate_checklist(task_dir, task_id, task_desc, pi_text)

    if "error" in checklist:
        return {"status": "error", "task": task_dir.name, "error": checklist["error"]}

    checklist_path.write_text(json.dumps(checklist, indent=4, ensure_ascii=False), encoding="utf-8")
    return {"status": "generated", "task": task_dir.name}


def main():
    parser = argparse.ArgumentParser(description="Generate missing VLM checklists")
    parser.add_argument("--env-dir", required=True, help="Path to environments directory")
    parser.add_argument("--envs-file", help="File with env names (one per line)")
    parser.add_argument("--envs", nargs="+", help="Specific env names")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="Count missing only")
    args = parser.parse_args()

    if not OPENROUTER_API_KEY and not args.dry_run:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    env_dir = Path(args.env_dir)
    if args.envs_file:
        env_names = Path(args.envs_file).read_text().strip().split("\n")
    elif args.envs:
        env_names = args.envs
    else:
        env_names = [d.name for d in env_dir.iterdir() if d.is_dir() and d.name.endswith("_env")]

    # Collect tasks missing checklists
    tasks_to_process = []
    skipped = 0
    for env_name in sorted(env_names):
        tasks_dir = env_dir / env_name / "tasks"
        if not tasks_dir.is_dir():
            continue
        for task in sorted(tasks_dir.iterdir()):
            if not task.is_dir():
                continue
            if (task / "vlm_checklist.json").exists():
                skipped += 1
            else:
                tasks_to_process.append(task)

    print(f"Envs: {len(env_names)}")
    print(f"Already have checklist: {skipped}")
    print(f"Missing checklist: {len(tasks_to_process)}")

    if args.dry_run:
        return

    print(f"\nGenerating {len(tasks_to_process)} checklists (concurrency={args.concurrency})...\n")

    generated = 0
    errors = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(process_task, t): t for t in tasks_to_process}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if result["status"] == "generated":
                generated += 1
                if generated % 50 == 0:
                    print(f"  Generated {generated}/{len(tasks_to_process)}...")
            elif result["status"] == "error":
                errors += 1
                if errors <= 10:
                    print(f"  ERROR {result['task']}: {result.get('error', '?')}")

    print(f"\nDone: {generated} generated, {errors} errors, {skipped} already existed")


if __name__ == "__main__":
    main()
