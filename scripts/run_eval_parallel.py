#!/usr/bin/env python3
"""Run paper's eval harness in parallel across tasks.

Uses agents/evaluation/run_single.py with the paper's exact agent harness.
Retries once on transient failures (KeyError, no summary).

Usage:
    GOOGLE_API_KEY=... python scripts/run_eval_parallel.py ~/eval_tasks.json 200 8 3600 [run_id]
    # run_id defaults to timestamp. Trajectories saved to all_runs/fleet-eval-{run_id}/
    # Results saved to ~/eval_results/{run_id}/
"""
import json, subprocess, sys, os, time, re, concurrent.futures
from pathlib import Path

TASKS_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/eval_tasks.json")
MAX_STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
CONCURRENCY = int(sys.argv[3]) if len(sys.argv) > 3 else 16
TASK_TIMEOUT = int(sys.argv[4]) if len(sys.argv) > 4 else 3600
RUN_ID = sys.argv[5] if len(sys.argv) > 5 else time.strftime("%Y%m%d_%H%M%S")
RESULTS_DIR = Path(os.path.expanduser(f"~/eval_results/{RUN_ID}"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
S3_RESULTS = f"s3://fleet-internal-datasets/gym-anything/eval-runs/{RUN_ID}/results"
MAX_RETRIES = 2  # Try each task up to 2 times

# === Pre-flight checks ===
def _preflight():
    """Verify everything works before starting a multi-hour eval."""
    errors = []

    # 1. AWS CLI available
    try:
        subprocess.run(["aws", "--version"], capture_output=True, timeout=10, check=True)
    except Exception:
        errors.append("aws CLI not installed (pip install awscli)")

    # 2. AWS credentials work
    if not errors:
        try:
            result = subprocess.run(
                ["aws", "s3", "ls", "s3://fleet-internal-datasets/gym-anything/", "--max-items", "1"],
                capture_output=True, timeout=30)
            if result.returncode != 0:
                errors.append(f"AWS credentials failed: {result.stderr.decode()[:100]}")
        except Exception as e:
            errors.append(f"AWS S3 test failed: {e}")

    # 3. Test S3 write
    if not errors:
        test_file = RESULTS_DIR / "_preflight_test.json"
        test_file.write_text('{"test": true}')
        try:
            result = subprocess.run(
                ["aws", "s3", "cp", str(test_file), f"{S3_RESULTS}/_preflight_test.json"],
                capture_output=True, timeout=30)
            if result.returncode != 0:
                errors.append(f"S3 write failed: {result.stderr.decode()[:100]}")
            else:
                subprocess.run(["aws", "s3", "rm", f"{S3_RESULTS}/_preflight_test.json"],
                               capture_output=True, timeout=30)
        except Exception as e:
            errors.append(f"S3 write test failed: {e}")
        finally:
            test_file.unlink(missing_ok=True)

    # 4. Disk space
    import shutil
    total, used, free = shutil.disk_usage("/")
    free_gb = free // (1024**3)
    if free_gb < 50:
        errors.append(f"Disk too low: {free_gb}GB free (need 50GB+)")

    if errors:
        print("❌ PRE-FLIGHT FAILED:", flush=True)
        for e in errors:
            print(f"   - {e}", flush=True)
        sys.exit(1)
    else:
        print(f"✓ Pre-flight passed: aws OK, S3 write OK, disk {free_gb}GB free", flush=True)

_preflight()

# Resume: pull existing results from S3 (in case server was restarted)
print("Checking S3 for existing results...", flush=True)
try:
    subprocess.run(["aws", "s3", "sync", S3_RESULTS, str(RESULTS_DIR), "--quiet"],
                   timeout=300, capture_output=True)
    existing = len([f for f in RESULTS_DIR.glob("*.json") if f.name != "all_results.json"])
    if existing > 0:
        print(f"Resumed: {existing} results pulled from S3", flush=True)
except Exception:
    pass

tasks = json.load(open(TASKS_FILE))
print(f"=== Parallel eval: {len(tasks)} tasks, max_steps={MAX_STEPS}, concurrency={CONCURRENCY}, timeout={TASK_TIMEOUT}s, run_id={RUN_ID} ===", flush=True)


_last_sync_count = 0

def _s3_sync():
    """Sync results to S3. Called by background thread and after every 20 tasks."""
    global _last_sync_count
    try:
        result = subprocess.run(["aws", "s3", "sync", str(RESULTS_DIR), S3_RESULTS, "--quiet"],
                               timeout=120, capture_output=True)
        current = len([f for f in RESULTS_DIR.glob("*.json") if f.name != "all_results.json"])
        if result.returncode != 0:
            print(f"⚠️ S3 sync failed: {result.stderr.decode()[:100]}", flush=True)
        elif current > _last_sync_count:
            print(f"  S3 synced: {current} results", flush=True)
            _last_sync_count = current
    except Exception as e:
        print(f"⚠️ S3 sync error: {e}", flush=True)


def _s3_sync_loop():
    """Background thread: sync results to S3 every 5 minutes."""
    while True:
        time.sleep(300)
        _s3_sync()

import threading
_sync_thread = threading.Thread(target=_s3_sync_loop, daemon=True)
_sync_thread.start()


def _run_once(env_dir, env_name, task_id, task_key):
    """Run a single task attempt. Returns result dict."""
    start = time.time()
    try:
        proc = subprocess.run(
            ["python", "-m", "agents.evaluation.run_single",
             "--env_dir", env_dir, "--task", task_id,
             "--agent", "Gemini3Agent",
             "--agent_args", json.dumps({
                 "model": os.environ.get("EVAL_MODEL", "gemini-3-flash-preview"),
                 "temperature": 1.0,
                 "exp_name": f"fleet-eval-{RUN_ID}",
                 "task_name": task_id,
             }),
             "--steps", str(MAX_STEPS),
             "--use_cache", "--cache_level", "post_start"],
            timeout=TASK_TIMEOUT, capture_output=True, text=True,
        )
        elapsed = time.time() - start
        output = proc.stdout + proc.stderr

        match = re.search(r"Episode finished\. See: (\S+)", output)
        if match:
            episode_dir = match.group(1)
            summary_path = os.path.join(episode_dir, "summary.json")
            if os.path.exists(summary_path):
                summary = json.load(open(summary_path))
                v = summary.get("verifier", {})
                return {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                        "score": v.get("score", 0), "passed": v.get("passed", False),
                        "steps": summary.get("steps", 0), "elapsed": elapsed,
                        "episode_dir": episode_dir}
            else:
                return {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                        "score": 0, "passed": False, "error": "no summary.json",
                        "elapsed": elapsed, "retryable": True}
        else:
            err_lines = [l for l in output.split("\n") if "Error" in l or "error" in l]
            err_msg = err_lines[-1][:150] if err_lines else "no episode dir in output"
            retryable = "KeyError" in err_msg or "path" in err_msg or "no episode" in err_msg
            return {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                    "score": 0, "passed": False, "error": err_msg,
                    "elapsed": elapsed, "retryable": retryable}

    except subprocess.TimeoutExpired:
        try:
            subprocess.run(f"docker ps --filter name=ga_{env_name} -q | xargs -r docker kill",
                           shell=True, capture_output=True, timeout=30)
        except Exception:
            pass  # Don't let cleanup crash the eval
        return {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                "score": 0, "passed": False, "error": "timeout",
                "elapsed": time.time() - start, "retryable": False}
    except Exception as e:
        return {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                "score": 0, "passed": False, "error": str(e)[:200],
                "elapsed": time.time() - start, "retryable": True}


def run_task(task):
    env_name = task["env_name"]
    task_id = task["task_id"]
    env_dir = task["env_dir"]
    task_key = f"{env_name}/{task_id}"
    result_file = RESULTS_DIR / f"{env_name}__{task_id}.json"

    if result_file.exists():
        return json.load(open(result_file))

    for attempt in range(MAX_RETRIES):
        result = _run_once(env_dir, env_name, task_id, task_key)

        # Success or non-retryable failure — done
        if result.get("score", 0) > 0 or not result.get("retryable", False):
            break

        # Retryable failure — try again
        if attempt < MAX_RETRIES - 1:
            result["_retried"] = True

    # Clean up internal fields
    result.pop("retryable", None)
    result.pop("_retried", None)

    json.dump(result, open(result_file, "w"), indent=2)
    return result


completed = 0
scored = 0
errors = 0

with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
    futures = {pool.submit(run_task, t): t for t in tasks}
    for future in concurrent.futures.as_completed(futures):
        result = future.result()
        completed += 1
        if result.get("score", 0) > 0: scored += 1
        if result.get("error"): errors += 1
        s = result.get("score", 0)
        e = result.get("error", "")
        status = f"score={s}" if not e else f"ERR:{e[:40]}"
        print(f"[{completed}/{len(tasks)}] {result['task_key']}: {status} ({result.get('elapsed',0):.0f}s)", flush=True)
        # Sync every task result to S3 immediately — zero data loss on server death
        try:
            result_file = RESULTS_DIR / f"{result['env_name']}__{result['task_id']}.json"
            subprocess.run(["aws", "s3", "cp", str(result_file), f"{S3_RESULTS}/{result_file.name}", "--quiet"],
                           timeout=30, capture_output=True)
        except Exception:
            pass
        if completed % 20 == 0:
            print(f"  --- {completed}/{len(tasks)}, scored>0: {scored}, errors: {errors} ---", flush=True)

all_r = [json.load(open(f)) for f in RESULTS_DIR.glob("*.json") if f.name != "all_results.json"]
s = [r for r in all_r if r.get("score", 0) > 0]
p = [r for r in all_r if r.get("passed")]
avg = sum(r.get("score", 0) for r in all_r) / len(all_r) if all_r else 0
print(f"\n=== FINAL: {len(all_r)} tasks, score>0: {len(s)} ({100*len(s)/len(all_r):.1f}%), full pass: {len(p)}, avg: {avg:.1f}/100 ===", flush=True)
json.dump(all_r, open(RESULTS_DIR / "all_results.json", "w"), indent=2)

# Upload to S3
S3_BUCKET = "s3://fleet-internal-datasets/gym-anything/eval-runs"
s3_dest = f"{S3_BUCKET}/{RUN_ID}"
print(f"\nUploading to {s3_dest}...", flush=True)
try:
    subprocess.run(["aws", "s3", "cp", str(RESULTS_DIR / "all_results.json"), f"{s3_dest}/all_results.json"], check=True, timeout=60)
    subprocess.run(["aws", "s3", "sync", str(RESULTS_DIR), f"{s3_dest}/results/", "--quiet"], check=True, timeout=300)
    runs_dir = Path(f"all_runs/fleet-eval-{RUN_ID}")
    if runs_dir.exists():
        subprocess.run(["aws", "s3", "sync", str(runs_dir), f"{s3_dest}/trajectories/", "--quiet"], check=True, timeout=1800)
    print(f"Uploaded to {s3_dest}", flush=True)
except Exception as e:
    print(f"S3 upload failed: {e}", flush=True)
