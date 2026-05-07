    # Environment Creation for Gym-Anything

    You are creating a new Gym-Anything environment for the software: **Krita**

    The output directory is: `/private/tmp/fleet-gym-anything/benchmarks/cua_world/environments/krita_env`

    ## Your Objective

    Create a complete, working environment that:
    1. Installs and configures Krita in a Docker container
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

    ## Phase 2: Research Krita

    Before writing any code, research:
    1. How to install Krita (apt, wget, snap, compile from source?)
    2. What dependencies does it need?
    3. Is it a desktop GUI app, a web app with backend, or both?
    4. What real datasets/sample files exist for it?
    5. Does it have a first-run wizard that needs suppressing?
    6. What file formats does it work with?

    Use web search and read documentation.

    ## Phase 3: Study Existing Environments

    Read at least 3 of these existing environments to learn the patterns:

      - stellarium_env: base=ubuntu-gnome-systemd_highres, scripts=['task_utils.sh', 'install_stellarium.sh', 'setup_stellarium.sh'], tasks=80
  - dbeaver_env: base=ubuntu-gnome-systemd_highres, scripts=['task_utils.sh', 'install_dbeaver.sh', 'setup_dbeaver.sh'], tasks=81
  - libreoffice_calc_env: base=ubuntu-gnome-systemd_highres, scripts=['install_calc.sh', 'task_utils.sh', 'setup_calc.sh'], tasks=195
  - firefox_env: base=ubuntu-gnome-systemd_highres, scripts=['install_firefox.sh', 'setup_firefox.sh'], tasks=99

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

    Create this directory structure at `/private/tmp/fleet-gym-anything/benchmarks/cua_world/environments/krita_env`:

    ```
    /private/tmp/fleet-gym-anything/benchmarks/cua_world/environments/krita_env/
    ├── env.json
    ├── scripts/
    │   ├── install_krita.sh
    │   ├── setup_krita.sh
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
    {
        "id": "<env_name>@0.1",
        "version": "0.1",
        "base": "ubuntu-gnome-systemd_highres",
        "description": "...",
        "category": "...",
        "tags": ["linux", ...],
        "resources": {
            "cpu": 4,
            "mem_gb": 4,
            "gpu": 0,
            "net": true
        },
        "mounts": [
            {"source": "benchmarks/cua_world/environments/<env_name>/scripts", "target": "/workspace/scripts", "mode": "ro"},
            {"source": "benchmarks/cua_world/environments/<env_name>/config", "target": "/workspace/config", "mode": "ro"},
            {"source": "benchmarks/cua_world/environments/<env_name>/tasks", "target": "/workspace/tasks", "mode": "ro"},
            {"source": "benchmarks/cua_world/environments/<env_name>/data", "target": "/workspace/data", "mode": "ro"}
        ],
        "hooks": {
            "pre_start": "/workspace/scripts/install_<name>.sh",
            "post_start": "/workspace/scripts/setup_<name>.sh"
        },
        "security": {
            "user": "root",
            "cap_drop": ["ALL"],
            "privileged": true,
            "use_systemd": true,
            "mount_cgroups": true,
            "cgroupns_host": true,
            "tmpfs_run": true
        },
        "vnc": {"password": "password"}
    }
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
    {
        "id": "<task_name>@1",
        "version": "1.0",
        "env_id": "<env_name>@0.1",
        "description": "Clear, specific task instruction. State what to do and where to save output.",
        "difficulty": "easy|medium|hard",
        "init": {
            "timeout_sec": 300,
            "max_steps": 50,
            "reward_type": "sparse"
        },
        "hooks": {
            "pre_task": "/workspace/tasks/<task_name>/setup_task.sh",
            "post_task": "/workspace/tasks/<task_name>/export_result.sh"
        },
        "metadata": {
            "expected_output_file": "/home/ga/...",
            "ground_truth_key": "ground_truth_value"
        },
        "success": {
            "mode": "program",
            "spec": {
                "program": "verifier.py::verify_<task_name>"
            }
        }
    }
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
        metadata = task_info.get('metadata', {})

        # Copy output file from container
        # Check file exists, has correct content
        # Compare against ground truth in metadata

        return {"passed": bool, "score": 0-100, "feedback": "..."}
    ```

    The verifier gets:
    - `copy_from_env(container_path, local_path)` — copy file from container
    - `exec_capture(command)` — run command in container, get stdout
    - `query_vlm(image=path, prompt=text)` — ask VLM about a screenshot
    - `task_info['metadata']` — ground truth values from task.json

    ## Example: Complete task reference

    ### task.json (DBeaver / run_sql_query)
    ```json
    {
  "id": "run_sql_query@1",
  "version": "1.0",
  "env_id": "dbeaver_env@0.1",
  "description": "Using DBeaver and the Chinook SQLite database, identify all track names by the artist 'AC/DC'. Export the resulting list of track names to /home/ga/Documents/exports/acdc_tracks.csv.",
  "difficulty": "medium",
  "init": {
    "timeout_sec": 240,
    "max_steps": 40,
    "reward_type": "sparse"
  },
  "hooks": {
    "pre_task": "/workspace/tasks/run_sql_query/setup_task.sh",
    "post_task": "/workspace/tasks/run_sql_query/export_result.sh"
  },
  "metadata": {
    "expected_artist": "AC/DC",
    "expected_track_count": 18,
    "expected_output_file": "/home/ga/Documents/exports/acdc_tracks.csv",
    "known_track_names": [
      "For Those About To Rock",
      "Put The Finger On You",
      "Lets Get It Up",
      "Inject The Venom",
      "Snowballed",
      "Evil Walks",
      "C.O.D.",
      "Breaking The Rules",
      "Night Of The Long Knives",
      "Spellbound",
      "Go Down",
      "Dog Eat Dog",
      "Let There Be Rock",
      "Bad Boy Boogie",
      "Problem Child",
      "Overdose",
      "Hell Aint A Bad Place To Be",
      "Whole Lotta Rosie"
    ]
  },
  "success": {
    "mode": "program",
    "spec": {
      "program": "verifier.py::verify_run_sql_query"
    }
  }
}

    ```

    ### setup_task.sh (DBeaver / run_sql_query)
    ```bash
    #!/bin/bash
# Setup script for run_sql_query task
# Records initial state before agent action

echo "=== Setting up Run SQL Query Task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Ensure DBeaver is running
if [ "$(is_dbeaver_running)" = "false" ]; then
    echo "Starting DBeaver..."
    su - ga -c "DISPLAY=:1 /usr/share/dbeaver-ce/dbeaver > /tmp/dbeaver.log 2>&1 &"
    sleep 10
fi

# Focus DBeaver window
focus_dbeaver

# Record initial state - verify the database has AC/DC tracks
echo "Verifying database state..."
ACDC_TRACKS=$(chinook_query "SELECT COUNT(*) FROM tracks t JOIN albums a ON t.AlbumId = a.AlbumId JOIN artists ar ON a.ArtistId = ar.ArtistId WHERE ar.Name = 'AC/DC';")
echo "AC/DC tracks in database: $ACDC_TRACKS"
echo "$ACDC_TRACKS" > /tmp/expected_acdc_tracks

# Take initial screenshot
take_screenshot /tmp/task_start_screenshot.png

echo "=== Task Setup Complete ==="

    ```

    ### verifier.py (DBeaver / run_sql_query)
    ```python
    #!/usr/bin/env python3
"""
Verifier for Run SQL Query task in DBeaver

Verifies actual query execution by checking:
1. Output file exists with query results
2. Output contains correct number of rows (18 AC/DC tracks)
3. Output contains known AC/DC track names
4. Does NOT require specific SQL syntax - any valid approach is accepted
"""

import json
import logging
import os
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Known AC/DC track names for validation
KNOWN_ACDC_TRACKS = [
    "For Those About To Rock",
    "Put The Finger On You",
    "Let There Be Rock",
    "Hell Ain't A Bad Place To Be",
    "Whole Lotta Rosie",
    "Dog Eat Dog",
    "Problem Child",
    "Overdose",
    "Inject The Venom",
    "Snowballed",
    "Evil Walks",
    "C.O.D.",
    "Breaking The Rules",
    "Night Of The Long Knives",
    "Spellbound",
    "Go Down",
    "Bad Boy Boogie",
    "Lets Get It Up"
]


def verify_run_sql_query(traj, env_info, task_info):
    """
    Verify that a SQL query was executed and results were saved.

    Criteria:
    1. Output file exists at expected path (REQUIRED)
    2. Output has correct row count (~18) (REQUIRED)
    3. Output contains known AC/DC track names (REQUIRED)
    4. SQL query file found (bonus, not required)
    5. VLM verification of results (if available)
    """
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Get VLM function for visual verification
    query_vlm = env_info.get('query_vlm')

    # Get expected values from task metadata
    metadata = task_info.get('metadata', {})
    expected_track_count = metadata.get('expected_track_count', 18)
    expected_output_file = metadata.get('expected_output_file', '/home/ga/Documents/exports/acdc_tracks.csv')

    try:
        # Copy result JSON from container
        temp_result = tempfile.NamedTemporaryFile(delete=False, 
    ```

    ## Phase 5: Write the Files

    Now create ALL files for the Krita environment. Follow these rules:

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

    Create the complete environment for **Krita** at `/private/tmp/fleet-gym-anything/benchmarks/cua_world/environments/krita_env`.
    Start by researching the software, then create all files.
