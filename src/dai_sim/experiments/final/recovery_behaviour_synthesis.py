"""Registered H4 recovery and behavioural-stabilisation evidence synthesis.

This owner validates and organises committed compact evidence.  It deliberately
contains no model runner, checkpoint reader, calibration routine, statistical
pooling or scenario-selection path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file


SYNTHESIS_PARENT_COMMIT = "e688a0cf5b2f90c244a08dc58afda040ba476808"
MASTER_PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
CONFIDENCE_REGISTRY_IDENTITY = (
    "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
)
PARTIAL_IDENTIFICATION_IDENTITY = (
    "39d01a3dfa07053dbe31c8189d88ab5f5fdfaa8003d3ddb28606179fd8413e6d"
)
STRUCTURAL_FACTORIAL_IDENTITY = (
    "4558b97de3c092b8cec70b9117407333527f517559b7126fa0428c5e9059ad00"
)
UNBOUNDED_RECOVERY_IDENTITY = (
    "68afcef1166bb6b13813d0e481ce7bddff7605c0ac7326bf8b9d1400eacff20b"
)
CONSTRAINED_RECOVERY_IDENTITY = (
    "6cfbd19384fc95fe8b06de74704d0b2a76638722b100242e0bc87a9ee3e05acc"
)
EXPERIMENT_IDENTITIES = {
    "experiment_a": "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb",
    "experiment_b": "e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83",
    "experiment_c": "cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b",
    "experiment_d": "b324c31be7ef6dd7f61e504709b2086b0e88ce181c177f25dcaad182095c17e3",
    "experiment_e": "67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8",
}

EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "data/provenance/experiments/final/recovery_behaviour_synthesis"
)
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
COMPACT_FILENAMES = (
    "recovery_behaviour_synthesis_specification.json",
    "recovery_behaviour_synthesis_sources.csv",
    "recovery_behaviour_synthesis_evidence_matrix.csv",
    "recovery_behaviour_synthesis_claim_crosswalk.csv",
    "recovery_behaviour_synthesis_decision.json",
    "recovery_behaviour_synthesis_reproducibility.json",
)
SOURCE_COLUMNS = (
    "source_order",
    "source_identifier",
    "source_type",
    "path",
    "experiment_or_calibration_identity",
    "specification_checksum",
    "decision_checksum",
    "reproducibility_checksum",
    "supporting_checksums",
    "registered_classification",
    "evidence_status",
    "design_population",
    "treatment_dimensions",
    "simulation_count",
    "peg_effects_operational",
    "backlog_operational",
    "bad_debt_operational",
    "confidence_status",
    "principal_limitation",
    "inclusion_decision",
)
MATRIX_COLUMNS = (
    "finding_order",
    "component",
    "source_identifier",
    "tier",
    "registered_finding",
    "evidence_direction",
    "quantitative_context",
    "limitation",
)
CLAIM_COLUMNS = (
    "claim_order",
    "claim_identifier",
    "claim_text",
    "supporting_source_ids",
    "limiting_source_ids",
    "source_decision_labels",
    "source_design_differences",
    "evidence_direction",
    "evidential_status",
    "dissertation_safe_wording",
    "prohibited_overstatement",
)


@dataclass(frozen=True)
class SourceDefinition:
    identifier: str
    source_type: str
    identity: str
    specification_path: str
    specification_sha256: str
    decision_path: str
    decision_sha256: str
    reproducibility_path: str
    reproducibility_sha256: str
    registered_classification: str
    evidence_status: str
    design_population: str
    treatment_dimensions: str
    simulation_count: int | None
    peg_effects_operational: str
    backlog_operational: str
    bad_debt_operational: str
    confidence_status: str
    principal_limitation: str
    supporting_paths: tuple[tuple[str, str], ...] = ()


SOURCE_DEFINITIONS = (
    SourceDefinition(
        "final_programme",
        "programme_boundary",
        MASTER_PROGRAMME_IDENTITY,
        "data/provenance/experiments/final_programme/final_programme_specification.json",
        "a16302160fc1124d0e61a9157bb596cf80b376d0a07dfd9800c985fb87f84419",
        "data/provenance/experiments/final_programme/final_programme_decision.json",
        "96938611e4ca5fbe169fdcd4c1c9e2b49482a10851edba1a3f319c34d0cfa1c6",
        "data/provenance/experiments/final_programme/final_programme_reproducibility.json",
        "f2044e38a55cdd59e6e010d80c9360492d4d343e589311d64422154e0516dc34",
        "pre_registered_final_programme",
        "included_boundary_only",
        "five core experiments",
        "43 frozen cells; H1-H4",
        5504,
        "varies_by_experiment",
        "varies_by_experiment",
        "varies_by_experiment",
        "stage1_only_default",
        "The historical programme decision predates execution completion; individual frozen decisions own results.",
    ),
    SourceDefinition(
        "confidence_partial_identification",
        "calibration_closure",
        PARTIAL_IDENTIFICATION_IDENTITY,
        "data/provenance/calibration/confidence/partial_identification_specification.json",
        "347e47bc4c36bf7804320f823abf728096256fab1bc2706fefd0f2a66552f82c",
        "data/provenance/calibration/confidence/partial_identification_set.json",
        "a42ae42f3cb55ac215e3d76d373d8be1c4f45656f32669d69a5e98bfa075e7ae",
        "data/provenance/calibration/confidence/partial_identification_reproducibility.json",
        "3a8533aecc0bb5eb67aca1c00607d58e4f603902a767925b1983917badb452da",
        "model_evidence_incompatibility",
        "included",
        "74 historical stress events",
        "256 bounded candidate vectors",
        None,
        "operational_for_calibration",
        "operational_for_calibration",
        "diagnostic_only",
        "no_admissible_vector",
        "Finite candidate grid; not an asymptotic confidence region.",
    ),
    SourceDefinition(
        "confidence_structural_factorial",
        "calibration_closure",
        STRUCTURAL_FACTORIAL_IDENTITY,
        "data/provenance/calibration/confidence/structural_factorial_specification.json",
        "a6c7c809a7d9e1a7c5ad3c82f63cdee90936fd5a1eadbf725b0bbc86a82369da",
        "data/provenance/calibration/confidence/structural_factorial_decision.json",
        "f9ac6758dcff3597f2541c3ac68f28cb23fe66c1072b025fabf41b141443f8b9",
        "data/provenance/calibration/confidence/structural_factorial_reproducibility.json",
        "ba1bc543cb935caca81fb27134cc665eca40be2414c7968fa9853d336b3b3988",
        "factorial_interactions_reveal_tradeoffs",
        "included",
        "registered confidence calibration events",
        "2^3 structural factorial",
        None,
        "operational_for_calibration",
        "operational_for_calibration",
        "diagnostic_only",
        "calibration_rescue_closed",
        "Structural alternatives improve some constraints but identify no compatible cell.",
    ),
    SourceDefinition(
        "confidence_scenarios",
        "transparent_scenario_registry",
        CONFIDENCE_REGISTRY_IDENTITY,
        "data/provenance/experiments/confidence/confidence_scenario_specification.json",
        "d9f3de40aa1d9852c3fb1a51edc172ebf7eafc802a3b4547b003213dc7843adc",
        "data/provenance/experiments/confidence/confidence_scenario_decision.json",
        "b66124cffea3177f5343a91e3529afde29bdf143e189ec358ddf8c5ee198aa4d",
        "data/provenance/experiments/confidence/confidence_scenario_reproducibility.json",
        "b5a2f84babe6ed11bad9fa5200e8b003582023c8766ac22ad4a2c123b9b878ef",
        "transparent_scenario_assumptions",
        "included",
        "scenario mechanism",
        "stage1_only; resilient; central; fragile",
        0,
        "scenario_dependent",
        "gated_by_unresolved_stress",
        "gated_by_active_bad_debt",
        "not_calibrated_not_ranked",
        "Active scenarios are transparent assumptions and do not represent truth.",
        (("data/provenance/experiments/confidence/confidence_scenario_registry.csv", CONFIDENCE_REGISTRY_IDENTITY),),
    ),
    SourceDefinition(
        "stage1_dai_mechanism",
        "accepted_mechanism",
        "stage1-market-and-recovery-gate",
        "data/provenance/calibration/confidence/recovery_gate_specification.json",
        "e0208285c0f532b81b16ded9d2db74091b0fa34953b968cccc39378a8eb87017",
        "data/provenance/calibration/confidence/stage1_market_estimates.json",
        "d86625e268c7e8b8abcb6d37e48f87c3c01578c8a3c09024a57da93978614547",
        "data/provenance/calibration/confidence/stage1_residual_summary.json",
        "98299918d452695b96f639aaae4c2344c189a3351bd55f1d86a2441d5bcded0e",
        "accepted_stage1_market_response",
        "included",
        "ordinary historical DAI market hours",
        "asymmetric peg response plus 24-hour residual blocks",
        0,
        "operational",
        "no_direct_recovery_path_term",
        "not_a_direct_state_variable",
        "persistent_confidence_inactive",
        "No direct collateral-recovery-path term exists in Stage 1.",
    ),
    SourceDefinition(
        "unbounded_eth_recovery",
        "registered_mechanism_experiment",
        UNBOUNDED_RECOVERY_IDENTITY,
        "data/provenance/experiments/recovery/eth_recovery_specification.json",
        "f8a747e4e53cdebece4d2fe826836df5b6ee63dc81f561644386720239aa552b",
        "data/provenance/experiments/recovery/eth_recovery_decision.json",
        "2124186a748617044664942d68d56b740df3b112d84b6889f44c78b80727b59f",
        "data/provenance/experiments/recovery/eth_recovery_reproducibility.json",
        "ab9767c80c31cb664e29fb68440a388edc3c565f7be2a64fa69ec492147d56f8",
        "no_clear_recovery_path_effect",
        "conditional_channel_absence",
        "100 legacy ETH vaults",
        "four recovery paths x four confidence scenarios",
        2048,
        "operational_by_confidence_scenario",
        "resolved_immediately",
        "resolved_immediately",
        "transparent_scenarios",
        "Immediate full-close execution leaves no unresolved vault for rebound to rescue.",
        (
            ("data/provenance/experiments/recovery/eth_recovery_cell_summary.csv", "4957e93d0b0857aefdfd3bb33853874d9f2e4fd2c6a4e2c1f4bacd2b3afce43e"),
            ("data/provenance/experiments/recovery/eth_recovery_contrasts.csv", "7f38af47d134cc78365715602aa2755f6bd34b0109e810149213f6bd444d6cab"),
            ("data/provenance/experiments/recovery/eth_recovery_interactions.csv", "f0482c8ca8de3548120c5f13c7e3f8ffc92251871af026d1cc18c311c0d96378"),
        ),
    ),
    SourceDefinition(
        "constrained_eth_recovery",
        "registered_mechanism_experiment",
        CONSTRAINED_RECOVERY_IDENTITY,
        "data/provenance/experiments/constrained_recovery/constrained_recovery_specification.json",
        "4016d213eed7cde1262af2cb7cc2318bcb27efd282f35669cdf8f8cb12d0ab70",
        "data/provenance/experiments/constrained_recovery/constrained_recovery_decision.json",
        "b366f83fe8d217555aa7f56c8f924ad69d55e15be6f0b0a9713be364121103f6",
        "data/provenance/experiments/constrained_recovery/constrained_recovery_reproducibility.json",
        "4acb1fb01a2de68c695e0ef54e21323077fadbb76b8d74d452ad0e12851adc05",
        "recovery_effect_capacity_dependent",
        "included",
        "500 empirical-profile ETH vaults",
        "two recovery paths x capacities 14/26/45 x four confidence scenarios",
        3072,
        "scenario_dependent",
        "operational",
        "degenerate_under_full_close",
        "transparent_scenarios",
        "ETH-only controlled paths; capacity is partially identified.",
        (
            ("data/provenance/experiments/constrained_recovery/constrained_recovery_recovery_contrasts.csv", "119a905a058d414bd063dc9fe95c620eba8892f34c88a815e0a3f52c410e4bc4"),
            ("data/provenance/experiments/constrained_recovery/constrained_recovery_capacity_contrasts.csv", "48d540ec015495d77e5e8b6af85ed29b49727b0eebc5ccb5247fd05b4e1ebb90"),
            ("data/provenance/experiments/constrained_recovery/constrained_recovery_vault_rescue.csv", "7c8ef81f874a41451b111087d4890c04ae5cd525e0d9d236c31cfd4c2ac72c06"),
        ),
    ),
    SourceDefinition(
        "experiment_a",
        "registered_final_experiment",
        EXPERIMENT_IDENTITIES["experiment_a"],
        "data/provenance/experiments/final/idiosyncratic_diversification/idiosyncratic_diversification_specification.json",
        "e6da0af839c53ddffb6eeaea596174d26499afeb55ca0d1910be49c679cd740d",
        "data/provenance/experiments/final/idiosyncratic_diversification/idiosyncratic_diversification_decision.json",
        "cf720d855adc62c5270042f9d2cb85338ef14d7d80a2aa8cb70f7d0dc7b9f614",
        "data/provenance/experiments/final/idiosyncratic_diversification/idiosyncratic_diversification_reproducibility.json",
        "d04a955c843b831ae95e9b4a9326b1cb65211041a12121b3e74b98922f562fe7",
        "H3_idiosyncratic_diversification_supported",
        "included_cross_programme_relation",
        "registered multi-collateral portfolios",
        "idiosyncratic diversification",
        1024,
        "operational_unchanged",
        "operational",
        "limited_by_full_close",
        "stage1_only",
        "Not a recovery-path experiment.",
    ),
    SourceDefinition(
        "experiment_b",
        "registered_final_experiment",
        EXPERIMENT_IDENTITIES["experiment_b"],
        "data/provenance/experiments/final/correlated_stress/correlated_stress_specification.json",
        "89f38e38b26426800c14f5b31a32e25aff783cf5951692adc4af0f92e870c680",
        "data/provenance/experiments/final/correlated_stress/correlated_stress_decision.json",
        "dc669354d036060ce9477fdca4a863877af3a88ead73a9130d804c1a66b3add6",
        "data/provenance/experiments/final/correlated_stress/correlated_stress_reproducibility.json",
        "94f07e9f18b724ab9dd595c9fc8684d0f76cf29007045b4f7d8fc4d03d8fb5de",
        "H3_correlation_deterioration_supported",
        "included_cross_programme_relation",
        "registered multi-collateral portfolios",
        "bundled correlated-stress contrast",
        1024,
        "operational_unchanged",
        "operational",
        "limited_by_full_close",
        "stage1_only",
        "Bundled stress comparison is not a pure correlation effect.",
    ),
    SourceDefinition(
        "experiment_c",
        "registered_final_experiment",
        EXPERIMENT_IDENTITIES["experiment_c"],
        "data/provenance/experiments/final/stable_collateral_tradeoff/stable_collateral_tradeoff_specification.json",
        "e5d9469e415c6fdf91e5514281b3c3751a34b81f31c96c60e2923ca80c0272dd",
        "data/provenance/experiments/final/stable_collateral_tradeoff/stable_collateral_tradeoff_decision.json",
        "9aa54888c6592859944f7ed5fa3e3b99fecaf29bfcf5518b566d8cdb24489cef",
        "data/provenance/experiments/final/stable_collateral_tradeoff/stable_collateral_tradeoff_reproducibility.json",
        "185faa58c4efe3940532544d9a4acbbaf4ab0cc43fb1273bc24425735f4fa1aa",
        "H3_stable_tradeoff_partially_supported",
        "included_cross_programme_relation",
        "registered multi-collateral portfolios",
        "stable-share trade-off",
        1536,
        "operational_unchanged",
        "operational",
        "limited_by_full_close",
        "stage1_only",
        "Stable collateral is a counterfactual proxy with no material depeg-cost gradient.",
    ),
    SourceDefinition(
        "experiment_d",
        "registered_final_experiment",
        EXPERIMENT_IDENTITIES["experiment_d"],
        "data/provenance/experiments/final/shared_keeper_capacity/shared_keeper_capacity_specification.json",
        "10d7bd2062d6d52b03941c90558dded45954fb8ffbf1a501dc0dd05e4f2b28e0",
        "data/provenance/experiments/final/shared_keeper_capacity/shared_keeper_capacity_decision.json",
        "ca6927dfadb88d22c4e7d8e5cdede644b3486ccddf53c1f4a6b690e179ba51f2",
        "data/provenance/experiments/final/shared_keeper_capacity/shared_keeper_capacity_reproducibility.json",
        "a62b7e301f1a91859835de3d4679a2a3eec5bb78d0eaee02c1a43fccfa130ecc",
        "H1_no_clear_shared_capacity_effect",
        "included_context_limit",
        "three registered multi-collateral anchors",
        "capacity 14/26/45",
        1152,
        "operational_unchanged",
        "mixed_or_non_binding",
        "degenerate",
        "stage1_only",
        "Population, shocks and treatment question differ from constrained ETH recovery.",
    ),
    SourceDefinition(
        "experiment_e",
        "registered_final_experiment",
        EXPERIMENT_IDENTITIES["experiment_e"],
        "data/provenance/experiments/final/oracle_delay/oracle_delay_specification.json",
        "acce1aafeabcc8ccfd63b4ca353e9839c1cc11373043432a47c31389eb8f0537",
        "data/provenance/experiments/final/oracle_delay/oracle_delay_decision.json",
        "a9745d751f77b07ec3d44eb1c54449ca6a15f71340ab23af9b9e1ac750b62776",
        "data/provenance/experiments/final/oracle_delay/oracle_delay_reproducibility.json",
        "5056febd30b658a2089daa2aa15f843fb9eef493e0b2d6b0e0ea30926e2ebc96",
        "H2_oracle_delay_partially_supported",
        "included_cross_programme_relation",
        "two registered multi-collateral anchors",
        "transparent delay 0/1/2 hours",
        768,
        "operational_unchanged",
        "operational_timing",
        "degenerate",
        "stage1_only",
        "Delay values are transparent sensitivities, not historical estimates.",
    ),
)


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _pretty_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _csv_bytes(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return output.getvalue().encode("utf-8")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _load_json(relative: str) -> dict[str, Any]:
    return json.loads((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))


def _is_committed_source(relative: str) -> bool:
    result = subprocess.run(
        ("git", "cat-file", "-e", f"{SYNTHESIS_PARENT_COMMIT}:{relative}"),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _validate_file(relative: str, expected_sha256: str) -> None:
    path = REPOSITORY_ROOT / relative
    if not path.is_file():
        raise ValueError(f"Synthesis source is missing: {relative}.")
    if not _is_committed_source(relative):
        raise ValueError(f"Synthesis source is not committed at the boundary: {relative}.")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"Synthesis source checksum differs: {relative}.")


def _validate_source_files(source: SourceDefinition) -> None:
    for relative, digest in (
        (source.specification_path, source.specification_sha256),
        (source.decision_path, source.decision_sha256),
        (source.reproducibility_path, source.reproducibility_sha256),
        *source.supporting_paths,
    ):
        _validate_file(relative, digest)


def _validate_registered_decisions() -> None:
    partial = _load_json(SOURCE_DEFINITIONS[1].decision_path)
    factorial = _load_json(SOURCE_DEFINITIONS[2].decision_path)
    confidence = _load_json(SOURCE_DEFINITIONS[3].decision_path)
    stage1 = _load_json(SOURCE_DEFINITIONS[4].decision_path)
    residual = _load_json(SOURCE_DEFINITIONS[4].reproducibility_path)
    unbounded = _load_json(SOURCE_DEFINITIONS[5].decision_path)
    unbounded_specification = _load_json(SOURCE_DEFINITIONS[5].specification_path)
    unbounded_reproducibility = _load_json(
        SOURCE_DEFINITIONS[5].reproducibility_path
    )
    constrained = _load_json(SOURCE_DEFINITIONS[6].decision_path)
    constrained_specification = _load_json(SOURCE_DEFINITIONS[6].specification_path)
    constrained_reproducibility = _load_json(
        SOURCE_DEFINITIONS[6].reproducibility_path
    )
    if (
        partial.get("set_id") != PARTIAL_IDENTIFICATION_IDENTITY
        or partial.get("counts", {}).get("inner_admissible") != 0
        or partial.get("counts", {}).get("outer_admissible") != 0
        or factorial.get("final_classification")
        != "factorial_interactions_reveal_tradeoffs"
        or factorial.get("selected_cell") is not None
        or factorial.get("selected_parameter") is not None
        or confidence.get("scenario_count") != 4
        or confidence.get("scenario_order")
        != [
            "stage1_only",
            "confidence_resilient",
            "confidence_central",
            "confidence_fragile",
        ]
        or confidence.get("scenario_ranked") is not False
        or confidence.get("scenario_selected") is not None
        or confidence.get("no_scenario_represents_truth") is not True
        or confidence.get("production_baseline") != "stage1_only"
        or stage1["below_peg_response"]["point_estimate"] != 0.19938097532295382
        or stage1["above_peg_response"]["point_estimate"] != 0.10513116022712267
        or residual.get("representation") != "centred empirical 24-hour moving blocks"
        or residual.get("eligible_hourly_residual_count") != 28859
        or unbounded.get("overall_classification") != "no_clear_recovery_path_effect"
        or len(unbounded_specification.get("path_definitions", ())) != 4
        or len(unbounded_specification.get("cell_order", ())) != 16
        or unbounded_specification.get("replications_per_cell") != 128
        or unbounded_reproducibility.get("expected_runs") != 2048
        or unbounded_reproducibility.get("completed_runs") != 2048
        or any(unbounded_reproducibility.get("numerical_failure_counts", {}).values())
        or constrained.get("H5a") != "supported"
        or constrained.get("H5b") != "not_supported"
        or constrained.get("H5c") != "present"
        or constrained.get("H5d") != "present"
        or constrained.get("capacity_mechanism_classification")
        != "higher_capacity_reduces_backlog"
        or constrained.get("overall_classification")
        != "recovery_effect_capacity_dependent"
        or constrained_specification.get("integrated_profile", {}).get("identifier")
        != "empirical_integrated_eth"
        or constrained_specification.get("integrated_profile", {}).get("vault_count")
        != 500
        or constrained_specification.get("integrated_profile", {}).get(
            "total_debt_dai"
        )
        != 2_500_000.0
        or len(constrained_specification.get("cell_order", ())) != 24
        or constrained_specification.get("replications_per_cell") != 128
        or constrained_specification.get("capacity", {}).get("profiles")
        != {
            "shared_keeper_capacity_central": 26,
            "shared_keeper_capacity_high": 45,
            "shared_keeper_capacity_low": 14,
        }
        or constrained_specification.get("confidence", {}).get("primary")
        != "stage1_only"
        or constrained_specification.get("confidence", {}).get("ranked") is not False
        or constrained_specification.get("confidence", {}).get("selected") is not None
        or constrained_reproducibility.get("expected_simulations") != 3072
        or constrained_reproducibility.get("completed_simulations") != 3072
        or constrained_reproducibility.get("numerical_failures") != 0
        or constrained_reproducibility.get("seed_registry_sha256")
        != "fcd4b17789da5684bbbcbc3f3fcbf7825328bf593c0cf06bb4b40ffd75948b5c"
    ):
        raise ValueError("A protected confidence or recovery decision differs.")

    expected = {
        "experiment_a": (
            "overall_h3_classification",
            "H3_idiosyncratic_diversification_supported",
            "solvency_improves_peg_unchanged",
        ),
        "experiment_b": (
            "overall_h3_classification",
            "H3_correlation_deterioration_supported",
            "solvency_deteriorates_peg_unchanged",
        ),
        "experiment_c": (
            "overall_h3_classification",
            "H3_stable_tradeoff_partially_supported",
            "solvency_improves_peg_unchanged",
        ),
        "experiment_d": (
            "overall_h1_classification",
            "H1_no_clear_shared_capacity_effect",
            "neither_materially_changes",
        ),
        "experiment_e": (
            "overall_h2_classification",
            "H2_oracle_delay_partially_supported",
            "solvency_deteriorates_peg_unchanged",
        ),
    }
    for source in SOURCE_DEFINITIONS[7:]:
        decision = _load_json(source.decision_path)
        key, classification, relation = expected[source.identifier]
        if (
            decision.get("experiment_identity") != source.identity
            or decision.get(key) != classification
            or decision.get("peg_solvency_relationship") != relation
        ):
            raise ValueError(f"Protected decision differs: {source.identifier}.")
    experiment_d = _load_json(SOURCE_DEFINITIONS[10].decision_path)
    experiment_e = _load_json(SOURCE_DEFINITIONS[11].decision_path)
    if (
        experiment_d["D1"]["classification"] != "not_supported"
        or experiment_d["D2"]["classification"]
        != "shared_capacity_transmission_mixed"
        or experiment_d["D3"]["classification"] != "peg_unchanged"
        or experiment_e["E1"]["classification"] != "supported"
        or experiment_e["E2"]["classification"] != "partially_supported"
        or experiment_e["E3"]["classification"] != "peg_unchanged"
    ):
        raise ValueError("Protected D or E component decision differs.")


def _lookup_csv(relative: str, **criteria: str) -> dict[str, str]:
    with (REPOSITORY_ROOT / relative).open(encoding="utf-8", newline="") as handle:
        matches = [
            row
            for row in csv.DictReader(handle)
            if all(row.get(key) == value for key, value in criteria.items())
        ]
    if len(matches) != 1:
        raise ValueError(f"Expected one registered summary row, found {len(matches)}.")
    return matches[0]


def validate_quantitative_context() -> dict[str, Any]:
    contrast_path = SOURCE_DEFINITIONS[6].supporting_paths[0][0]
    rescue_path = SOURCE_DEFINITIONS[6].supporting_paths[2][0]
    expected = {
        "14": (7213.86534133, -203359.78925, 27.6484375),
        "26": (5579.37531173, -140912.013976, 20.328125),
        "45": (5237.86042989, -130802.694697, 17.921875),
    }
    observed: dict[str, Any] = {}
    for capacity, (avoided, backlog, rescued) in expected.items():
        avoided_row = _lookup_csv(
            rescue_path,
            record_type="paired_recovery",
            recovery_path="full_week - persistent_trough",
            capacity=capacity,
            confidence_scenario="stage1_only",
            metric="paired_avoided_debt_dai",
        )
        backlog_row = _lookup_csv(
            contrast_path,
            capacity=capacity,
            confidence_scenario="stage1_only",
            contrast="full_week - persistent_trough",
            metric="backlog_area_dai_hours",
        )
        rescued_row = _lookup_csv(
            rescue_path,
            record_type="within_cell",
            recovery_path="full_week",
            capacity=capacity,
            confidence_scenario="stage1_only",
            metric="recovered_before_execution",
        )
        if (
            float(avoided_row["mean"]) != avoided
            or float(backlog_row["mean"]) != backlog
            or float(backlog_row["ci95_lower"]) >= 0
            or float(backlog_row["ci95_upper"]) >= 0
            or float(rescued_row["mean"]) != rescued
        ):
            raise ValueError("Constrained-recovery quantitative evidence differs.")
        for metric in ("below_peg_burden", "restricted_mean_recovery_time"):
            row = _lookup_csv(
                contrast_path,
                capacity=capacity,
                confidence_scenario="stage1_only",
                contrast="full_week - persistent_trough",
                metric=metric,
            )
            if any(float(row[key]) != 0.0 for key in ("mean", "ci95_lower", "ci95_upper")):
                raise ValueError("Stage 1 recovery-path peg contrast differs.")
        resilient = _lookup_csv(
            contrast_path,
            capacity=capacity,
            confidence_scenario="confidence_resilient",
            contrast="full_week - persistent_trough",
            metric="below_peg_burden",
        )
        if not float(resilient["mean"]) < 0:
            raise ValueError("Resilient confidence recovery contrast differs.")
        for scenario in ("confidence_central", "confidence_fragile"):
            row = _lookup_csv(
                contrast_path,
                capacity=capacity,
                confidence_scenario=scenario,
                contrast="full_week - persistent_trough",
                metric="below_peg_burden",
            )
            if float(row["mean"]) != 0.0:
                raise ValueError("Registered confidence scenario contrast differs.")
        observed[capacity] = {
            "avoided_debt_dai": avoided,
            "backlog_area_change_dai_hours": backlog,
            "recovered_before_execution": rescued,
        }
    return observed


def build_source_registry() -> list[dict[str, Any]]:
    if len({source.identifier for source in SOURCE_DEFINITIONS}) != len(SOURCE_DEFINITIONS):
        raise ValueError("Synthesis source definitions contain duplicates.")
    for source in SOURCE_DEFINITIONS:
        _validate_source_files(source)
    _validate_registered_decisions()
    validate_quantitative_context()
    return [
        {
            "source_order": order,
            "source_identifier": source.identifier,
            "source_type": source.source_type,
            "path": source.decision_path,
            "experiment_or_calibration_identity": source.identity,
            "specification_checksum": source.specification_sha256,
            "decision_checksum": source.decision_sha256,
            "reproducibility_checksum": source.reproducibility_sha256,
            "supporting_checksums": ";".join(
                f"{path}:{digest}" for path, digest in source.supporting_paths
            ),
            "registered_classification": source.registered_classification,
            "evidence_status": source.evidence_status,
            "design_population": source.design_population,
            "treatment_dimensions": source.treatment_dimensions,
            "simulation_count": "" if source.simulation_count is None else source.simulation_count,
            "peg_effects_operational": source.peg_effects_operational,
            "backlog_operational": source.backlog_operational,
            "bad_debt_operational": source.bad_debt_operational,
            "confidence_status": source.confidence_status,
            "principal_limitation": source.principal_limitation,
            "inclusion_decision": "included",
        }
        for order, source in enumerate(SOURCE_DEFINITIONS, start=1)
    ]


def validate_source_registry(rows: Sequence[Mapping[str, Any]]) -> None:
    identifiers = [str(row["source_identifier"]) for row in rows]
    if identifiers != [source.identifier for source in SOURCE_DEFINITIONS]:
        raise ValueError("Synthesis source order or population differs.")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Synthesis source registry contains duplicates.")
    if any("held_out" in identifier or "usdc" in identifier.lower() for identifier in identifiers):
        raise ValueError("Excluded validation evidence entered the synthesis.")


def classify_s1(*, immediate_channel: bool, constrained_channel: bool, valid: bool = True) -> str:
    if not valid:
        return "invalid"
    if not immediate_channel and constrained_channel:
        return "conditionally_operational"
    if immediate_channel and constrained_channel:
        return "generally_operational"
    if not immediate_channel and not constrained_channel:
        return "not_operational"
    return "inconsistent"


def classify_s2(
    *, interaction_clear: bool, capacity_effect_clear: bool, operational_count: int
) -> str:
    if operational_count <= 0:
        return "not_supported"
    if interaction_clear and capacity_effect_clear:
        return "supported"
    if interaction_clear or capacity_effect_clear:
        return "partially_supported"
    return "not_supported"


def s2_generalisability(*, final_capacity_clear: bool) -> str:
    return "general" if final_capacity_clear else "context_specific"


def classify_s3(
    *, calibrated_vector: bool, active_effects: Sequence[bool], active_directions: Sequence[int]
) -> str:
    if calibrated_vector:
        return "empirically_identified"
    if not any(active_effects):
        return "not_operational"
    non_zero = [direction for active, direction in zip(active_effects, active_directions, strict=True) if active]
    if non_zero and len(set(non_zero)) == 1 and len(non_zero) == len(active_effects):
        return "robustly_supported"
    return "scenario_dependent_not_identified"


def classify_s4(
    *,
    backlog_operational: bool,
    mechanism_condition: bool,
    isolated_peg_gate: bool,
    peg_effect_assessed: bool,
) -> str:
    if not backlog_operational:
        return "not_operational"
    if isolated_peg_gate:
        return "peg_gate_effect_supported"
    if mechanism_condition and peg_effect_assessed:
        return "mechanism_present_peg_effect_unresolved"
    if mechanism_condition:
        return "mechanism_condition_supported"
    return "not_operational"


def classify_s5(*, constrained_decoupling: bool, final_decoupling_count: int, contradiction_count: int) -> str:
    if contradiction_count:
        return "mixed"
    if constrained_decoupling and final_decoupling_count >= 3:
        return "strongly_supported"
    if constrained_decoupling and final_decoupling_count >= 1:
        return "supported"
    return "not_supported"


def classify_h4(*, s1: str, s2: str, s2_qualifier: str, s3: str, s4: str, s5: str, valid: bool = True) -> str:
    if not valid:
        return "H4_recovery_synthesis_invalid"
    if (
        s1 == "generally_operational"
        and s2 == "supported"
        and s2_qualifier == "general"
        and s3 in {"robustly_supported", "empirically_identified"}
        and s4 == "peg_gate_effect_supported"
        and s5 in {"supported", "strongly_supported"}
    ):
        return "H4_joint_recovery_supported"
    if (
        s1 == "conditionally_operational"
        and s2 == "supported"
        and s2_qualifier == "context_specific"
        and s3 == "scenario_dependent_not_identified"
        and s4 in {"mechanism_condition_supported", "mechanism_present_peg_effect_unresolved"}
        and s5 in {"supported", "strongly_supported"}
    ):
        return "H4_recovery_conditionally_supported"
    if s1 in {"conditionally_operational", "generally_operational"} and s2 in {"supported", "partially_supported"} and s3 == "not_operational":
        return "H4_solvency_recovery_without_peg_recovery"
    if s1 in {"conditionally_operational", "generally_operational"} and s2 == "supported":
        return "H4_behavioural_recovery_unresolved"
    return "H4_no_clear_recovery_evidence"


def build_evidence_matrix() -> list[dict[str, Any]]:
    rows = [
        ("S1_recovery_channel", "unbounded_eth_recovery", 1, "no_clear_recovery_path_effect", "conditional_null", "Immediate full-close execution resolves nearly all unsafe positions before rebound.", "No unresolved inventory remains to rescue."),
        ("S1_recovery_channel", "constrained_eth_recovery", 1, "H5a supported", "supports_channel", "Full-week recovery avoids liquidation debt at all three capacities.", "Controlled ETH-only setting."),
        ("S2_execution_conditioning", "constrained_eth_recovery", 1, "H5c present; higher_capacity_reduces_backlog", "supports_interaction", "Avoided debt and rescue counts are largest at capacity 14; backlog falls as capacity rises.", "Capacity values are partially identified."),
        ("S2_execution_conditioning", "experiment_d", 1, "H1_no_clear_shared_capacity_effect", "limits_generalisability", "Final multi-collateral capacity transmission is mixed or non-binding.", "Different populations, shocks and treatment question."),
        ("S3_behavioural_stabilisation", "confidence_partial_identification", 1, "zero admissible vectors", "not_identified", "All 256 bounded candidates are rejected.", "Finite candidate grid."),
        ("S3_behavioural_stabilisation", "confidence_structural_factorial", 1, "factorial_interactions_reveal_tradeoffs", "not_identified", "No structural-factorial cell is admissible.", "Mechanism diagnosis, not parameter estimation."),
        ("S3_behavioural_stabilisation", "confidence_scenarios", 1, "transparent scenario assumptions", "scenario_boundary", "Four fixed scenarios; no ranking or selection.", "Active values are not estimates."),
        ("S3_behavioural_stabilisation", "unbounded_eth_recovery", 2, "confidence controls registered peg recovery", "scenario_dependent", "Active confidence assumptions alter the DAI recovery path.", "Cannot establish which scenario is empirically correct."),
        ("S3_behavioural_stabilisation", "constrained_eth_recovery", 2, "H5b not supported; scenario contrasts differ", "scenario_dependent", "Resilient recovery contrasts are negative while central and fragile primary contrasts are zero.", "Scenario-conditional, not a ranking."),
        ("S4_backlog_gate", "constrained_eth_recovery", 1, "H5a and H5c supported", "supports_mechanism_condition", "Unresolved positions create a recovery window and recovery reduces backlog.", "No clean isolated backlog-to-peg contrast."),
        ("S4_backlog_gate", "stage1_dai_mechanism", 1, "operational recovery gate", "supports_mechanism_condition", "Behavioural recovery is gated by unresolved tab, active bad debt and price stability.", "Gate coefficient is not fitted."),
        ("S4_backlog_gate", "experiment_e", 1, "E2 partially supported", "timing_context", "Delay changes recognition and interim backlog while peg outcomes remain unchanged.", "Capacity never binds; bad debt is degenerate."),
        ("S5_solvency_peg_decoupling", "constrained_eth_recovery", 1, "H5a supported; H5b not supported; H5d present", "supports_decoupling", "Recovery improves solvency without changing Stage 1 primary peg outcomes.", "Persistent-confidence results remain scenario-defined."),
        ("S5_solvency_peg_decoupling", "experiment_a", 1, "solvency_improves_peg_unchanged", "supports_decoupling", "Diversification improves solvency with unchanged peg outcomes.", "Not a recovery-path experiment."),
        ("S5_solvency_peg_decoupling", "experiment_b", 1, "solvency_deteriorates_peg_unchanged", "supports_decoupling", "Bundled correlated stress worsens solvency with unchanged peg outcomes.", "Not a pure correlation contrast."),
        ("S5_solvency_peg_decoupling", "experiment_c", 1, "solvency_improves_peg_unchanged", "supports_decoupling", "Stable collateral improves solvency with unchanged peg outcomes.", "Stable proxy is counterfactual."),
        ("S5_solvency_peg_decoupling", "experiment_d", 1, "neither_materially_changes", "neutral_context", "Capacity treatment does not materially alter either outcome overall.", "Several anchors do not bind."),
        ("S5_solvency_peg_decoupling", "experiment_e", 1, "solvency_deteriorates_peg_unchanged", "supports_decoupling", "Oracle delay changes timing and solvency diagnostics with unchanged peg outcomes.", "Transparent delay sensitivity."),
    ]
    return [
        {
            "finding_order": index,
            "component": component,
            "source_identifier": source,
            "tier": tier,
            "registered_finding": finding,
            "evidence_direction": direction,
            "quantitative_context": context,
            "limitation": limitation,
        }
        for index, (component, source, tier, finding, direction, context, limitation) in enumerate(rows, start=1)
    ]


def build_claim_crosswalk() -> list[dict[str, Any]]:
    claims = [
        ("C01", "Collateral rebound needs unresolved positions.", "unbounded_eth_recovery;constrained_eth_recovery", "", "no_clear_recovery_path_effect;H5a supported", "Immediate versus capacity-constrained ETH execution.", "conditional", "conditionally supported", "Collateral rebound can affect vault outcomes while unsafe positions remain unresolved.", "Collateral recovery always rescues vaults."),
        ("C02", "Immediate liquidation removes the rescue channel.", "unbounded_eth_recovery", "constrained_eth_recovery", "no_clear_recovery_path_effect", "Unbounded full-close execution.", "supports", "supported", "Immediate closure can leave no unresolved vault for later rebound to rescue.", "Collateral recovery never matters."),
        ("C03", "Bounded execution creates a rescue window.", "constrained_eth_recovery", "experiment_d", "H5a supported", "Controlled ETH versus final multi-collateral populations.", "supports", "supported", "Capacity-constrained execution leaves positions that can recover before liquidation.", "All capacity constraints create the same rescue window."),
        ("C04", "Lower capacity enlarges the rescue window.", "constrained_eth_recovery", "experiment_d", "H5c present", "Capacity 14/26/45 in controlled ETH paths.", "supports", "conditionally supported", "Within constrained ETH recovery, lower capacity leaves more positions available for rebound.", "Lower capacity is universally preferable."),
        ("C05", "Higher capacity reduces backlog.", "constrained_eth_recovery", "experiment_d", "higher_capacity_reduces_backlog", "Controlled ETH and mixed multi-collateral evidence.", "supports", "conditionally supported", "Higher registered capacity reduces backlog in the constrained ETH design.", "Capacity 45 is empirically optimal."),
        ("C06", "Collateral recovery improves solvency under constrained execution.", "constrained_eth_recovery", "", "H5a supported", "Persistent trough versus full-week rebound.", "supports", "supported", "Full-week rebound avoids liquidation debt and rescues positions under constrained execution.", "Recovery improves every system outcome."),
        ("C07", "Stage 1 peg outcomes do not respond directly to collateral rebound.", "stage1_dai_mechanism;constrained_eth_recovery", "confidence_scenarios", "H5b not supported", "Stage 1 has no direct recovery-path term.", "supports", "supported", "Under Stage 1-only, registered recovery paths leave primary peg outcomes unchanged.", "Collateral values can never affect the DAI peg."),
        ("C08", "Persistent-confidence effects are scenario-dependent.", "confidence_scenarios;unbounded_eth_recovery;constrained_eth_recovery", "confidence_partial_identification", "scenario effects;no admissible vector", "Transparent active scenarios versus dormant Stage 1.", "scenario_dependent", "scenario-dependent", "Behavioural assumptions can alter recovery, but the direction depends on the registered scenario.", "Persistent confidence is empirically calibrated."),
        ("C09", "No confidence scenario is empirically preferred.", "confidence_partial_identification;confidence_structural_factorial;confidence_scenarios", "", "zero admissible vectors;no selected cell;no scenario selected", "Calibration closure and transparent registry.", "not_identified", "not identified", "The evidence supports sensitivity analysis without ranking or selecting a scenario.", "The central scenario is the empirical estimate."),
        ("C10", "Backlog is a structural behavioural-recovery gate.", "stage1_dai_mechanism;constrained_eth_recovery", "", "operational gate;H5c present", "Registered scenario mechanism and constrained ETH execution.", "supports_mechanism", "supported", "The implemented behavioural recovery mechanism requires unresolved stress to clear.", "Backlog alone causes peg recovery."),
        ("C11", "The gate's causal peg effect is not cleanly isolated.", "constrained_eth_recovery;experiment_e", "", "H5b not supported;E3 peg_unchanged", "Recovery and timing contrasts do not isolate the gate coefficient.", "unresolved", "not identified", "The gate is operational, but its independent causal effect on peg recovery remains unresolved.", "Backlog is proven to cause DAI depegging."),
        ("C12", "Solvency and peg recovery are distinct.", "constrained_eth_recovery;experiment_a;experiment_b;experiment_c;experiment_e", "experiment_d", "registered peg-solvency relations", "Different populations and treatment questions; decisions are not pooled.", "supports", "supported", "Operational solvency changes repeatedly coexist with unchanged registered peg outcomes.", "Better solvency automatically restores the peg."),
        ("C13", "Bad-debt evidence is limited by close-factor-one accounting.", "experiment_e;experiment_d", "", "bad-debt metrics degenerate", "Full-close final experiments.", "limits", "conditionally supported", "Degenerate bad-debt outcomes limit inference beyond the retained accounting boundary.", "Zero bad debt proves insolvency risk is absent."),
        ("C14", "H4 is conditional rather than universal.", "unbounded_eth_recovery;constrained_eth_recovery;confidence_scenarios;experiment_a;experiment_b;experiment_c;experiment_d;experiment_e", "confidence_partial_identification", "registered synthesis", "Mechanism triangulation across incompatible designs without statistical pooling.", "conditional", "conditionally supported", "Recovery depends on unresolved inventory, execution conditions and scenario-defined behaviour.", "H4 is universally or fully supported."),
    ]
    return [
        {
            "claim_order": index,
            "claim_identifier": identifier,
            "claim_text": text,
            "supporting_source_ids": support,
            "limiting_source_ids": limits,
            "source_decision_labels": labels,
            "source_design_differences": differences,
            "evidence_direction": direction,
            "evidential_status": status,
            "dissertation_safe_wording": safe,
            "prohibited_overstatement": prohibited,
        }
        for index, (identifier, text, support, limits, labels, differences, direction, status, safe, prohibited) in enumerate(claims, start=1)
    ]


def validate_claim_crosswalk(rows: Sequence[Mapping[str, Any]]) -> None:
    expected = [f"C{number:02d}" for number in range(1, 15)]
    identifiers = [str(row["claim_identifier"]) for row in rows]
    allowed_statuses = {
        "supported",
        "conditionally supported",
        "scenario-dependent",
        "not identified",
        "contradicted",
        "not testable",
    }
    source_ids = {source.identifier for source in SOURCE_DEFINITIONS}
    if identifiers != expected:
        raise ValueError("The registered H4 claim population differs.")
    for row in rows:
        referenced = {
            item
            for column in ("supporting_source_ids", "limiting_source_ids")
            for item in str(row[column]).split(";")
            if item
        }
        if not referenced or not referenced <= source_ids:
            raise ValueError(f"Invalid source mapping for {row['claim_identifier']}.")
        if row["evidential_status"] not in allowed_statuses:
            raise ValueError(f"Invalid evidence status for {row['claim_identifier']}.")
        if not row["dissertation_safe_wording"] or not row["prohibited_overstatement"]:
            raise ValueError(f"Incomplete wording boundary for {row['claim_identifier']}.")


def classify_synthesis() -> dict[str, Any]:
    _validate_registered_decisions()
    validate_quantitative_context()
    s1 = classify_s1(immediate_channel=False, constrained_channel=True)
    s2 = classify_s2(interaction_clear=True, capacity_effect_clear=True, operational_count=3)
    qualifier = s2_generalisability(final_capacity_clear=False)
    s3 = classify_s3(
        calibrated_vector=False,
        active_effects=(True, False, False),
        active_directions=(-1, 0, 0),
    )
    s4 = classify_s4(
        backlog_operational=True,
        mechanism_condition=True,
        isolated_peg_gate=False,
        peg_effect_assessed=True,
    )
    s5 = classify_s5(
        constrained_decoupling=True,
        final_decoupling_count=4,
        contradiction_count=0,
    )
    overall = classify_h4(s1=s1, s2=s2, s2_qualifier=qualifier, s3=s3, s4=s4, s5=s5)
    return {
        "S1_recovery_channel": s1,
        "S2_execution_conditioning": s2,
        "S2_generalisability_qualifier": qualifier,
        "S3_behavioural_stabilisation": s3,
        "S4_backlog_gate": s4,
        "S5_solvency_peg_decoupling": s5,
        "overall_h4_classification": overall,
    }


def specification_payload(source_registry_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "synthesis_parent_commit": SYNTHESIS_PARENT_COMMIT,
        "programme_identity": MASTER_PROGRAMME_IDENTITY,
        "purpose": "Registered evidence synthesis for RQ3 and H4; no new experiment.",
        "research_question": "RQ3",
        "hypothesis": "H4",
        "scientific_status": "registered_evidence_synthesis",
        "source_registry_sha256": source_registry_sha256,
        "evidence_hierarchy": [
            "Tier 1 registered decisions",
            "Tier 2 registered compact summaries",
            "Tier 3 tracked reports",
        ],
        "source_inclusion_rules": {
            "tracked_at_parent_commit": True,
            "checksum_match_required": True,
            "registered_decisions_are_primary": True,
            "compact_summaries_quantify_decisions_only": True,
            "reports_cannot_override_decisions": True,
        },
        "excluded_evidence": [
            "ignored checkpoints",
            "untracked notes",
            "held-out validation",
            "USDC/SVB validation",
            "external sources",
        ],
        "components": [
            "S1_recovery_channel",
            "S2_execution_conditioning",
            "S3_behavioural_stabilisation",
            "S4_backlog_gate",
            "S5_solvency_peg_decoupling",
        ],
        "component_rules": {
            "S1_recovery_channel": [
                "conditionally_operational",
                "generally_operational",
                "not_operational",
                "inconsistent",
                "invalid",
            ],
            "S2_execution_conditioning": [
                "supported",
                "partially_supported",
                "not_supported",
            ],
            "S2_generalisability_qualifier": ["general", "context_specific"],
            "S3_behavioural_stabilisation": [
                "scenario_dependent_not_identified",
                "robustly_supported",
                "not_operational",
                "empirically_identified",
            ],
            "S4_backlog_gate": [
                "mechanism_condition_supported",
                "peg_gate_effect_supported",
                "mechanism_present_peg_effect_unresolved",
                "not_operational",
            ],
            "S5_solvency_peg_decoupling": [
                "strongly_supported",
                "supported",
                "mixed",
                "not_supported",
            ],
        },
        "overall_hierarchy": [
            "H4_joint_recovery_supported",
            "H4_recovery_conditionally_supported",
            "H4_solvency_recovery_without_peg_recovery",
            "H4_behavioural_recovery_unresolved",
            "H4_no_clear_recovery_evidence",
            "H4_recovery_synthesis_invalid",
        ],
        "no_pooling_rule": {
            "statistical_pooling": False,
            "meta_analysis": False,
            "simulation_count_weighting": False,
            "method": "registered decision triangulation and mechanism compatibility",
        },
        "claim_schema": list(CLAIM_COLUMNS),
        "historical_labels": {
            "H5a_to_H5d": "internal constrained-recovery component labels, not dissertation hypotheses"
        },
        "final_validation_excluded": True,
        "runtime_adopted": False,
    }


def synthesis_identity(source_rows: Sequence[Mapping[str, Any]]) -> str:
    validate_source_registry(source_rows)
    source_decisions = {
        str(row["source_identifier"]): str(row["decision_checksum"])
        for row in source_rows
    }
    payload = {
        "parent_commit": SYNTHESIS_PARENT_COMMIT,
        "programme_identity": MASTER_PROGRAMME_IDENTITY,
        "confidence_registry_identity": CONFIDENCE_REGISTRY_IDENTITY,
        "partial_identification_identity": PARTIAL_IDENTIFICATION_IDENTITY,
        "structural_factorial_identity": STRUCTURAL_FACTORIAL_IDENTITY,
        "unbounded_recovery_identity": UNBOUNDED_RECOVERY_IDENTITY,
        "constrained_recovery_identity": CONSTRAINED_RECOVERY_IDENTITY,
        "final_experiment_identities": EXPERIMENT_IDENTITIES,
        "source_decision_checksums": source_decisions,
        "component_rules": specification_payload("")["component_rules"],
        "h4_hierarchy": specification_payload("")["overall_hierarchy"],
        "claim_schema": list(CLAIM_COLUMNS),
        "no_pooling": True,
        "final_validation_excluded": True,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def decision_payload(source_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    classification = classify_synthesis()
    return {
        "schema_version": 1,
        "synthesis_identity": synthesis_identity(source_rows),
        "scientific_status": "registered_evidence_synthesis",
        **classification,
        "rq3_answer": (
            "Collateral recovery can rescue unresolved vaults and reduce backlog, but "
            "the channel disappears after liquidation closure. Execution capacity "
            "changes the rescue window. Behavioural assumptions can alter peg "
            "recovery under transparent scenarios, but are not empirically identified. "
            "Across the Stage 1-only final programme, solvency and liquidation-timing "
            "changes generally remain distinct from sustained DAI peg recovery."
        ),
        "principal_limitations": [
            "The synthesis organises known registered findings and creates no new cross-experiment causal contrast.",
            "Source populations, shocks, seeds and confidence activation differ and are not statistically pooled.",
            "Persistent-confidence parameters are not empirically identified.",
            "The causal backlog-to-peg gate effect is not cleanly isolated.",
            "Bad-debt evidence is limited by close-factor-one accounting.",
        ],
        "confidence_scenario_ranked": False,
        "confidence_scenario_selected": None,
        "runtime_adopted": False,
        "simulations_executed": 0,
        "checkpoints_read": 0,
        "held_out_observations": 0,
        "usdc_svb_used": False,
        "next_stage": "pre_registered_robustness_and_final_validation_without_retuning",
    }


def build_evidence_payloads() -> dict[str, bytes]:
    sources = build_source_registry()
    validate_source_registry(sources)
    sources_bytes = _csv_bytes(sources, SOURCE_COLUMNS)
    registry_sha = hashlib.sha256(sources_bytes).hexdigest()
    specification = specification_payload(registry_sha)
    identity = synthesis_identity(sources)
    specification["synthesis_identity"] = identity
    matrix = build_evidence_matrix()
    claims = build_claim_crosswalk()
    validate_claim_crosswalk(claims)
    decision = decision_payload(sources)
    first_five = {
        COMPACT_FILENAMES[0]: _pretty_json(specification),
        COMPACT_FILENAMES[1]: sources_bytes,
        COMPACT_FILENAMES[2]: _csv_bytes(matrix, MATRIX_COLUMNS),
        COMPACT_FILENAMES[3]: _csv_bytes(claims, CLAIM_COLUMNS),
        COMPACT_FILENAMES[4]: _pretty_json(decision),
    }
    reproducibility = {
        "schema_version": 1,
        "synthesis_identity": identity,
        "programme_identity": MASTER_PROGRAMME_IDENTITY,
        "source_registry_sha256": registry_sha,
        "source_count": len(sources),
        "claim_count": len(claims),
        "source_identities": {
            str(row["source_identifier"]): str(row["experiment_or_calibration_identity"])
            for row in sources
        },
        "source_decision_checksums": {
            str(row["source_identifier"]): str(row["decision_checksum"])
            for row in sources
        },
        "result_checksums": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in first_five.items()
        },
        "deterministic_reconstruction": True,
        "simulations_executed": 0,
        "checkpoints_read": 0,
        "network_calls": 0,
        "calibration_runs": 0,
        "held_out_observations": 0,
        "scenario_rankings": 0,
        "runtime_changes": 0,
        "historical_evidence_rewritten": False,
        "runtime_adopted": False,
    }
    return {
        **first_five,
        COMPACT_FILENAMES[5]: _pretty_json(reproducibility),
    }


def _manifest_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [
        {
            "classification": "registered_h4_recovery_behaviour_evidence_synthesis",
            "path": _relative(path),
            "runtime_adopted": False,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]


def update_experiment_manifest(records: Sequence[Mapping[str, Any]]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    owned = {_relative(EVIDENCE_DIR / name) for name in COMPACT_FILENAMES}
    preserved = [row for row in manifest["artefacts"] if str(row["path"]) not in owned]
    if len(preserved) != 67:
        raise ValueError("H4 synthesis expected 67 preserved experiment artefacts.")
    if {str(row["path"]) for row in records} != owned:
        raise ValueError("H4 synthesis manifest ownership differs.")
    combined = sorted([*preserved, *map(dict, records)], key=lambda row: str(row["path"]))
    if len(combined) != 73 or len({str(row["path"]) for row in combined}) != 73:
        raise ValueError("H4 synthesis manifest count or uniqueness differs.")
    manifest["artefacts"] = combined
    manifest["artefact_count"] = 73
    _atomic_bytes(MANIFEST_PATH, _pretty_json(manifest))


def write_evidence() -> dict[str, Any]:
    first = build_evidence_payloads()
    second = build_evidence_payloads()
    if first != second:
        raise ValueError("H4 synthesis reconstruction is not deterministic.")
    with tempfile.TemporaryDirectory(prefix="h4-synthesis-first-") as first_name, tempfile.TemporaryDirectory(prefix="h4-synthesis-second-") as second_name:
        for directory, payloads in ((Path(first_name), first), (Path(second_name), second)):
            for name, payload in payloads.items():
                _atomic_bytes(directory / name, payload)
        for name in COMPACT_FILENAMES:
            if (Path(first_name) / name).read_bytes() != (Path(second_name) / name).read_bytes():
                raise ValueError(f"Isolated H4 reconstruction differs: {name}.")
    for name, payload in first.items():
        _atomic_bytes(EVIDENCE_DIR / name, payload)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    update_experiment_manifest(_manifest_records(paths))
    return {
        "synthesis_identity": json.loads(first[COMPACT_FILENAMES[4]])["synthesis_identity"],
        "artefact_count": 6,
        "artefact_checksums": {path.name: sha256_file(path) for path in paths},
        "deterministic_reconstruction": True,
        "simulations_executed": 0,
        "checkpoints_read": 0,
    }


def validate_evidence() -> dict[str, Any]:
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise ValueError("H4 synthesis evidence is incomplete.")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {str(row["path"]): row for row in manifest["artefacts"]}
    if manifest.get("artefact_count") != 73 or len(records) != 73:
        raise ValueError("H4 synthesis manifest count differs.")
    for path in paths:
        row = records.get(_relative(path))
        if row is None or row["sha256"] != sha256_file(path) or int(row["size_bytes"]) != path.stat().st_size:
            raise ValueError(f"H4 synthesis manifest mismatch: {_relative(path)}.")
    with paths[1].open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle))
    with paths[3].open(encoding="utf-8", newline="") as handle:
        claims = list(csv.DictReader(handle))
    decision = json.loads(paths[4].read_text(encoding="utf-8"))
    reproducibility = json.loads(paths[5].read_text(encoding="utf-8"))
    validate_source_registry(sources)
    validate_claim_crosswalk(claims)
    if (
        len(sources) != len(SOURCE_DEFINITIONS)
        or len(claims) != 14
        or decision["overall_h4_classification"] != "H4_recovery_conditionally_supported"
        or decision["confidence_scenario_selected"] is not None
        or decision["runtime_adopted"]
        or reproducibility["simulations_executed"] != 0
        or reproducibility["checkpoints_read"] != 0
        or reproducibility["network_calls"] != 0
        or not reproducibility["deterministic_reconstruction"]
    ):
        raise ValueError("H4 synthesis evidence validation failed.")
    return {
        "passed": True,
        "synthesis_identity": decision["synthesis_identity"],
        "source_count": len(sources),
        "claim_count": len(claims),
        "overall_h4_classification": decision["overall_h4_classification"],
        "manifest_count": manifest["artefact_count"],
        "artefact_checksums": {path.name: sha256_file(path) for path in paths},
        "simulations_executed": 0,
        "checkpoints_read": 0,
    }
