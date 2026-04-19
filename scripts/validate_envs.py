#!/usr/bin/env python3
"""Comprehensive environment validator for gym-anything.

Tests ALL built Docker env images on the server: create → reset → check
screenshot > 15KB → close. Outputs a list of validated envs.

Usage:
    # Test all envs (discovers from Docker images)
    python scripts/validate_envs.py http://<server-ip>:5000

    # Test specific envs
    python scripts/validate_envs.py http://<server-ip>:5000 --envs stellarium_env libreoffice_calc_env

    # With custom concurrency
    python scripts/validate_envs.py http://<server-ip>:5000 --concurrency 10

    # Save validated env list
    python scripts/validate_envs.py http://<server-ip>:5000 --output validated_envs.txt
"""

import argparse
import base64
import concurrent.futures
import json
import subprocess
import sys
import time

import requests

MIN_SCREENSHOT_BYTES = 15000  # Blank blue desktop ~11KB, real desktop >15KB


def discover_envs_from_docker() -> list[str]:
    """Discover available env images from local Docker."""
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True, text=True, timeout=30,
        )
        envs = []
        for line in result.stdout.strip().split("\n"):
            # Match ga/<env_name>:0.1 or gcr.io/.../gym-anything/<env_name>:0.1
            repo = line.split(":")[0]
            if repo.startswith("ga/"):
                envs.append(repo[3:])
            elif "gym-anything/" in repo:
                envs.append(repo.split("gym-anything/")[-1])
        return sorted(set(envs))
    except Exception as e:
        print(f"Warning: could not discover envs from Docker: {e}")
        return []


def discover_envs_from_filesystem(prefix: str) -> list[str]:
    """Discover available envs from the filesystem (run on server)."""
    try:
        result = subprocess.run(
            ["ls", prefix], capture_output=True, text=True, timeout=10,
        )
        return sorted([
            d for d in result.stdout.strip().split("\n")
            if d.endswith("_env") and d.strip()
        ])
    except Exception:
        return []


def find_task_id(prefix: str, env_name: str) -> str | None:
    """Find the first available task_id for an env."""
    tasks_dir = f"{prefix}/{env_name}/tasks"
    try:
        result = subprocess.run(
            ["ls", tasks_dir], capture_output=True, text=True, timeout=10,
        )
        tasks = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]
        return tasks[0] if tasks else None
    except Exception:
        return None


def validate_env(
    server_url: str,
    env_dir: str,
    task_id: str,
    env_name: str,
    timeout: int = 600,
) -> dict:
    """Validate a single environment. Returns result dict."""
    result = {
        "env_name": env_name,
        "task_id": task_id,
        "passed": False,
        "screenshot_bytes": 0,
        "error": None,
        "elapsed_s": 0,
    }
    env_id = None
    start = time.time()

    try:
        # Create
        r = requests.post(
            f"{server_url}/envs/create",
            json={"env_dir": env_dir, "task_id": task_id},
            timeout=60,
        )
        r.raise_for_status()
        env_id = r.json().get("env_id")
        if not env_id:
            result["error"] = f"no env_id: {r.json()}"
            return result

        # Reset
        r = requests.post(
            f"{server_url}/envs/{env_id}/reset",
            json={"use_cache": True, "cache_level": "post_start"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()

        if data.get("error"):
            result["error"] = data["error"][:200]
            return result

        # Check screenshot
        obs = data.get("observation") or {}
        screen = obs.get("screen") or {}
        png_b64 = screen.get("png_b64", "")
        if not png_b64:
            result["error"] = "no screenshot in response"
            return result

        png_bytes = base64.b64decode(png_b64)
        result["screenshot_bytes"] = len(png_bytes)

        if len(png_bytes) < MIN_SCREENSHOT_BYTES:
            result["error"] = f"screenshot too small ({len(png_bytes)} bytes)"
            return result

        result["passed"] = True

    except requests.exceptions.Timeout:
        result["error"] = f"timeout after {timeout}s"
    except Exception as e:
        result["error"] = str(e)[:200]
    finally:
        result["elapsed_s"] = round(time.time() - start, 1)
        if env_id:
            try:
                requests.post(f"{server_url}/envs/{env_id}/close", timeout=30)
            except Exception:
                pass

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate all gym-anything environments")
    parser.add_argument("server_url", help="e.g. http://10.0.0.1:5000")
    parser.add_argument("--envs", nargs="+", help="Specific env names to test (default: all)")
    parser.add_argument(
        "--env-dir-prefix",
        default="/home/gcpuser/gym-anything/benchmarks/cua_world/environments",
        help="Env directory prefix on the server",
    )
    parser.add_argument("--concurrency", type=int, default=8, help="Parallel validations")
    parser.add_argument("--timeout", type=int, default=600, help="Per-env timeout (seconds)")
    parser.add_argument("--output", "-o", help="Write validated env names to file")
    parser.add_argument("--json-output", help="Write full results as JSON")
    args = parser.parse_args()

    server_url = args.server_url.rstrip("/")

    # Health check
    print(f"Server: {server_url}")
    try:
        r = requests.get(f"{server_url}/health", timeout=10)
        health = r.json()
        print(f"Workers: {health.get('healthy_workers', '?')}, Capacity: {health.get('total_capacity', '?')}")
    except Exception as e:
        print(f"FAIL: health check failed: {e}")
        sys.exit(1)

    # Discover envs
    if args.envs:
        env_names = args.envs
    else:
        print("Discovering envs from filesystem...")
        env_names = discover_envs_from_filesystem(args.env_dir_prefix)
        if not env_names:
            print("Discovering envs from Docker images...")
            env_names = discover_envs_from_docker()
        if not env_names:
            print("FAIL: no envs found. Use --envs to specify manually.")
            sys.exit(1)

    # Find task_ids
    env_tasks = []
    for name in env_names:
        task_id = find_task_id(args.env_dir_prefix, name)
        if task_id:
            env_tasks.append((name, task_id))
        else:
            print(f"  SKIP {name}: no tasks found")

    print(f"\nValidating {len(env_tasks)} environments (concurrency={args.concurrency})...\n")

    # Run validations
    results = []
    passed = 0
    failed = 0

    def run_one(item):
        name, task_id = item
        env_dir = f"{args.env_dir_prefix}/{name}"
        return validate_env(server_url, env_dir, task_id, name, args.timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, item): item for item in env_tasks}
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

    # Summary
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(results)} tested")
    print(f"Pass rate: {passed/len(results)*100:.1f}%" if results else "No envs tested")

    # Write outputs
    validated = sorted([r["env_name"] for r in results if r["passed"]])

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
