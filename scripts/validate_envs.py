#!/usr/bin/env python3
"""Validate gym-anything environments.

Two-step validation per env:
1. Fresh boot → creates checkpoint
2. Load from checkpoint → capture screenshot (this is what eval does)

If step 2 fails, retry once. If it fails twice, the env is rejected.
Only envs that work from checkpoint are validated.

Usage:
    python scripts/validate_envs.py --env-dir benchmarks/cua_world/environments
    python scripts/validate_envs.py --env-dir benchmarks/cua_world/environments --envs stellarium_env qgis_env
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MIN_SCREENSHOT_BYTES = 15000

# Inner script run inside subprocess — tests one reset and returns screenshot size
RESET_AND_CHECK = """
import os, sys, subprocess as _sp, time as _time
from gym_anything.api import from_config

env = from_config('{env_dir}', task_id='{task_id}')
_local_tag = 'ga/{env_name}:0.1'
_check = _sp.run(['docker', 'image', 'inspect', _local_tag], capture_output=True)
if _check.returncode == 0:
    env._runner.spec.image = _local_tag
try:
    env.reset(use_cache=True, cache_level='post_start')
except Exception:
    pass
_time.sleep(5)
try:
    obs = env.capture_observation()
    screen = obs.get('screen', {{}})
    path = screen.get('path')
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        print(f'VALIDATE_RESULT:OK:{{size}}')
    else:
        png_b64 = screen.get('png_b64', '')
        import base64
        size = len(base64.b64decode(png_b64)) if png_b64 else 0
        print(f'VALIDATE_RESULT:OK:{{size}}')
except Exception as e:
    print(f'VALIDATE_RESULT:FAIL:{{e}}')
finally:
    env.close()
"""


def _run_reset(env_dir, env_name, task_id, timeout):
    """Run a single reset subprocess, return (size, error)."""
    proc = subprocess.run(
        ["python", "-c", RESET_AND_CHECK.format(env_dir=env_dir, env_name=env_name, task_id=task_id)],
        timeout=timeout, capture_output=True, text=True,
    )
    for line in proc.stdout.strip().split("\n"):
        if line.startswith("VALIDATE_RESULT:OK:"):
            return int(line.split(":")[2]), None
        elif line.startswith("VALIDATE_RESULT:FAIL:"):
            return 0, line[21:][:200]
    return 0, "no marker in output"


def validate_env(env_dir: str, env_name: str, task_id: str, timeout: int = 7200) -> dict:
    """Validate one env: fresh boot → checkpoint → test checkpoint with retry."""
    result = {"env_name": env_name, "task_id": task_id, "passed": False,
              "screenshot_bytes": 0, "error": None, "elapsed_s": 0}
    start = time.time()

    try:
        # Delete existing checkpoint — clean slate
        subprocess.run(["docker", "rmi", "-f", f"ga-checkpoint/{env_name}:0.1-post_start"],
                       capture_output=True, timeout=30)

        # Step 1: Fresh boot (creates checkpoint)
        _run_reset(env_dir, env_name, task_id, timeout)

        # Verify checkpoint was created
        cp_check = subprocess.run(
            ["docker", "image", "inspect", f"ga-checkpoint/{env_name}:0.1-post_start"],
            capture_output=True)
        if cp_check.returncode != 0:
            result["error"] = "checkpoint not created after fresh boot"
            result["elapsed_s"] = round(time.time() - start, 1)
            return result

        # Step 2: Load from checkpoint (what eval does) — with retry
        for attempt in range(2):
            size, error = _run_reset(env_dir, env_name, task_id, timeout=600)
            if size > MIN_SCREENSHOT_BYTES:
                result["passed"] = True
                result["screenshot_bytes"] = size
                result["elapsed_s"] = round(time.time() - start, 1)
                return result
            if attempt == 0 and (size == 0 or error):
                # Retry once — transient failures happen
                continue

        # Both attempts failed
        result["error"] = error or f"screenshot too small ({size} bytes)"
        result["screenshot_bytes"] = size

    except subprocess.TimeoutExpired:
        result["error"] = f"timeout after {timeout}s"
        subprocess.run(f"docker ps --filter name=ga_{env_name} -q | xargs -r docker kill",
                       shell=True, capture_output=True, timeout=30)
    except Exception as e:
        result["error"] = str(e)[:200]

    result["elapsed_s"] = round(time.time() - start, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description="Validate gym-anything environments")
    parser.add_argument("--env-dir", required=True, help="Path to environments directory")
    parser.add_argument("--envs", nargs="+", help="Specific env names to test")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=7200, help="Timeout for fresh boot (seconds)")
    parser.add_argument("--output", "-o", help="Write validated env names to file")
    parser.add_argument("--json-output", help="Write full results as JSON")
    args = parser.parse_args()

    env_dir = Path(args.env_dir)
    if args.envs:
        env_names = args.envs
    else:
        env_names = sorted(d.name for d in env_dir.iterdir()
                          if d.is_dir() and d.name.endswith("_env") and (d / "env.json").exists())

    env_tasks = []
    for name in env_names:
        tasks_dir = env_dir / name / "tasks"
        if not tasks_dir.is_dir():
            continue
        tasks = sorted(d.name for d in tasks_dir.iterdir() if d.is_dir())
        if tasks:
            env_tasks.append((name, tasks[0]))

    print(f"Validating {len(env_tasks)} environments (concurrency={args.concurrency})...\n", flush=True)

    results = []
    passed = 0
    failed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for name, task_id in env_tasks:
            ed = str(env_dir / name)
            futures[pool.submit(validate_env, ed, name, task_id, args.timeout)] = name

        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            results.append(r)
            status = "PASS" if r["passed"] else "FAIL"
            detail = f"{r['screenshot_bytes']} bytes" if r["passed"] else r["error"]
            print(f"  [{status}] {r['env_name']} ({r['elapsed_s']}s) — {detail}", flush=True)
            if r["passed"]:
                passed += 1
            else:
                failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(results)} tested")
    if results:
        print(f"Pass rate: {100*passed/len(results):.1f}%")

    validated = sorted(r["env_name"] for r in results if r["passed"])

    if args.output:
        with open(args.output, "w") as f:
            for name in validated:
                f.write(f"{name}\n")
        print(f"\nValidated env list written to {args.output}")

    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(results, f, indent=2)

    if failed > 0:
        print(f"\nFailed envs:")
        for r in sorted(results, key=lambda x: x["env_name"]):
            if not r["passed"]:
                print(f"  {r['env_name']}: {r['error']}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
