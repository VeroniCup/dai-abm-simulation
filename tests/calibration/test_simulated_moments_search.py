"""Substantive tests for resumable parallel confidence SMM execution."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import numpy as np
import pytest

from dai_sim.calibration.simulated_moments_search import (
    CANDIDATE_SCHEMA,
    REGISTRY_A,
    _cache_root,
    _candidate_paths,
    _process_exists,
    _thread_cap,
    _write_candidate_checkpoint,
    build_search_identity,
    canonical_json_bytes,
    classify_candidate_checkpoints,
    deterministic_npz_bytes,
    load_search_identity,
    payload_sha256,
    rank_candidates,
    search_lock,
    structural_event_flags_pass,
    validate_candidate_checkpoint,
)


def _identity(**changes):
    values = {
        "scientific_checksums": {"a": "1", "b": "2"},
        "event_subset_sha256": "events",
        "candidate_sha256": "candidates",
        "replication_count": 32,
        "registry_id": REGISTRY_A,
        "event_count": 32,
        "candidate_count": 256,
    }
    values.update(changes)
    return build_search_identity(**values)


def _candidate(index: int, *, objective: float = 1.0, **flags):
    result = {
        "candidate_index": index,
        "total_objective": objective,
        "structural_validity": True,
        "objective_validity": True,
        "mcse_pass": True,
        "numerical_bound_pass": True,
    }
    result.update(flags)
    return result


def _checkpoint(index: int = 0, search_id: str = "search"):
    deterministic = {
        "search_id": search_id,
        "schema_version": CANDIDATE_SCHEMA,
        "candidate_index": index,
        "candidate_checksum": "candidate",
        "event_count": 1,
        "replication_count_per_event": 2,
        "event_replication_count": 2,
        "event_result_checksums": [
            {
                "event_id": "calibration__a",
                "replication": replication,
                "result_checksum": f"result-{replication}",
            }
            for replication in range(2)
        ],
        "simulated_core_moments": {},
        "total_objective": 1.0,
    }
    deterministic["result_checksum"] = payload_sha256(deterministic)
    return {**deterministic, "execution_duration_seconds": 0.1}


def test_registered_design_and_search_identity_reproduce() -> None:
    identity, design = load_search_identity()
    assert len(design["event_ids"]) == 32
    assert len(design["structural"]) == 256
    assert identity.registry_id == REGISTRY_A
    assert all(value.startswith("calibration__") for value in design["event_ids"])


def test_search_identity_is_content_addressed_and_path_independent() -> None:
    first = _identity()
    repeated = _identity()
    changed = _identity(scientific_checksums={"a": "changed", "b": "2"})
    assert first == repeated
    assert first.search_id != changed.search_id
    assert "/Users/" not in canonical_json_bytes(first.inputs).decode()


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_subset_sha256", "changed"),
        ("candidate_sha256", "changed"),
        ("replication_count", 64),
        ("event_count", 31),
        ("candidate_count", 255),
    ],
)
def test_each_fixed_identity_field_changes_search_id(field, value) -> None:
    assert _identity().search_id != _identity(**{field: value}).search_id


def test_canonical_json_and_npz_are_byte_deterministic_and_pickle_free() -> None:
    payload = {"b": 2, "a": [1, 2]}
    assert canonical_json_bytes(payload) == canonical_json_bytes(
        {"a": [1, 2], "b": 2}
    )
    arrays = {"z": np.arange(3), "a": np.array([1.5, 2.5])}
    first = deterministic_npz_bytes(arrays)
    second = deterministic_npz_bytes(dict(reversed(list(arrays.items()))))
    assert first == second
    assert b"pickle" not in first


def test_cache_root_is_order_independent_but_checksum_sensitive() -> None:
    base = {
        "event_id": "calibration__a",
        "replication": 0,
        "registry_id": REGISTRY_A,
        "metadata_filename": "a.json",
        "arrays_filename": "a.npz",
        "metadata_size_bytes": 10,
        "arrays_size_bytes": 20,
        "metadata_sha256": "m",
        "arrays_sha256": "a",
        "state_checksum": "s",
        "residual_checksum": "r",
        "schema_version": 1,
    }
    other = {**base, "event_id": "calibration__b"}
    assert _cache_root([base, other]) == _cache_root([other, base])
    assert _cache_root([base, other]) != _cache_root(
        [base, {**other, "arrays_sha256": "changed"}]
    )


def test_candidate_ranking_applies_validity_precedence_and_index_tie_break() -> None:
    candidates = [
        _candidate(3, objective=0.1, mcse_pass=False),
        _candidate(2, objective=0.1, numerical_bound_pass=False),
        _candidate(1, objective=0.2),
        _candidate(0, objective=0.2),
    ]
    ranked, selected = rank_candidates(candidates)
    assert [value["candidate_index"] for value in ranked] == [0, 1, 2, 3]
    assert selected == []


def test_structural_flags_require_desirable_false_diagnostics() -> None:
    flags = {
        "confidence_within_bounds": True,
        "valid_price": True,
        "future_information_used": False,
        "valid_vault_state": True,
        "valid_liquidation_state": True,
        "valid_bad_debt_state": True,
        "duplicated_panic_term": False,
        "event_result_present": True,
    }
    assert structural_event_flags_pass(flags)
    assert not structural_event_flags_pass(
        {**flags, "future_information_used": True}
    )
    assert not structural_event_flags_pass(
        {**flags, "duplicated_panic_term": True}
    )


def test_candidate_ranking_selects_exactly_sixteen_valid_nonfinalists() -> None:
    candidates = [_candidate(index, objective=float(index)) for index in range(20)]
    ranked, selected = rank_candidates(candidates)
    assert len(ranked) == 20
    assert [value["candidate_index"] for value in selected] == list(range(16))


def test_candidate_ranking_refuses_fewer_than_sixteen_valid_candidates() -> None:
    candidates = [_candidate(index) for index in range(15)]
    _, selected = rank_candidates(candidates)
    assert selected == []


def test_atomic_checkpoint_validates_and_is_not_silently_overwritten(tmp_path) -> None:
    payload = _checkpoint()
    arrays = {"replication": np.array([0, 1], dtype="<i8")}
    _write_candidate_checkpoint(tmp_path, payload, arrays)
    observed = validate_candidate_checkpoint(
        tmp_path, 0, expected_search_id="search"
    )
    assert observed["result_checksum"] == payload["result_checksum"]
    before = _candidate_paths(tmp_path, 0)[0].read_bytes()
    _write_candidate_checkpoint(tmp_path, payload, arrays)
    assert _candidate_paths(tmp_path, 0)[0].read_bytes() == before


def test_partial_or_corrupt_checkpoint_is_rejected(tmp_path) -> None:
    json_path, npz_path = _candidate_paths(tmp_path, 0)
    json_path.parent.mkdir(parents=True)
    json_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        validate_candidate_checkpoint(tmp_path, 0, expected_search_id="search")
    npz_path.write_bytes(b"not an npz")
    with pytest.raises((ValueError, KeyError)):
        validate_candidate_checkpoint(tmp_path, 0, expected_search_id="search")


def test_mixed_search_checkpoint_is_rejected(tmp_path) -> None:
    _write_candidate_checkpoint(
        tmp_path,
        _checkpoint(search_id="first"),
        {"replication": np.array([0, 1])},
    )
    with pytest.raises(ValueError, match="another search"):
        validate_candidate_checkpoint(
            tmp_path, 0, expected_search_id="second"
        )


def test_interrupted_checkpoint_set_classifies_resume_work_exactly(tmp_path) -> None:
    _write_candidate_checkpoint(
        tmp_path,
        _checkpoint(index=0),
        {"replication": np.array([0, 1])},
    )
    partial_json, _ = _candidate_paths(tmp_path, 1)
    partial_json.parent.mkdir(parents=True, exist_ok=True)
    partial_json.write_text("{}", encoding="utf-8")
    state = classify_candidate_checkpoints(
        tmp_path,
        expected_search_id="search",
        candidate_count=3,
    )
    assert state == {
        "completed": [0],
        "invalid": [1],
        "pending": [1, 2],
    }


def test_live_lock_rejected_and_stale_lock_requires_explicit_recovery(tmp_path) -> None:
    with search_lock(tmp_path, "test"):
        with pytest.raises(RuntimeError, match="live process"):
            with search_lock(tmp_path, "second"):
                pass
    stale = {
        "search_id": tmp_path.name,
        "process_id": 999_999_999,
        "hostname": __import__("socket").gethostname(),
        "start_time_utc": "2000-01-01T00:00:00+00:00",
        "operation": "old",
    }
    (tmp_path / "search.lock").write_bytes(canonical_json_bytes(stale))
    with pytest.raises(RuntimeError, match="explicit recovery"):
        with search_lock(tmp_path, "new"):
            pass
    with search_lock(tmp_path, "new", recover_stale=True):
        assert (tmp_path / "search.lock").is_file()
    assert not (tmp_path / "search.lock").exists()


def test_worker_thread_cap_is_process_local_environment_policy(monkeypatch) -> None:
    names = (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    _thread_cap()
    assert {os.environ[name] for name in names} == {"1"}


def test_process_liveness_uses_real_process_identifier() -> None:
    assert _process_exists(os.getpid())
    assert not _process_exists(-1)


def test_search_source_has_no_random_hash_pickle_or_final_validation_execution() -> None:
    source = Path(
        "src/dai_sim/calibration/simulated_moments_search.py"
    ).read_text(encoding="utf-8")
    assert "hash(" not in source
    assert "pickle" in source  # Explicit prohibition/documentation is present.
    assert "allow_pickle=False" in source
    assert "registry_b_used" in source and "False" in source
    assert "runtime_adopted" in source
