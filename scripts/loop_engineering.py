"""Pure, reproducible state for the maps-to-3d engineering loop.

This module does not import bpy. The agent evaluates each render/reference pair,
records scores and defects, applies one change family, and uses ``decision`` to
continue, accept, or restore the best checkpoint.
"""
from copy import deepcopy
import json
import os
import tempfile


SCHEMA_VERSION = 2
DIMENSION_WEIGHTS = {
    "semantics": 0.18,
    "geometry": 0.18,
    "silhouette": 0.14,
    "facade_structure": 0.14,
    "color": 0.12,
    "framing": 0.10,
    "materials": 0.08,
    "lighting": 0.06,
}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _score(value):
    value = float(value)
    if not 0.0 <= value <= 100.0:
        raise ValueError("scores must be between 0 and 100")
    return round(value, 2)


def normalize_scores(scores):
    missing = set(DIMENSION_WEIGHTS) - set(scores or {})
    if missing:
        raise ValueError("missing score dimensions: %s" % ", ".join(sorted(missing)))
    return {key: _score(scores[key]) for key in DIMENSION_WEIGHTS}


def weighted_score(scores):
    scores = normalize_scores(scores)
    return round(sum(scores[key] * weight
                     for key, weight in DIMENSION_WEIGHTS.items()), 2)


def rank_defects(defects):
    """Sort defects by severity and then estimated impact."""
    out = []
    for defect in defects or []:
        item = dict(defect)
        severity = str(item.get("severity", "medium")).lower()
        if severity not in SEVERITY_ORDER:
            raise ValueError("invalid defect severity: %s" % severity)
        item["severity"] = severity
        item["impact"] = _score(item.get("impact", 50))
        item.setdefault("category", "facade_structure")
        item.setdefault("fix", "inspect and correct")
        out.append(item)
    return sorted(out, key=lambda d: (SEVERITY_ORDER[d["severity"]],
                                      -d["impact"], str(d.get("category"))))


def new_state(project, references=None, holdout_references=None,
              max_iterations=6, target_score=85.0, min_dimension=70.0,
              min_delta=1.0, patience=2, max_generalization_gap=8.0):
    if int(max_iterations) < 1:
        raise ValueError("max_iterations must be >= 1")
    return {
        "schema_version": SCHEMA_VERSION,
        "project": str(project),
        "references": list(references or []),
        "holdout_references": list(holdout_references or []),
        "policy": {
            "max_iterations": int(max_iterations),
            "target_score": _score(target_score),
            "min_dimension": _score(min_dimension),
            "min_delta": max(0.0, float(min_delta)),
            "patience": max(1, int(patience)),
            "max_generalization_gap": max(0.0, float(max_generalization_gap)),
        },
        "iterations": [],
        "best_iteration": None,
        "best_score": None,
        "stagnation": 0,
        "status": "running",
    }


def record_iteration(state, scores, defects=None, change=None, artifacts=None,
                     camera_signature=None, validation_scores=None, notes=None):
    """Record an observation and update best/stagnation without mutating input.

    Iteration 0 is the baseline and needs no ``change``. Later iterations require
    one change category so improvements or regressions remain attributable.
    """
    out = deepcopy(state)
    if out.get("status") != "running":
        raise ValueError("cannot append to a finished loop")
    index = len(out["iterations"])
    if index > 0:
        if not isinstance(change, dict) or not change.get("category"):
            raise ValueError("iterations after baseline require one controlled change")
        if isinstance(change.get("category"), (list, tuple, set)):
            raise ValueError("change.category must identify one failure family")
        previous_camera = out["iterations"][-1].get("camera_signature")
        if (previous_camera is not None
                and change.get("category") not in ("camera", "framing")
                and camera_signature != previous_camera):
            raise ValueError("non-camera changes must keep the camera signature frozen")

    clean_scores = normalize_scores(scores)
    total = weighted_score(clean_scores)
    clean_validation = (normalize_scores(validation_scores)
                        if validation_scores is not None else None)
    validation_total = (weighted_score(clean_validation)
                        if clean_validation is not None else None)
    selection_score = min(total, validation_total) if validation_total is not None else total
    generalization_gap = (round(abs(total - validation_total), 2)
                          if validation_total is not None else None)
    ranked = rank_defects(defects)
    previous = (out["iterations"][-1]["selection_score"]
                if out["iterations"] else None)
    delta = None if previous is None else round(selection_score - previous, 2)
    record = {
        "index": index,
        "scores": clean_scores,
        "score": total,
        "validation_scores": clean_validation,
        "validation_score": validation_total,
        "selection_score": selection_score,
        "generalization_gap": generalization_gap,
        "delta": delta,
        "defects": ranked,
        "critical_count": sum(1 for d in ranked if d["severity"] == "critical"),
        "change": deepcopy(change),
        "artifacts": deepcopy(artifacts or {}),
        "camera_signature": camera_signature,
        "notes": notes,
    }
    out["iterations"].append(record)

    if out["best_score"] is None or selection_score > out["best_score"]:
        out["best_score"] = selection_score
        out["best_iteration"] = index

    if delta is None or delta >= out["policy"]["min_delta"]:
        out["stagnation"] = 0
    else:
        out["stagnation"] += 1

    verdict = decision(out)
    out["status"] = verdict["status"]
    return out


