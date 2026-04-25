#!/usr/bin/env python3
"""Run paper's eval harness in parallel across tasks.

Uses agents/evaluation/run_single.py with the paper's exact agent harness.
Parses episode_dir from stdout to find verifier results.

Usage:
    # Generate eval tasks (4 per validated env)
    python scripts/generate_eval_tasks.py --validated-envs ~/validated_envs.txt -o ~/eval_tasks.json

    # Run eval
    OPENROUTER_API_KEY=... python scripts/run_eval_parallel.py ~/eval_tasks.json 200 8 3600 [run_id]
    # run_id defaults to timestamp. Trajectories saved to all_runs/fleet-eval-{run_id}/
    # Results saved to ~/eval_results/{run_id}/
"""
import json, subprocess, sys, os, time, re, concurrent.futures
from pathlib import Path

TASKS_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/eval_tasks.json")
MAX_STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
CONCURRENCY = int(sys.argv[3]) if len(sys.argv) > 3 else 8
TASK_TIMEOUT = int(sys.argv[4]) if len(sys.argv) > 4 else 3600
RUN_ID = sys.argv[5] if len(sys.argv) > 5 else time.strftime("%Y%m%d_%H%M%S")
RESULTS_DIR = Path(os.path.expanduser(f"~/eval_results/{RUN_ID}"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

tasks = json.load(open(TASKS_FILE))
print(f"=== Parallel eval: {len(tasks)} tasks, max_steps={MAX_STEPS}, concurrency={CONCURRENCY}, timeout={TASK_TIMEOUT}s, run_id={RUN_ID} ===", flush=True)

def run_task(task):
    env_name = task["env_name"]
    task_id = task["task_id"]
    env_dir = task["env_dir"]
    task_key = f"{env_name}/{task_id}"
    result_file = RESULTS_DIR / f"{env_name}__{task_id}.json"

    if result_file.exists():
        return json.load(open(result_file))

    start = time.time()
    try:
        proc = subprocess.run(
            ["python", "-m", "agents.evaluation.run_single",
             "--env_dir", env_dir, "--task", task_id,
             "--agent", "Gemini3Agent",
             "--agent_args", json.dumps({
                 "model": "openrouter/google/gemini-3-flash-preview",
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
                result = {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                          "score": v.get("score", 0), "passed": v.get("passed", False),
                          "steps": summary.get("steps", 0), "elapsed": elapsed,
                          "episode_dir": episode_dir}
            else:
                result = {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                          "score": 0, "passed": False, "error": "no summary.json", "elapsed": elapsed}
        else:
            err_lines = [l for l in output.split("\n") if "Error" in l or "error" in l]
            err_msg = err_lines[-1][:150] if err_lines else "no episode dir in output"
            result = {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                      "score": 0, "passed": False, "error": err_msg, "elapsed": elapsed}

    except subprocess.TimeoutExpired:
        result = {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                  "score": 0, "passed": False, "error": "timeout", "elapsed": time.time() - start}
        # Kill orphaned Docker container (subprocess timeout doesn't call env.close())
        subprocess.run(f"docker ps --filter name=ga_{env_name} -q | xargs -r docker kill",
                       shell=True, capture_output=True, timeout=30)
    except Exception as e:
        result = {"task_key": task_key, "env_name": env_name, "task_id": task_id,
                  "score": 0, "passed": False, "error": str(e)[:200], "elapsed": time.time() - start}

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
        if completed % 20 == 0:
            print(f"  --- {completed}/{len(tasks)}, scored>0: {scored}, errors: {errors} ---", flush=True)

all_r = [json.load(open(f)) for f in RESULTS_DIR.glob("*.json") if f.name != "all_results.json"]
s = [r for r in all_r if r.get("score", 0) > 0]
p = [r for r in all_r if r.get("passed")]
avg = sum(r.get("score", 0) for r in all_r) / len(all_r) if all_r else 0
print(f"\n=== FINAL: {len(all_r)} tasks, score>0: {len(s)} ({100*len(s)/len(all_r):.1f}%), full pass: {len(p)}, avg: {avg:.1f}/100 ===", flush=True)
json.dump(all_r, open(RESULTS_DIR / "all_results.json", "w"), indent=2)

# Upload results and trajectories to S3
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
