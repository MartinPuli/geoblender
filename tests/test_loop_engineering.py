import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import loop_engineering as le  # noqa: E402


GOOD = {"semantics": 90, "geometry": 88, "silhouette": 86,
        "facade_structure": 84, "color": 83, "framing": 86,
        "materials": 82, "lighting": 82}


def test_weighted_score_is_bounded():
    assert 0 <= le.weighted_score(GOOD) <= 100


def test_missing_dimension_fails_loudly():
    scores = dict(GOOD)
    scores.pop("color")
    try:
        le.weighted_score(scores)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_acceptance_requires_all_gates():
    state = le.new_state("x", target_score=80, min_dimension=70)
    state = le.record_iteration(state, GOOD, defects=[])
    assert state["status"] == "accepted"


def test_critical_defect_blocks_acceptance():
    state = le.new_state("x", target_score=80, min_dimension=70)
    state = le.record_iteration(state, GOOD, defects=[
        {"category": "semantics", "severity": "critical", "impact": 100,
         "fix": "restore missing runway"}
    ])
    assert state["status"] == "running"
    assert le.decision(state)["next_defect"]["category"] == "semantics"


def test_iterations_after_baseline_require_controlled_change():
    state = le.new_state("x")
    low = {key: 50 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, low)
    try:
        le.record_iteration(state, low)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_stagnation_restores_best_checkpoint():
    state = le.new_state("x", min_delta=2, patience=2)
    base = {key: 50 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, base)
    state = le.record_iteration(state, {key: 50.5 for key in base},
                                change={"category": "lighting"})
    state = le.record_iteration(state, {key: 50.6 for key in base},
                                change={"category": "materials"})
    verdict = le.decision(state)
    assert state["status"] == "stopped"
    assert verdict["action"] == "restore_best"


def test_best_iteration_survives_regression():
    state = le.new_state("x")
    base = {key: 40 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, base)
    better = {key: 70 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, better, change={"category": "geometry"})
    worse = {key: 60 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, worse, change={"category": "materials"})
    assert le.best_record(state)["index"] == 1


def test_holdout_is_required_when_configured():
    state = le.new_state("x", holdout_references=["unseen.png"],
                         target_score=80, min_dimension=70)
    state = le.record_iteration(state, GOOD)
    verdict = le.decision(state)
    assert state["status"] == "running"
    assert verdict["action"] == "render_holdout"


def test_holdout_and_gap_must_pass():
    state = le.new_state("x", holdout_references=["unseen.png"],
                         target_score=80, min_dimension=70,
                         max_generalization_gap=5)
    weak_holdout = {key: 70 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, GOOD, validation_scores=weak_holdout)
    verdict = le.decision(state)
    assert state["status"] == "running"
    assert verdict["next_defect"]["category"] == "generalization"


def test_holdout_can_accept_generalized_result():
    state = le.new_state("x", holdout_references=["unseen.png"],
                         target_score=80, min_dimension=70)
    validation = {key: max(78, value - 3) for key, value in GOOD.items()}
    state = le.record_iteration(state, GOOD, validation_scores=validation)
    assert state["status"] == "accepted"


def test_non_camera_change_freezes_camera_signature():
    state = le.new_state("x")
    low = {key: 50 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, low, camera_signature="cam-a")
    try:
        le.record_iteration(state, low, change={"category": "color"},
                            camera_signature="cam-b")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_best_checkpoint_uses_worst_of_tuning_and_holdout():
    state = le.new_state("x", holdout_references=["unseen.png"],
                         target_score=99, min_dimension=0, patience=5)
    tuning = {key: 90 for key in le.DIMENSION_WEIGHTS}
    holdout = {key: 70 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, tuning, validation_scores=holdout,
                                camera_signature="cam")
    tuning_better = {key: 95 for key in le.DIMENSION_WEIGHTS}
    holdout_worse = {key: 60 for key in le.DIMENSION_WEIGHTS}
    state = le.record_iteration(state, tuning_better,
                                validation_scores=holdout_worse,
                                change={"category": "color"},
                                camera_signature="cam")
    assert le.best_record(state)["index"] == 0


def test_state_roundtrip_is_atomic(tmp_path):
    state = le.new_state("x", references=["ref.png"])
    path = le.save_state(state, tmp_path / "loop_state.json")
    assert os.path.isfile(path)
    assert le.load_state(path) == state
