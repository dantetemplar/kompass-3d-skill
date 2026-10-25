"""One bounded follow-up reflection and replay; never adopts the proposed skill."""
from __future__ import annotations

from dataclasses import asdict
import fcntl
from pathlib import Path
import shutil
import sys

import practice_fast_pilot as fast
from skillopt_sleep.types import ReplayResult, TaskRecord


def main() -> None:
    p = fast.p
    run = Path(sys.argv[1]).resolve()
    with (p.CONFIG / "cad.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = p.read_json(run / "run.json")
        attempt_id = sys.argv[2] if len(sys.argv) > 2 else "fast-candidate-2"
        passed = [item for item in data["attempts"] if item.get("hard") == 1]
        observed = min(passed, key=lambda item: item["worker_seconds"]) if passed else data["attempts"][-1]
        review = p.validated_review(run, observed)
        history = run / f"before-{attempt_id}"
        history.mkdir()
        for name in ("proposal.json", "candidate-skill.md", "patch-result.json", "efficiency-comparison.json", "run.json"):
            shutil.copy2(run / name, history / name)
        backend = fast.WholeSkillTeacher(run, p.CONFIG, p.run_process,
                                        evidence_attempt=observed["directory"])
        backend.preferences = (
            "The correct low-thinking replay took 269.064s / 1118093 tokens: 16 read and 23 bash calls, "
            "mostly repeated crops and programmatic pixel analysis. Turning thinking off was worse: "
            "299.708s / 2118962 tokens, 81 requests, failed geometry. Preserve low thinking. "
            "Retain the current correct general right-handed front-view rule: X right and Z up means "
            "positive Y AWAY from viewer. Choose convenient datums; absolute origin is ignored by user policy. "
            "Allow translation and proper rotation, never reflection or wrong relative feature placement. "
            "Request an actionable lean workflow: read task, drawing and recipe in one batch; "
            "if labels are unclear, one combined enlarged view, not repeated pixel/color scans, "
            "scipy, or raster measurement of dimensioned geometry. Use written dimensions and "
            "projection relationships; genuine ambiguity still blocks rather than guessing. "
            "Use cp to copy the entire standalone recipe to solution.py then edit only its SPEC marker; "
            "do not rewrite or truncate the recipe, survey directories or read run.sh. Execute once "
            "with --output, and treat its built-in assertions as routine checks. "
            "No repeated arithmetic/crops merely for reassurance. Preserve signed bounds and "
            "asymmetry checks; final source must match the saved artifact. "
            "Mandatory reference-SKILL safety remains binding. No task-specific dimensions or solutions.")
        task = TaskRecord(id="practice-1.1-fast", project=str(p.ROOT), intent=p.SOURCE.read_text(),
                          system="Build actual native artifact, no task answer in skill.")
        result = ReplayResult(id=task.id, hard=0., soft=review["score"],
                              response=review["feedback"], optimizer_feedback=review["feedback"])
        edits = backend.reflect([(task, result)], [], (run / "candidate-skill.md").read_text(), "",
                                edit_budget=1, evolve_skill=True, evolve_memory=False)
        p.write_json(run / "proposal.json", [asdict(edit) for edit in edits])
        fast.stage(run)
        # Preserve evidence and settings; stage never adopts or resets prior attempts here.
        data.pop("gate", None)
        data["state"] = "candidate_prepared"
        data["worker_thinking"] = "low"
        data["scope"] = "Task 1.1 training replay; bounded teacher skill refinement, same worker/helper with low thinking; not held-out"
        p.persist(run, data)
        p.execute_attempt(run, data, attempt_id, (run / "candidate-skill.md").read_text())
        attempt = data["attempts"][-1]
        review = p.validated_review(run, attempt)
        if p.stop_for_blocked_review(run, data, review):
            return
        comparison = {"passed": bool(attempt["hard"]), "target_seconds": 120,
                      "worker_seconds": attempt["worker_seconds"], "worker_usage": attempt["worker_usage"],
                      "target_met": bool(attempt["hard"]) and attempt["worker_seconds"] <= 120,
                      "adopted": False, "scope": data["scope"]}
        p.write_json(run / "efficiency-comparison.json", comparison)
        data.update(state="complete", gate={"accepted": False, "target_met": comparison["target_met"],
                                           "scope": data["scope"]})
        p.persist(run, data)


if __name__ == "__main__":
    main()
