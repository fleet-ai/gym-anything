#!/usr/bin/env python3
"""Pre-warm all validated envs by running reset() once per env.

Creates checkpoint images (ga-checkpoint/<env>:0.1-post_start) so subsequent
resets skip the full boot. One-time cost per server launch.

Usage:
    python scripts/prewarm_envs.py --validated-envs ~/validated_envs.txt --env-dir benchmarks/cua_world/environments --concurrency 4
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def prewarm_env(env_dir: str, env_name: str, task_id: str, timeout: int = 1800) -> dict:
    """Reset one env to create its checkpoint."""
    start = time.time()
    try:
        proc = subprocess.run(
            ["python", "-c", f"""
import subprocess as _sp
from gym_anything.api import from_config

# Use GCR image if available
_local_tag = 'ga/{env_name}:0.1'
_check = _sp.run(['docker', 'image', 'inspect', _local_tag], capture_output=True)

env = from_config('{env_dir}', task_id='{task_id}')
if _check.returncode == 0:
    env._runner.spec.image = _local_tag
try:
    env.reset(use_cache=True, cache_level='post_start')
    print('PREWARM:OK')
except Exception as e:
    print(f'PREWARM:FAIL:{{e}}')
finally:
    env.close()
"""],
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        elapsed = time.time() - start

        for line in proc.stdout.strip().split("\n"):
            if line.startswith("PREWARM:OK"):
                return {"env_name": env_name, "status": "ok", "elapsed": round(elapsed, 1)}
            elif line.startswith("PREWARM:FAIL:"):
                return {"env_name": env_name, "status": "fail", "error": line[13:200], "elapsed": round(elapsed, 1)}

        return {"env_name": env_name, "status": "fail", "error": "no marker in output", "elapsed": round(elapsed, 1)}

    except subprocess.TimeoutExpired:
        subprocess.run(f"docker ps --filter name=ga_{env_name} -q | xargs -r docker kill",
                       shell=True, capture_output=True, timeout=30)
        return {"env_name": env_name, "status": "timeout", "elapsed": timeout}
    except Exception as e:
        return {"env_name": env_name, "status": "fail", "error": str(e)[:200], "elapsed": round(time.time() - start, 1)}


def main():
    parser = argparse.ArgumentParser(description="Pre-warm envs by creating checkpoints")
    parser.add_argument("--validated-envs", required=True, help="File with env names")
    parser.add_argument("--env-dir", default="benchmarks/cua_world/environments")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    env_names = open(args.validated_envs).read().strip().split("\n")
    env_dir = Path(args.env_dir)

    # Find first task_id per env and check if checkpoint already exists
    to_warm = []
    already_cached = 0
    for name in sorted(env_names):
        tasks_dir = env_dir / name / "tasks"
        if not tasks_dir.is_dir():
            continue
        tasks = sorted(d.name for d in tasks_dir.iterdir() if d.is_dir())
        if not tasks:
            continue

        # Check if checkpoint exists
        import subprocess
        check = subprocess.run(
            ["docker", "image", "inspect", f"ga-checkpoint/{name}:0.1-post_start"],
            capture_output=True)
        if check.returncode == 0:
            already_cached += 1
            continue

        to_warm.append((name, tasks[0]))

    print(f"Envs: {len(env_names)}, already cached: {already_cached}, need warming: {len(to_warm)}", flush=True)

    if not to_warm:
        print("All envs already have checkpoints.", flush=True)
        return

    ok = 0
    fail = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for name, task_id in to_warm:
            ed = str(env_dir / name)
            futures[pool.submit(prewarm_env, ed, name, task_id, args.timeout)] = name

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            status = result["status"]
            elapsed = result.get("elapsed", 0)
            if status == "ok":
                ok += 1
                print(f"  [OK] {result['env_name']} ({elapsed}s)", flush=True)
            else:
                fail += 1
                err = result.get("error", status)
                print(f"  [FAIL] {result['env_name']} ({elapsed}s) — {err[:80]}", flush=True)

    print(f"\nPre-warm complete: {ok} ok, {fail} failed, {already_cached} already cached", flush=True)


if __name__ == "__main__":
    main()