def decision(state):
    iterations = state.get("iterations", [])
    if not iterations:
        return {"status": "running", "action": "render_baseline",
                "reason": "no baseline", "next_defect": None}
    latest = iterations[-1]
    policy = state["policy"]
    min_score = min(latest["scores"].values())
    holdout_required = bool(state.get("holdout_references"))
    if holdout_required and latest.get("validation_scores") is None:
        if len(iterations) >= policy["max_iterations"]:
            return {"status": "stopped", "action": "restore_best",
                    "reason": "maximum iterations reached without holdout evidence",
                    "next_defect": None}
        return {"status": "running", "action": "render_holdout",
                "reason": "held-out references require validation scores",
                "next_defect": {"category": "evaluation", "severity": "high",
                                "impact": 90.0,
                                "fix": "render and score the frozen holdout view"}}
    holdout_min = (min(latest["validation_scores"].values())
                   if latest.get("validation_scores") else 100.0)
    holdout_score = (latest.get("validation_score")
                     if latest.get("validation_score") is not None else 100.0)
    gap = (latest.get("generalization_gap")
           if latest.get("generalization_gap") is not None else 0.0)
    if (latest["score"] >= policy["target_score"] and
            min_score >= policy["min_dimension"] and
            holdout_score >= policy["target_score"] and
            holdout_min >= policy["min_dimension"] and
            gap <= policy["max_generalization_gap"] and
            latest["critical_count"] == 0):
        return {"status": "accepted", "action": "deliver",
                "reason": "acceptance gates passed", "next_defect": None}
    if len(iterations) >= policy["max_iterations"]:
        return {"status": "stopped", "action": "restore_best",
                "reason": "maximum iterations reached", "next_defect": None}
    if state.get("stagnation", 0) >= policy["patience"]:
        return {"status": "stopped", "action": "restore_best",
                "reason": "score stagnated", "next_defect": None}
    if gap > policy["max_generalization_gap"]:
        next_defect = {
            "category": "generalization", "severity": "high", "impact": 95.0,
            "fix": "reject the view-specific tweak; use a source/tag-driven change that improves holdout",
        }
    else:
        next_defect = latest["defects"][0] if latest["defects"] else {
            "category": min(latest["scores"], key=latest["scores"].get),
            "severity": "medium", "impact": 50.0,
            "fix": "improve the lowest-scoring dimension",
        }
    return {"status": "running", "action": "correct_one_family",
            "reason": "acceptance gates not met", "next_defect": next_defect}


def best_record(state):
    idx = state.get("best_iteration")
    if idx is None:
        return None
    return deepcopy(state["iterations"][idx])


def save_state(state, path):
    """Write atomically so a Blender or MCP failure cannot lose loop state."""
    path = os.path.abspath(str(path))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".loop-", suffix=".json",
                               dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def load_state(path):
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported loop state schema")
    return state
