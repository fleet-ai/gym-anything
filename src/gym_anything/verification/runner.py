from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ..runtime.runners.base import BaseRunner
from ..specs import EnvSpec, TaskSpec
from ..vlm import query_vlm, sample_trajectory_frames, get_final_screenshot, get_first_screenshot
from .imports import verifier_import_context


class VerifierRunner:
    """Dispatches to programmatic or image-match verifiers based on TaskSpec."""

    def evaluate(
        self,
        runner: BaseRunner,
        env_spec: EnvSpec,
        task_spec: TaskSpec,
        episode_dir: Path,
        env_root: Optional[Path],
        task_root: Optional[Path],
    ) -> Dict[str, Any]:
        mode = task_spec.success.mode
        spec = task_spec.success.spec or {}
        report: Dict[str, Any] = {"mode": mode}
        # breakpoint()
        # Auto-upgrade to vlm_checklist if the file exists and VLM_CHECKLIST_OVERRIDE is set
        if mode == "program" and os.environ.get("VLM_CHECKLIST_OVERRIDE", "").lower() in ("1", "true", "yes"):
            if task_root and (task_root / "vlm_checklist.json").exists():
                mode = "vlm_checklist"
                report["mode"] = mode
                logger.info(f"Auto-upgraded verifier mode to vlm_checklist for {task_spec.id}")

        if mode == "vlm_checklist":
            report.update(
                self._run_vlm_checklist(episode_dir, task_spec, task_root)
            )
        elif mode == "program":
            report.update(
                self._run_program_verifier(spec, episode_dir, env_spec, task_spec, task_root, env_root, runner)
            )
        elif mode == "image_match":
            report.update(
                self._run_image_match(runner, spec, episode_dir, env_root, task_root)
            )
        elif mode == "multi":
            # Try program first, then image_match
            prog = self._run_program_verifier(
                spec.get("program", {}),
                episode_dir,
                env_spec,
                task_spec,
                task_root,
                env_root,
                runner,
            )
            if prog.get("decided"):
                prog["mode"] = "program"
                return prog
            img = self._run_image_match(runner, spec.get("image_match", {}), episode_dir, env_root, task_root)
            img["mode"] = "image_match"
            return img
        else:
            report.update({"error": f"unsupported mode: {mode}", "passed": False, "score": 0})
        return report

    def _run_program_verifier(
        self,
        spec: Dict[str, Any],
        episode_dir: Path,
        env_spec: EnvSpec,
        task_spec: TaskSpec,
        task_root: Optional[Path],
        env_root: Optional[Path],
        runner: Optional[BaseRunner] = None,
    ) -> Dict[str, Any]:
        target = spec if isinstance(spec, str) else spec.get("program") or spec.get("target")
        if not target:
            return {"error": "no program specified", "passed": False, "score": 0, "decided": False}
        func = self._load_function(target, task_root, env_root)
        traj = self._load_traj(episode_dir)
        env_info = {"env_id": env_spec.id, "episode_dir": str(episode_dir)}
        
        # Add copy utilities if runner is available
        if runner:
            env_info["copy_from_env"] = runner.copy_from
            env_info["copy_to_env"] = runner.copy_to
            # Add exec_capture for direct command execution (used for secure DB queries)
            env_info["exec_capture"] = runner.exec_capture
            runtime_info_getter = getattr(runner, "get_runtime_info", None)
            if callable(runtime_info_getter):
                runtime_info = runtime_info_getter()
                if runtime_info.container_name:
                    env_info["container"] = runtime_info.container_name
            elif hasattr(runner, "container_name"):
                env_info["container"] = runner.container_name

        # Provide VLM utilities so verifiers can do visual checks
        # without needing to import from gym_anything (verifiers are
        # loaded via spec_from_file_location and may not have gym_anything
        # on their import path).
        env_info["query_vlm"] = query_vlm
        env_info["sample_trajectory_frames"] = sample_trajectory_frames
        env_info["get_final_screenshot"] = get_final_screenshot
        env_info["get_first_screenshot"] = get_first_screenshot

        task_info = {
            "task_id": task_spec.id,
            "metadata": task_spec.metadata if task_spec.metadata else {},
            "task_spec": asdict(task_spec),
        }
        try:
            res = func(traj, env_info, task_info)
            # Expect dict with passed/score
            return {"decided": True, **res}
        except Exception as e:
            return {"error": f"verifier error: {e}", "passed": False, "score": 0, "decided": True}

    def _load_traj(self, episode_dir: Path) -> Dict[str, Any]:
        """Load trajectory data including frames for VLM-based verification.

        Returns dict with:
            - steps: List of events from traj.jsonl
            - episode_dir: Path to episode directory
            - frames: List of frame paths sorted by step index
            - final_screenshot: Path to final.png if exists
            - post_verification_screenshot: Path to post_verification.png if exists
            - first_frame: Path to first frame (frame_00000.png) if exists
            - last_frame: Path to last frame if exists

        This is backward compatible - existing verifiers can ignore the new keys.
        """
        traj_path = episode_dir / "traj.jsonl"
        steps = []
        if traj_path.exists():
            with traj_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        steps.append(json.loads(line))
                    except Exception:
                        pass

        # Find all frame screenshots (sorted by step index)
        frames = sorted(episode_dir.glob("frame_*.png"))
        frame_paths = [str(f) for f in frames]

        # Find special screenshots
        final_png = episode_dir / "final.png"
        post_verification_png = episode_dir / "post_verification.png"

        # Build trajectory dict
        traj = {
            "steps": steps,
            "episode_dir": str(episode_dir),
            "frames": frame_paths,
            "final_screenshot": str(final_png) if final_png.exists() else None,
            "post_verification_screenshot": str(post_verification_png) if post_verification_png.exists() else None,
            "first_frame": frame_paths[0] if frame_paths else None,
            "last_frame": frame_paths[-1] if frame_paths else None,
        }

        # Add step-to-frame mapping for easy lookup
        # step_frames[idx] = path to frame for that step
        step_frames = {}
        for fp in frame_paths:
            # Extract step index from frame_XXXXX.png
            fname = Path(fp).stem
            if fname.startswith("frame_"):
                try:
                    idx = int(fname.split("_")[1])
                    step_frames[idx] = fp
                except (ValueError, IndexError):
                    pass
        traj["step_frames"] = step_frames

        return traj

    def _load_function(self, ref: str, task_root: Optional[Path], env_root: Optional[Path]):
        # Support "verifier.py::func" relative to task_root, or "pkg.mod:func" import path
        if "::" in ref:
            file, func = ref.split("::", 1)
            if not task_root:
                raise ValueError("task_root not set for file-based verifier")
            path = task_root / file
            with verifier_import_context(task_root=task_root, env_root=env_root):
                spec = importlib.util.spec_from_file_location("task_verifier", path)
                if not spec or not spec.loader:
                    raise ImportError(f"cannot import from {path}")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[attr-defined]
                fn = getattr(mod, func)
                return fn
        # import path 'pkg.module:function'
        if ":" in ref:
            mod_name, func = ref.split(":", 1)
            mod = importlib.import_module(mod_name)
            return getattr(mod, func)
        raise ValueError("Invalid program reference; expected 'file.py::func' or 'pkg.mod:func'")

    def _sample_frames_for_vlm(self, traj: Dict[str, Any]) -> List[str]:
        """Sample trajectory frames: first 3, every 3rd middle, last 3."""
        frames = traj.get("frames", [])
        if not frames:
            final = traj.get("final_screenshot")
            return [final] if final else []
        if len(frames) <= 6:
            return list(frames)

        sampled = list(frames[:3])
        middle = frames[3:-3]
        sampled.extend(middle[::3])
        sampled.extend(frames[-3:])
        return sampled

    def _run_vlm_checklist(
        self,
        episode_dir: Path,
        task_spec: TaskSpec,
        task_root: Optional[Path],
    ) -> Dict[str, Any]:
        """Grade trajectory using VLM checklist verification (paper Eq. 2)."""
        if not task_root:
            return {"error": "task_root required for vlm_checklist", "passed": False, "score": 0}

        # Load checklist
        checklist_path = task_root / "vlm_checklist.json"
        if not checklist_path.exists():
            return {"error": f"vlm_checklist.json not found at {checklist_path}", "passed": False, "score": 0}
        try:
            checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"error": f"failed to parse vlm_checklist.json: {e}", "passed": False, "score": 0}

        # Load privileged info
        pi_path = task_root / "validated_pi.json"
        pi_text = checklist.get("privileged_info_for_vlm", "No privileged information available.")
        if pi_path.exists():
            try:
                pi_data = json.loads(pi_path.read_text(encoding="utf-8"))
                if isinstance(pi_data, dict) and pi_data.get("summary"):
                    pi_text = pi_data["summary"]
                elif isinstance(pi_data, str):
                    pi_text = pi_data
            except Exception:
                pass

        # Load trajectory and sample frames
        traj = self._load_traj(episode_dir)
        frame_paths = self._sample_frames_for_vlm(traj)
        if not frame_paths:
            return {"error": "no trajectory frames found", "passed": False, "score": 0}

        # Build completion items text
        completion_items = checklist.get("task_completion", [])
        integrity_items = checklist.get("integrity", [])

        completion_text = ""
        for i, item in enumerate(completion_items, 1):
            completion_text += (
                f"{i}. [{item['id']}] (points: {item.get('points', 0)})\n"
                f"   Description: {item['description']}\n"
                f"   Visual evidence: {item.get('visual_evidence', 'N/A')}\n\n"
            )

        integrity_text = ""
        for i, item in enumerate(integrity_items, 1):
            integrity_text += (
                f"{i}. [{item['id']}]\n"
                f"   Description: {item['description']}\n"
                f"   Visual evidence: {item.get('visual_evidence', 'N/A')}\n\n"
            )

        task_desc = task_spec.description or f"Task: {task_spec.id}"

        prompt = f"""You are an expert evaluator scoring AI agent trajectories on computer-use benchmark tasks. Examine the trajectory screenshots and score the agent's work against the checklist.

SCORING RULES:
- For each task_completion item: "pass" (full points), "partial" (half points), or "fail" (0 points)
- For each integrity item: "pass" or "fail"
- Be strict: only give "pass" if you see clear visual evidence. However, if a checklist item is non-essential for the task completion solely based on the task description, and other items are completed, you can give "pass".
- "partial" is for when the agent made meaningful progress but didn't fully complete the sub-task

INTEGRITY CHECK RULES:
- Integrity checks detect CHEATING or SHORTCUTS, NOT task failure.
- An agent that genuinely attempted the task but failed is an INTEGRITY PASS.
- Only mark integrity FAIL if you see clear evidence of: hardcoding answers, copy-pasting expected values, fabricating results without using the software, or bypassing the required workflow entirely.

Task Description: {task_desc}
Privileged Information (verified facts): {pi_text}

=== TASK COMPLETION CHECKLIST ===
{completion_text}
=== INTEGRITY CHECKS ===
{integrity_text}
The screenshots below are from the agent's trajectory (first 3 frames, sampled middle frames, last 3 frames). Examine them carefully and score each checklist item.

Respond with ONLY a JSON object:
{{
    "task_completion": [
        {{"id": "item_id", "verdict": "pass|partial|fail", "confidence": 0.9, "evidence": "what you see"}}
    ],
    "integrity": [
        {{"id": "item_id", "verdict": "pass|fail", "confidence": 0.9, "evidence": "what you see"}}
    ],
    "overall_reasoning": "1-3 sentence summary"
}}"""

        # Call VLM
        try:
            result = query_vlm(prompt=prompt, images=frame_paths, max_tokens=4096, temperature=0.1)
        except Exception as e:
            return {"error": f"VLM query failed: {e}", "passed": False, "score": 0}

        if not result.get("success"):
            return {"error": f"VLM error: {result.get('error', 'unknown')}", "passed": False, "score": 0}

        parsed = result.get("parsed", {})
        if not parsed:
            return {"error": f"VLM returned unparseable response: {result.get('response', '')[:500]}", "passed": False, "score": 0}

        # Compute score from VLM verdicts
        # Check integrity first — any failure → score = 0
        integrity_pass = True
        integrity_results = parsed.get("integrity", [])
        for item in integrity_results:
            if item.get("verdict", "").lower() == "fail":
                integrity_pass = False
                break

        if not integrity_pass:
            return {
                "passed": False,
                "score": 0,
                "feedback": "Integrity check failed",
                "vlm_response": parsed,
                "integrity_pass": False,
            }

        # Score task_completion items
        total_score = 0
        max_score = 0
        item_map = {item["id"]: item for item in completion_items}
        completion_results = parsed.get("task_completion", [])
        for vlm_item in completion_results:
            item_id = vlm_item.get("id", "")
            verdict = vlm_item.get("verdict", "fail").lower()
            points = item_map.get(item_id, {}).get("points", 0)
            max_score += points
            if verdict == "pass":
                total_score += points
            elif verdict == "partial":
                total_score += points / 2

        # Normalize to 0-100 if max_score != 100
        if max_score > 0 and max_score != 100:
            total_score = total_score * 100 / max_score

        score = round(total_score, 1)
        passed = score >= 100.0

        return {
            "passed": passed,
            "score": score,
            "feedback": parsed.get("overall_reasoning", ""),
            "vlm_response": parsed,
            "integrity_pass": integrity_pass,
            "frames_sampled": len(frame_paths),
        }

    def _run_image_match(
        self,
        runner: BaseRunner,
        spec: Dict[str, Any],
        episode_dir: Path,
        env_root: Optional[Path],
        task_root: Optional[Path],
    ) -> Dict[str, Any]:
        # Inputs
        observed = Path(spec.get("observed") or "final.png")
        if not observed.is_absolute():
            observed = episode_dir / observed
        target = spec.get("target")
        if not target:
            return {"error": "image_match target missing", "passed": False, "score": 0, "decided": False}
        # Resolve target path (relative to task_root or env_root)
        target_path = Path(target)
        if not target_path.is_absolute():
            base = task_root or env_root or Path.cwd()
            target_path = base / target_path
        if not target_path.exists():
            return {"error": f"target not found: {target_path}", "passed": False, "score": 0, "decided": False}

        # Copy target into container (for ffmpeg ssim) and run SSIM comparison via ffmpeg
        container_target = runner.put_file(target_path)
        container_observed = runner.to_container_path(observed)
        # ffmpeg ssim filter prints metrics to stderr; we redirect to stdout via bash -lc capturing
        cmd = (
            "ffmpeg -y -loglevel info "
            f"-i {container_observed} -i {container_target} -lavfi ssim -f null -"
        )
        out = runner.exec_capture(cmd)
        # Parse 'All:0.984' from ffmpeg output
        m = re.search(r"All:([0-9.]+)", out)
        score = float(m.group(1)) if m else 0.0
        thresh = float(spec.get("metric", {}).get("ssim_gt", spec.get("ssim_gt", 0.95)))
        passed = score >= thresh
        return {"decided": True, "passed": passed, "score": round(score * 100, 2), "ssim": score}
