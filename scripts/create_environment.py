#!/usr/bin/env python3
"""
Create a new Gym-Anything environment for a given software application.

Uses Claude Code as the agentic backend — same approach as the CUA-World paper
(Claude Opus via Claude Code with bash + python + computer-use tools).

Usage:
    python scripts/create_environment.py "Stellarium" [--output-dir /path/to/envs]
    python scripts/create_environment.py "Krita" --dry-run  # just generate the prompt

The script:
1. Builds the CREATE prompt (~800 lines) from the template
2. Spawns Claude Code with the prompt
3. Claude Code creates the env directory with env.json, scripts, tasks
4. Validates the output structure
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).parent.parent
ENVS_DIR = REPO_ROOT / "benchmarks" / "cua_world" / "environments"

# Example environments for the agent to study (diverse app types)
EXAMPLE_ENVS = [
    "stellarium_env",       # Desktop GUI (science)
    "dbeaver_env",          # Database IDE (dev tools)
    "libreoffice_calc_env", # Office suite (productivity)
    "firefox_env",          # Browser (web)
]


def build_create_prompt(software_name: str, output_dir: Path) -> str:
    """Build the ~800 line CREATE agent prompt."""

    # Read example env structures for reference
    examples = []
    for env_name in EXAMPLE_ENVS:
        env_dir = ENVS_DIR / env_name
        if not env_dir.exists():
            continue
        env_json = env_dir / "env.json"
        if env_json.exists():
            examples.append({
                "name": env_name,
                "env_json": json.loads(env_json.read_text()),
                "scripts": [f.name for f in (env_dir / "scripts").iterdir()] if (env_dir / "scripts").exists() else [],
                "task_count": len(list((env_dir / "tasks").iterdir())) if (env_dir / "tasks").exists() else 0,
            })

    examples_text = "\n".join(
        f"  - {e['name']}: base={e['env_json'].get('base','?')}, "
        f"scripts={e['scripts']}, tasks={e['task_count']}"
        for e in examples
    )

    # Read one complete example task for reference
    example_task_dir = ENVS_DIR / "dbeaver_env" / "tasks" / "run_sql_query"
    example_task_json = ""
    example_setup_sh = ""
    example_verifier = ""
    if example_task_dir.exists():
        tj = example_task_dir / "task.json"
        if tj.exists():
            example_task_json = tj.read_text()[:2000]
        ss = example_task_dir / "setup_task.sh"
        if ss.exists():
            example_setup_sh = ss.read_text()[:1500]
        vf = example_task_dir / "verifier.py"
        if vf.exists():
            example_verifier = vf.read_text()[:2000]

    prompt = dedent(f"""\
    # Environment Creation for Gym-Anything

    You are creating a new Gym-Anything environment for the software: **{software_name}**

    The output directory is: `{output_dir}`

    ## Your Objective

    Create a complete, working environment that:
    1. Installs and configures {software_name} in a Docker container
    2. Seeds it with REAL data (from public datasets, official samples — NEVER synthetic)
    3. Creates 5 diverse, realistic seed tasks with programmatic verifiers
    4. Tests everything interactively to verify it works

    ## Phase 1: Understand the Framework

    Read these files to understand the Gym-Anything library:
    - `src/gym_anything/env.py` — the GymAnythingEnv class (reset, step, close, capture_observation)
    - `src/gym_anything/specs.py` — EnvSpec and TaskSpec dataclasses
    - `src/gym_anything/config/loading.py` — from_config() and make()

    Key concepts:
    - Each env is a Docker container with a desktop (Ubuntu + GNOME + VNC on :1)
    - The base preset `ubuntu-gnome-systemd_highres` provides the OS + desktop
    - Your env layers the specific app on top via install/setup scripts
    - Hooks: `pre_start` runs install script, `post_start` runs setup script
    - Tasks have `pre_task` hooks that set up task-specific starting state
    - Verifiers check if the agent completed the task correctly

    ## Phase 2: Research {software_name}

    Before writing any code, research:
    1. How to install {software_name} (apt, wget, snap, compile from source?)
    2. What dependencies does it need?
    3. Is it a desktop GUI app, a web app with backend, or both?
    4. What real datasets/sample files exist for it?
    5. Does it have a first-run wizard that needs suppressing?
    6. What file formats does it work with?

    Use web search and read documentation.

    ## Phase 3: Study Existing Environments

    Read at least 3 of these existing environments to learn the patterns:

    {examples_text}

    For each, read:
    - `env.json` — how the environment is configured
    - `scripts/install_*.sh` — how the software is installed
    - `scripts/setup_*.sh` — how it's configured with data
    - `scripts/task_utils.sh` — shared utility functions
    - `tasks/*/task.json` — how tasks are defined
    - `tasks/*/setup_task.sh` — how task starting state is set
    - `tasks/*/verifier.py` — how verification works

    Pay attention to:
    - Desktop apps use `DISPLAY=:1`, `xdotool`, `scrot` for interaction
    - Web apps need service readiness polling before the GUI is usable
    - `task_utils.sh` provides shared functions (screenshots, window management, app focus)
    - Verifiers use `copy_from_env()` to read files from the container
    - Data must be REAL (downloaded from public sources), never synthetic

    ## Phase 4: Create the Environment

    Create this directory structure at `{output_dir}`:

    ```
    {output_dir}/
    ├── env.json
    ├── scripts/
    │   ├── install_{software_name.lower().replace(' ', '_')}.sh
    │   ├── setup_{software_name.lower().replace(' ', '_')}.sh
    │   └── task_utils.sh
    ├── config/          # app-specific config files (optional)
    ├── data/            # real datasets (optional)
    └── tasks/
        ├── task_1/
        │   ├── task.json
        │   ├── setup_task.sh
        │   ├── export_result.sh  # optional: extracts app state to JSON
        │   └── verifier.py
        ├── task_2/
        │   └── ...
        ├── task_3/
        │   └── ...
        ├── task_4/
        │   └── ...
        └── task_5/
            └── ...
    ```

    ### env.json format

    ```json
    {{
        "id": "<env_name>@0.1",
        "version": "0.1",
        "base": "ubuntu-gnome-systemd_highres",
        "description": "...",
        "category": "...",
        "tags": ["linux", ...],
        "resources": {{
            "cpu": 4,
            "mem_gb": 4,
            "gpu": 0,
            "net": true
        }},
        "mounts": [
            {{"source": "benchmarks/cua_world/environments/<env_name>/scripts", "target": "/workspace/scripts", "mode": "ro"}},
            {{"source": "benchmarks/cua_world/environments/<env_name>/config", "target": "/workspace/config", "mode": "ro"}},
            {{"source": "benchmarks/cua_world/environments/<env_name>/tasks", "target": "/workspace/tasks", "mode": "ro"}},
            {{"source": "benchmarks/cua_world/environments/<env_name>/data", "target": "/workspace/data", "mode": "ro"}}
        ],
        "hooks": {{
            "pre_start": "/workspace/scripts/install_<name>.sh",
            "post_start": "/workspace/scripts/setup_<name>.sh"
        }},
        "security": {{
            "user": "root",
            "cap_drop": ["ALL"],
            "privileged": true,
            "use_systemd": true,
            "mount_cgroups": true,
            "cgroupns_host": true,
            "tmpfs_run": true
        }},
        "vnc": {{"password": "password"}}
    }}
    ```

    ### install script (pre_start hook)

    Installs the software and ALL dependencies. Runs once, result is cached.

    Rules:
    - Use `set -e` for fail-fast
    - `export DEBIAN_FRONTEND=noninteractive`
    - Install system utilities: `scrot wmctrl xdotool imagemagick python3-pip`
    - Install the application via apt, wget, or compile
    - Suppress first-run wizards via config files
    - Do NOT download data here (that's the setup script's job)

    ### setup script (post_start hook)

    Configures the app and seeds it with REAL data. Runs once, result is cached.

    Rules:
    - Do NOT use `set -e` (robust error handling needed)
    - Wait for desktop: `sleep 5` at the start
    - Pre-configure app settings (suppress dialogs, set preferences)
    - Download REAL data from public sources (not synthetic!)
    - Create output directories for the agent
    - Launch the app for a "warm-up" to initialize its state
    - Take a screenshot to verify setup

    ### task_utils.sh

    Shared bash functions used by all tasks. Common patterns:
    - `take_screenshot()` — captures screen via scrot/import
    - `ensure_<app>_running()` — starts app if not running
    - `focus_<app>()` — brings app window to front via wmctrl
    - `maximize_<app>()` — maximizes the app window
    - App-specific query functions (e.g., database queries)

    ### task.json format

    ```json
    {{
        "id": "<task_name>@1",
        "version": "1.0",
        "env_id": "<env_name>@0.1",
        "description": "Clear, specific task instruction. State what to do and where to save output.",
        "difficulty": "easy|medium|hard",
        "init": {{
            "timeout_sec": 300,
            "max_steps": 50,
            "reward_type": "sparse"
        }},
        "hooks": {{
            "pre_task": "/workspace/tasks/<task_name>/setup_task.sh",
            "post_task": "/workspace/tasks/<task_name>/export_result.sh"
        }},
        "metadata": {{
            "expected_output_file": "/home/ga/...",
            "ground_truth_key": "ground_truth_value"
        }},
        "success": {{
            "mode": "program",
            "spec": {{
                "program": "verifier.py::verify_<task_name>"
            }}
        }}
    }}
    ```

    ### setup_task.sh

    Sets up the specific starting state for this task:
    - Source `task_utils.sh`
    - Ensure the app is running
    - Clear any stale output files
    - Record timestamp: `date +%s > /tmp/task_start_timestamp`
    - Open the correct file/project/database
    - Take initial screenshot

    ### verifier.py

    Checks if the agent completed the task. Pattern:

    ```python
    def verify_<task_name>(traj, env_info, task_info):
        copy_from_env = env_info.get('copy_from_env')
        metadata = task_info.get('metadata', {{}})

        # Copy output file from container
        # Check file exists, has correct content
        # Compare against ground truth in metadata

        return {{"passed": bool, "score": 0-100, "feedback": "..."}}
    ```

    The verifier gets:
    - `copy_from_env(container_path, local_path)` — copy file from container
    - `exec_capture(command)` — run command in container, get stdout
    - `query_vlm(image=path, prompt=text)` — ask VLM about a screenshot
    - `task_info['metadata']` — ground truth values from task.json

    ## Example: Complete task reference

    ### task.json (DBeaver / run_sql_query)
    ```json
    {example_task_json}
    ```

    ### setup_task.sh (DBeaver / run_sql_query)
    ```bash
    {example_setup_sh}
    ```

    ### verifier.py (DBeaver / run_sql_query)
    ```python
    {example_verifier}
    ```

    ## Phase 5: Write the Files

    Now create ALL files for the {software_name} environment. Follow these rules:

    1. **5 diverse tasks** covering different features of the software
    2. **Real data only** — download from public sources, official samples, or well-known datasets
    3. **Verifiers must be programmatic** — check actual file contents, database state, or command output
    4. **Tasks must be realistic** — things a real user would do with this software professionally
    5. **Difficulty range** — include easy (1-2 steps), medium (5-10 steps), and hard (15+ steps) tasks
    6. **Ground truth in metadata** — every verifiable value must be in task.json metadata

    ## Phase 6: Test (if running on a server with Docker)

    If you have access to a gym-anything server:
    1. Build the Docker image
    2. Boot the env
    3. Take a screenshot — verify the app is running
    4. Run each task's setup — verify the starting state
    5. Attempt to complete at least one task
    6. Run the verifier — confirm it scores correctly

    If you don't have server access, just create all the files. Testing will be done separately.

    ## Phase 7: Validate Output

    Before finishing, verify:
    - [ ] env.json is valid JSON with correct schema
    - [ ] Install script installs the app (test with `apt list --installed` or `which <app>`)
    - [ ] Setup script downloads REAL data
    - [ ] task_utils.sh has screenshot + window management functions
    - [ ] All 5 tasks have task.json + setup_task.sh + verifier.py
    - [ ] Each verifier has a working `verify_<name>()` function
    - [ ] Ground truth values in metadata are correct (verified via web search or documentation)
    - [ ] No synthetic/fake data anywhere

    ## START NOW

    Create the complete environment for **{software_name}** at `{output_dir}`.
    Start by researching the software, then create all files.
    """)

    return prompt


def validate_output(output_dir: Path) -> dict:
    """Validate the generated environment directory structure."""
    results = {"valid": True, "errors": [], "warnings": []}

    # Check env.json
    env_json = output_dir / "env.json"
    if not env_json.exists():
        results["errors"].append("Missing env.json")
        results["valid"] = False
    else:
        try:
            data = json.loads(env_json.read_text())
            for key in ("id", "base", "resources", "hooks"):
                if key not in data:
                    results["errors"].append(f"env.json missing '{key}'")
                    results["valid"] = False
        except json.JSONDecodeError as e:
            results["errors"].append(f"env.json invalid JSON: {e}")
            results["valid"] = False

    # Check scripts
    scripts_dir = output_dir / "scripts"
    if not scripts_dir.exists():
        results["errors"].append("Missing scripts/ directory")
        results["valid"] = False
    else:
        scripts = list(scripts_dir.glob("*.sh"))
        if len(scripts) < 2:
            results["errors"].append(f"Expected ≥2 scripts, found {len(scripts)}")
            results["valid"] = False

    # Check tasks
    tasks_dir = output_dir / "tasks"
    if not tasks_dir.exists():
        results["errors"].append("Missing tasks/ directory")
        results["valid"] = False
    else:
        task_dirs = [d for d in tasks_dir.iterdir() if d.is_dir()]
        if len(task_dirs) < 5:
            results["warnings"].append(f"Expected 5 tasks, found {len(task_dirs)}")

        for task_dir in task_dirs:
            task_name = task_dir.name
            for required in ("task.json", "setup_task.sh", "verifier.py"):
                if not (task_dir / required).exists():
                    results["errors"].append(f"Task '{task_name}' missing {required}")
                    results["valid"] = False

            # Validate task.json
            tj = task_dir / "task.json"
            if tj.exists():
                try:
                    td = json.loads(tj.read_text())
                    for key in ("id", "description", "hooks", "success"):
                        if key not in td:
                            results["warnings"].append(f"Task '{task_name}' task.json missing '{key}'")
                except json.JSONDecodeError:
                    results["errors"].append(f"Task '{task_name}' task.json invalid JSON")
                    results["valid"] = False

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Create a new Gym-Anything environment for a software application"
    )
    parser.add_argument("software", help="Name of the software (e.g., 'Stellarium', 'Krita')")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: benchmarks/cua_world/environments/<name>_env)")
    parser.add_argument("--dry-run", action="store_true", help="Print the prompt without running Claude Code")
    parser.add_argument("--model", default="opus", help="Claude Code model (default: opus)")
    args = parser.parse_args()

    # Determine output directory
    env_name = args.software.lower().replace(" ", "_").replace("-", "_") + "_env"
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = ENVS_DIR / env_name

    # Build the prompt
    prompt = build_create_prompt(args.software, output_dir)

    if args.dry_run:
        print(prompt)
        print(f"\n--- Prompt length: {len(prompt)} chars ---")
        return

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save the prompt for reference
    prompt_file = output_dir / "_create_prompt.md"
    prompt_file.write_text(prompt)
    print(f"Prompt saved to {prompt_file}")

    # Run Claude Code
    print(f"\nLaunching Claude Code to create environment for '{args.software}'...")
    print(f"Output: {output_dir}")
    print(f"Model: {args.model}")
    print()

    try:
        result = subprocess.run(
            [
                "claude",
                "--model", args.model,
                "--print",
                "--dangerously-skip-permissions",
                "-p", prompt,
            ],
            cwd=str(REPO_ROOT),
            timeout=3600,  # 1 hour max
        )

        if result.returncode != 0:
            print(f"\nClaude Code exited with code {result.returncode}")
            sys.exit(1)

    except subprocess.TimeoutExpired:
        print("\nClaude Code timed out after 1 hour")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: 'claude' command not found. Install Claude Code: https://claude.ai/claude-code")
        sys.exit(1)

    # Validate output
    print("\n=== Validating output ===")
    validation = validate_output(output_dir)

    if validation["errors"]:
        print("ERRORS:")
        for e in validation["errors"]:
            print(f"  ✗ {e}")

    if validation["warnings"]:
        print("WARNINGS:")
        for w in validation["warnings"]:
            print(f"  ⚠ {w}")

    if validation["valid"]:
        print(f"\n✓ Environment created successfully at {output_dir}")

        # Summary
        tasks = list((output_dir / "tasks").iterdir()) if (output_dir / "tasks").exists() else []
        scripts = list((output_dir / "scripts").glob("*.sh")) if (output_dir / "scripts").exists() else []
        print(f"  Scripts: {len(scripts)}")
        print(f"  Tasks: {len([t for t in tasks if t.is_dir()])}")
    else:
        print(f"\n✗ Environment has errors — review {output_dir}")
        sys.exit(1)


if __name__ == "__main__":
    main()
