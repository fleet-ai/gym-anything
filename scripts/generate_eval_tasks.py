#!/usr/bin/env python3
"""Generate eval task list (4 tasks per validated env).

Usage:
    python scripts/generate_eval_tasks.py --validated-envs ~/validated_envs.txt -o ~/eval_tasks.json
    python scripts/generate_eval_tasks.py --env-dir benchmarks/cua_world/environments -o ~/eval_tasks.json
"""
import argparse, json, os, random

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validated-envs", help="File with env names, one per line")
    parser.add_argument("--env-dir", default="benchmarks/cua_world/environments")
    parser.add_argument("--tasks-per-env", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("-o", "--output", default=os.path.expanduser("~/eval_tasks.json"))
    args = parser.parse_args()

    random.seed(args.seed)

    if args.validated_envs:
        env_names = open(args.validated_envs).read().strip().split("\n")
    else:
        env_names = sorted(d for d in os.listdir(args.env_dir)
                          if os.path.isdir(os.path.join(args.env_dir, d)) and d.endswith("_env"))

    tasks = []
    for env_name in sorted(env_names):
        tasks_dir = os.path.join(args.env_dir, env_name, "tasks")
        if not os.path.isdir(tasks_dir):
            continue
        env_tasks = []
        for task_name in sorted(os.listdir(tasks_dir)):
            td = os.path.join(tasks_dir, task_name)
            if not os.path.isdir(td):
                continue
            env_tasks.append({
                "env_name": env_name,
                "task_id": task_name,
                "env_dir": os.path.abspath(os.path.join(args.env_dir, env_name)),
                "task_key": f"{env_name}/{task_name}",
            })
        random.shuffle(env_tasks)
        tasks.extend(env_tasks[:args.tasks_per_env])

    json.dump(tasks, open(args.output, "w"), indent=2)
    print(f"{len(tasks)} eval tasks from {len(env_names)} envs → {args.output}")

if __name__ == "__main__":
    main()
