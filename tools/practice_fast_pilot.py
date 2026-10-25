"""Bounded SkillOpt full-skill proposal and independent timed CAD replay for task 1.1.

Produces an isolated candidate, never overwrites/adopts the live SKILL.md.
python tools/practice_fast_pilot.py prepare
python tools/practice_fast_pilot.py replay --run <directory>
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import shutil
import tempfile
import practice_pipeline as p
from practice_teacher import PiTeacherBackend
from skillopt_sleep.types import ReplayResult, TaskRecord


class WholeSkillTeacher(PiTeacherBackend):
    """Use SkillOpt reflection with a bounded whole-document replacement contract."""

    def _call(self, prompt: str, *, max_tokens: int = 1024) -> str:
        return super()._call(prompt + "\nThis run explicitly permits a whole-document replacement. "
                             "Return exactly one skill/replace edit, anchor WHOLE_SKILL. Content must be "
                             "the complete new SKILL.md, valid frontmatter and concise Russian body, "
                             "at most 4000 characters (hard limit, do not repeat full reference). "
                             "Missing essential dimensions MUST block, never produce guessed geometry. "
                             "Keep existing safety rules binding by reference to reference-SKILL.md; "
                             "summarize only existing session, one writer, native dimensions, fresh output, "
                             "owned documents, stop all calls after unknown native failure. "
                             "No managed-block-only restriction for this run. "
                             "Never include task-specific dimensions, shape, origin corner or solution. "
                             "No weakening safety, native constraints or correctness. "
                             "Use the reusable newly qualified recipe in optimization-objective.json. "
                             "Do not restate long API reference; link reference-SKILL.md for uncommon work.",
                             max_tokens=max_tokens)


def prepare() -> Path:
    p.preflight("pi")
    run = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-fast-"), dir=p.RUNS))
    source = p.RUNS / "20261023-221020-4wj7qgq6"
    shutil.copy2(p.SKILL / "SKILL.md", run / "baseline-skill.md")
    # Public training evidence only, already scrubbed. Never forward credentials.
    attempt = run / "training"
    for name in ("teacher-review.json", "verification/verification.json", "workspace/solution.py"):
        target = attempt / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "candidate-3" / name, target)
    (attempt / "trace.jsonl").write_text("")
    p.write_json(run / "optimization-objective.json", {
        "goal": "Correct native editable model within 60–120 worker seconds; reduce tokens",
        "diagnosis": p.read_json(source / "optimization-result.json"),
        "candidate_contract": "One whole SKILL.md replace edit; <=4000 characters, general reusable guidance only",
        "qualified_recipe": {
            "path": "examples/18_orthogonal_profiles.py",
            "use": "Copy standalone example to solution.py. Set SPEC via edit; run with --output. No imports from skill as runtime library.",
            "spec": "profiles: list of {plane: XOY|XOZ, vertices:[[u,v],...], circles:[[u,v,r],...], depth:signed}; bounds:[xmin,ymin,zmin,xmax,ymax,zmax]; volume:mm3",
            "meaning": "XOY (u,v)=(X,Y), signed depth along Z. XOZ (u,v)=(X,-Z), signed depth along Y. Single orthogonal closed polygon per profile, optional enclosed circles, no adjacent collinear edges. Each circle must have nonzero u and v offset from the first polygon vertex. Profiles union via native bosses; internal circles leave through voids within that profile.",
            "evidence": "Four native builds: XOY/XOZ with positive/negative depth, fully constrained sketches, one solid, measured signed bounds and volume. No general topology coverage claimed.",
            "direction": "SetDirection(dtNormal if depth>0 else dtReverse); SetSideParameters(depth>0, etBlind, abs(depth),0,False,None). Both settings must agree.",
            "routine_work": "Read recipe only if needed, copy, supply dimensions/geometry, run once without pipelines masking status. Do not recode constraints or perform exhaustive drawing-crop exploration. If final source changes after run, run final source again to a fresh output.",
            "safety": "Existing session only; one writer; new output; close owned document only; no further API calls after unknown native failure. Missing dimensions block rather than guessing."
        },
        "reference": "The original full skill is available in candidate workspace as skill/reference-SKILL.md",
        "time_boundary": "Worker process includes drawing interpretation, code construction, CAD execution/save/close; verifier and teacher measured separately",
        "trial": "Worker deepseek-flash thinking=low; worker profile=fast. This changes harness too, not an isolated skill-only effect; no held-out adoption."
    })
    backend = WholeSkillTeacher(run, p.CONFIG, p.run_process, evidence_attempt="training")
    backend.preferences = "Compact actionable replacement skill; first route familiar orthogonal extrusions to the qualified standalone recipe. Preserve all safety and parametric intent."
    task = TaskRecord(id="practice-1.1-fast", project=str(p.ROOT), intent=p.SOURCE.read_text(),
                      system="Construct real native CAD geometry; no task-specific answers in skill.")
    result = ReplayResult(id=task.id, hard=0., soft=.8,
                          response="Depth reflection and mismatched final source persist; 541 seconds and 3.886M tokens.",
                          optimizer_feedback="Read optimization-objective.json for measured diagnostics and qualified generic route.")
    edits = backend.reflect([(task, result)], [], (run / "baseline-skill.md").read_text(), "",
                            edit_budget=1, evolve_skill=True, evolve_memory=False)
    from dataclasses import asdict
    p.write_json(run / "proposal.json", [asdict(edit) for edit in edits])
    stage(run)
    return run


def stage(run: Path) -> None:
    edits = p.read_json(run / "proposal.json")
    if (len(edits) != 1 or edits[0]["target"] != "skill" or edits[0]["op"] != "replace"
            or edits[0]["anchor"] != "WHOLE_SKILL" or len(edits[0]["content"]) > 6500
            or not edits[0]["content"].startswith("---\n")):
        raise ValueError("Invalid full-skill candidate; no replay started")
    (run / "candidate-skill.md").write_text(edits[0]["content"] + "\n")
    p.write_json(run / "patch-result.json", {"contract": "explicit full-skill replacement in isolated replay only; 6500 character staging bound; optimizer asked for <=4000", "applied": edits, "unmatched": []})
    if (run / "run.json").exists():
        return
    p.write_json(run / "run.json", {
        "id": run.name, "task": "1.1", "title": "Ступенчатый кронштейн с отверстием — быстрый маршрут",
        "worker_model": p.WORKER, "worker_thinking": "low", "worker_profile": "fast",
        "teacher_model": "qgm-6.1-sol", "teacher_transport": "pi", "teacher_thinking": "high",
        "skill_sha256": p.sha256(p.SKILL / "SKILL.md"), "state": "candidate_prepared",
        "started_at": datetime.now(timezone.utc).isoformat(), "attempts": [],
        "scope": "same training task; new helper, skill and thinking setting; not held-out or isolated skill-only effect"})


def prepare_visual(source: Path) -> Path:
    """Replay the selected unchanged skill with an explicit worker-side image loop."""
    original = p.read_json(source / "run.json")
    selected = original["selected_attempt"]
    run = Path(tempfile.mkdtemp(
        prefix=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-visual-"), dir=p.RUNS))
    snapshot = source / selected / "workspace/skill/SKILL.md"
    shutil.copy2(snapshot, run / "baseline-skill.md")
    shutil.copy2(snapshot, run / "candidate-skill.md")
    p.write_json(run / "proposal.json", [])
    p.write_json(run / "patch-result.json", {"applied": [], "unmatched": [], "skill_unchanged": True})
    p.write_json(run / "optimization-objective.json", {
        "goal": "Worker views its own saved model and compares with drawing before finalizing",
        "baseline_run": str(source), "baseline_attempt": selected,
        "skill_unchanged": True, "preview_helper_sha256": p.sha256(p.ROOT / "tools/practice_preview.py"),
        "time_boundary": "Full worker runtime including preview export, image reads and any correction",
        "scope": "One training task, harness change; no generalization or isolated speed claim"})
    data = {key: original[key] for key in (
        "task", "worker_model", "teacher_model", "teacher_transport", "teacher_thinking")}
    data.update(id=run.name, title="Ступенчатый кронштейн — визуальная самопроверка",
                worker_thinking="low", worker_profile="fast", worker_attached_inputs=True,
                worker_image_scale=1, worker_attach_recipe=False, worker_visual_self_check=True,
                skill_sha256=p.sha256(snapshot), state="candidate_prepared", attempts=[],
                started_at=datetime.now(timezone.utc).isoformat(),
                scope="Task 1.1 training replay; unchanged selected skill plus draft render/read/compare loop; no live adoption")
    p.persist(run, data)
    return run


def replay(run: Path) -> None:
    data = p.read_json(run / "run.json")
    p.preflight("pi")
    # All reference content is unchanged, available on demand, never forced into prompt.
    reference = p.SKILL / "reference-SKILL.md"
    if reference.exists():
        raise ValueError("Unexpected live reference file")
    p.execute_attempt(run, data, "fast-candidate", (run / "candidate-skill.md").read_text())
    attempt = data["attempts"][-1]
    review = p.validated_review(run, attempt)
    if p.stop_for_blocked_review(run, data, review):
        return
    comparison = {"passed": bool(attempt["hard"]), "target_seconds": 120,
                  "worker_seconds": attempt["worker_seconds"], "worker_usage": attempt["worker_usage"],
                  "target_met": bool(attempt["hard"]) and attempt["worker_seconds"] <= 120,
                  "adopted": False, "scope": data["scope"]}
    if data.get("worker_visual_self_check"):
        visual = attempt.get("visual_self_check", {})
        comparison["visual_trajectory_completed"] = (
            visual.get("final_preview_pixels_delivered") is True
            and visual.get("final_model_matches_preview_export") is True
            and visual.get("worker_claim", {}).get("status") in {"matched", "corrected"})
        objective = p.read_json(run / "optimization-objective.json")
        baseline_data = p.read_json(Path(objective["baseline_run"]) / "run.json")
        baseline = next(item for item in baseline_data["attempts"]
                        if item["id"] == objective["baseline_attempt"])
        comparison["efficiency_vs_selected_baseline"] = p.efficiency_gate(baseline, attempt)
    p.write_json(run / "efficiency-comparison.json", comparison)
    data.update(state="complete", gate={"accepted": False, "pilot_improved": bool(attempt["hard"]),
                                       "target_met": comparison["target_met"], "scope": data["scope"]})
    p.persist(run, data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "prepare-visual", "replay"])
    parser.add_argument("--run", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    with (p.CONFIG / "cad.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "prepare":
            print(prepare(), flush=True)
        elif args.action == "prepare-visual":
            if args.source is None:
                parser.error("prepare-visual requires --source")
            print(prepare_visual(args.source.resolve()), flush=True)
        else:
            if args.run is None:
                parser.error("replay requires --run")
            replay(args.run.resolve())


if __name__ == "__main__":
    main()
