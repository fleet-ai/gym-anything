#!/usr/bin/env python3
"""Comprehensive environment validator for gym-anything.

Uses from_config() (direct Docker) — same code path as the eval harness.
Previous version used HTTP API which had screenshot inline issues.

Usage:
    # Test all envs
    python scripts/validate_envs.py --env-dir benchmarks/cua_world/environments

    # Test specific envs
    python scripts/validate_envs.py --env-dir benchmarks/cua_world/environments --envs stellarium_env qgis_env

    # With custom concurrency
    python scripts/validate_envs.py --env-dir benchmarks/cua_world/environments --concurrency 4

    # Save validated env list
    python scripts/validate_envs.py --env-dir benchmarks/cua_world/environments --output validated_envs.txt
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MIN_SCREENSHOT_BYTES = 15000  # Blank blue desktop ~11KB, real desktop >15KB


def validate_env(env_dir: str, env_name: str, task_id: str, timeout: int = 600) -> dict:
    """Validate a single env using from_config() — same path as eval."""
    result = {
        "env_name": env_name,
        "task_id": task_id,
        "passed": False,
        "screenshot_bytes": 0,
        "error": None,
        "elapsed_s": 0,
    }
    start = time.time()

    try:
        proc = subprocess.run(
            ["python", "-c", f"""
import os, sys
from gym_anything.api import from_config

env = from_config('{env_dir}', task_id='{task_id}')
try:
    # Set the image to the GCR-pulled tag if it exists, bypassing Dockerfile build
    import subprocess as _sp
    _local_tag = 'ga/{env_name}:0.1'
    _check = _sp.run(['docker', 'image', 'inspect', _local_tag], capture_output=True)
    if _check.returncode == 0:
        env._runner.spec.image = _local_tag
    try:
        env.reset(use_cache=True, cache_level='pre_start')
    except Exception as _e:
        print(f'WARN:reset error (continuing): {{_e}}', file=sys.stderr)
    # Always try to capture screenshot — app may work despite hook errors
    obs = env.capture_observation()
    screen = obs.get('screen', {{}})
    path = screen.get('path')
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        print(f'OK:{{size}}')
    else:
        png_b64 = screen.get('png_b64', '')
        import base64
        size = len(base64.b64decode(png_b64)) if png_b64 else 0
        print(f'OK:{{size}}')
except Exception as e:
    print(f'FAIL:{{e}}')
finally:
    env.close()
"""],
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        elapsed = time.time() - start
        result["elapsed_s"] = round(elapsed, 1)

        output = proc.stdout.strip().split("\n")[-1] if proc.stdout.strip() else ""

        if output.startswith("OK:"):
            size = int(output.split(":")[1])
            result["screenshot_bytes"] = size
            if size > MIN_SCREENSHOT_BYTES:
                result["passed"] = True
            else:
                result["error"] = f"screenshot too small ({size} bytes)"
        elif output.startswith("FAIL:"):
            result["error"] = output[5:][:200]
        else:
            stderr_tail = proc.stderr.strip().split("\n")[-1][:200] if proc.stderr else "no output"
            result["error"] = f"unexpected output: {stderr_tail}"

    except subprocess.TimeoutExpired:
        result["error"] = f"timeout after {timeout}s"
        result["elapsed_s"] = timeout
        # Kill orphaned container
        subprocess.run(f"docker ps --filter name=ga_{env_name} -q | xargs -r docker kill",
                       shell=True, capture_output=True, timeout=30)
    except Exception as e:
        result["error"] = str(e)[:200]
        result["elapsed_s"] = round(time.time() - start, 1)

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate all gym-anything environments")
    parser.add_argument("--env-dir", required=True, help="Path to environments directory")
    parser.add_argument("--envs", nargs="+", help="Specific env names to test")
    parser.add_argument("--concurrency", type=int, default=4, help="Parallel validations")
    parser.add_argument("--timeout", type=int, default=600, help="Per-env timeout (seconds)")
    parser.add_argument("--output", "-o", help="Write validated env names to file")
    parser.add_argument("--json-output", help="Write full results as JSON")
    args = parser.parse_args()

    env_dir = Path(args.env_dir)

    if args.envs:
        env_names = args.envs
    else:
        env_names = sorted(d.name for d in env_dir.iterdir()
                          if d.is_dir() and d.name.endswith("_env") and (d / "env.json").exists())

    # Find first task_id for each env
    env_tasks = []
    for name in env_names:
        tasks_dir = env_dir / name / "tasks"
        if not tasks_dir.is_dir():
            continue
        tasks = sorted(d.name for d in tasks_dir.iterdir() if d.is_dir())
        if tasks:
            env_tasks.append((name, tasks[0]))
        else:
            print(f"  SKIP {name}: no tasks")

    print(f"Validating {len(env_tasks)} environments (concurrency={args.concurrency})...\n")

    results = []
    passed = 0
    failed = 0

    import concurrent.futures
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
            print(f"  [{status}] {r['env_name']} ({r['elapsed_s']}s) — {detail}")
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
        print(f"Full results written to {args.json_output}")

    if failed > 0:
        print(f"\nFailed envs:")
        for r in sorted(results, key=lambda x: x["env_name"]):
            if not r["passed"]:
                print(f"  {r['env_name']}: {r['error']}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
