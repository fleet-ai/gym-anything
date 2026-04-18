#!/usr/bin/env python3
"""Quick server smoke test. Verifies one env produces a non-blank screenshot."""
import base64
import sys
import requests

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
    prefix = "/home/gcpuser/gym-anything/benchmarks/cua_world/environments"

    # Health
    try:
        r = requests.get(f"{url}/health", timeout=10)
        h = r.json()
        if h.get("healthy_workers", 0) == 0:
            print(f"FAIL: no healthy workers")
            return 1
        print(f"Health OK: {h['healthy_workers']} workers")
    except Exception as e:
        print(f"FAIL: health check: {e}")
        return 1

    # Create + reset + check screenshot
    env_id = None
    try:
        r = requests.post(f"{url}/envs/create",
            json={"env_dir": f"{prefix}/stellarium_env", "task_id": "observe_solar_eclipse"},
            timeout=60)
        env_id = r.json().get("env_id")
        if not env_id:
            print(f"FAIL: create: {r.json()}")
            return 1

        r = requests.post(f"{url}/envs/{env_id}/reset",
            json={"use_cache": True, "cache_level": "post_start"},
            timeout=600)
        data = r.json()
        if data.get("error"):
            print(f"FAIL: reset: {data['error']}")
            return 1

        obs = (data.get("observation") or {}).get("screen") or {}
        ss = obs.get("png_b64", "")
        if len(ss) < 100000:
            print(f"FAIL: screenshot too small ({len(ss)} chars, need >100000)")
            return 1

        print(f"PASS: screenshot {len(ss)} chars ({len(base64.b64decode(ss))} bytes)")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 1
    finally:
        if env_id:
            try:
                requests.post(f"{url}/envs/{env_id}/close", timeout=10)
            except Exception:
                pass

if __name__ == "__main__":
    sys.exit(main())
