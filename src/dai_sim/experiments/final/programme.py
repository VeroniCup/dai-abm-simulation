"""Typed, result-blind owner for the final dissertation programme.

The YAML registry owns the programme design.  This module validates frozen
input identities and expands the five core experiments into deterministic
cell records; it does not execute a simulation or inspect an experiment
result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import csv
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml

from dai_sim.inputs.confidence_scenarios import (
    load_confidence_scenario_registry,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PROGRAMME_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_experiment_programme.yaml"
)
DEFAULT_PREREGISTRATION_DIR = (
    REPOSITORY_ROOT / "data/provenance/experiments/final_programme"
)
EXPERIMENT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
)
PROGRAMME_IDENTIFIER = "final_dissertation_experiment_programme"
EXPECTED_PARENT_COMMIT = "0fabe5192b7942969fd01b602fc1031b6dcf8f62"
EXPECTED_TAXONOMY_SHA256 = (
    "b9e30d4ca97c4c1ab382dcdb2b2fdc980c277ebcef0f54ba20d1933db119af22"
)
RESEARCH_QUESTION_ORDER = ("RQ1", "RQ2", "RQ3", "RQ4")
HYPOTHESIS_ORDER = ("H1", "H2", "H3", "H4")
EXPERIMENT_ORDER = (
    "A_idiosyncratic_diversification",
    "B_correlated_stress",
    "C_stable_collateral_tradeoff",
    "D_shared_keeper_capacity",
    "E_oracle_delay",
)
EXPECTED_EXPERIMENT_CELL_COUNTS = {
    "A_idiosyncratic_diversification": 8,
    "B_correlated_stress": 8,
    "C_stable_collateral_tradeoff": 12,
    "D_shared_keeper_capacity": 9,
    "E_oracle_delay": 6,
}
EXPECTED_EXECUTION_STATUSES = {
    "A_idiosyncratic_diversification": "authorised_current_pass",
    "B_correlated_stress": "preregistered_not_executed",
    "C_stable_collateral_tradeoff": "preregistered_not_executed",
    "D_shared_keeper_capacity": "preregistered_not_executed",
    "E_oracle_delay": (
        "preregistered_blocked_pending_oracle_delay_freeze"
    ),
}
EXPECTED_DEPENDENCY_STATUSES = {
    "A_idiosyncratic_diversification": "frozen_inputs_ready",
    "B_correlated_stress": "frozen_inputs_ready",
    "C_stable_collateral_tradeoff": "frozen_inputs_ready",
    "D_shared_keeper_capacity": "frozen_inputs_ready",
    "E_oracle_delay": "oracle_delay_freeze_required",
}
EXPECTED_EXPERIMENT_OWNERSHIP = {
    "A_idiosyncratic_diversification": (("RQ4",), ("H3",)),
    "B_correlated_stress": (("RQ4",), ("H3",)),
    "C_stable_collateral_tradeoff": (("RQ4",), ("H3",)),
    "D_shared_keeper_capacity": (("RQ2", "RQ4"), ("H1", "H3")),
    "E_oracle_delay": (("RQ2",), ("H2",)),
}
EXPECTED_CROSS_PRODUCTS = {
    "A_idiosyncratic_diversification": (
        ("eth_only", "empirical_crypto", "balanced_crypto", "stable_supported"),
        ("eth_idiosyncratic_severe", "wbtc_idiosyncratic_severe"),
    ),
    "B_correlated_stress": (
        ("eth_only", "empirical_crypto", "balanced_crypto", "stable_supported"),
        ("joint_crypto_empirical_stress", "joint_crypto_high_correlation"),
    ),
    "C_stable_collateral_tradeoff": (
        ("empirical_crypto", "stable_supported", "stable_heavy"),
        (
            "joint_crypto_high_correlation",
            "stable_depeg_moderate",
            "stable_depeg_severe",
            "joint_crypto_stable_stress",
        ),
    ),
}
EXPECTED_ANCHORS = {
    "D_shared_keeper_capacity": (
        ("empirical_crypto", "joint_crypto_high_correlation"),
        ("stable_supported", "joint_crypto_stable_stress"),
        ("stable_heavy", "joint_crypto_stable_stress"),
    ),
    "E_oracle_delay": (
        ("empirical_crypto", "joint_crypto_high_correlation"),
        ("stable_supported", "joint_crypto_stable_stress"),
    ),
}
EXPECTED_PROFILE_IDENTITY = (
    "d0241808701d0472532c1f7c502ab6637afd60a50082b94bed9ff66f7ec2d53e"
)
EXPECTED_PROFILE_SHA256 = (
    "a2da654cdc9fc053c50f13aacb18e63ce7854bf47d6ad1519352467f6c7986fc"
)
EXPECTED_PROFILE_IDENTITY_SOURCE_SHA256 = (
    "e57258a9bc81f8d602a6bd7a9dbc306695a8c7bdbace84d5ba26b6b821c361f6"
)
EXPECTED_REGISTRY_SHA256 = {
    "collateral_registry": (
        "75268fed6b3db5a80a822a80b8629291491cd73ce62b4c3e6cf3975060b4eb6d"
    ),
    "portfolio_registry": (
        "76aa03afa352d86be76fbc7e0153981589f50798c52aed7dfad897061b7960b1"
    ),
    "shock_registry": (
        "a98df90e3e743fc22d9f92c38d53cf46a893928d3fe48eda9e609a20aa108581"
    ),
    "keeper_registry": (
        "e1d590508bb3e95ec6bdc2a30c41580fe211831a673dd447e793a0053a7fa848"
    ),
}
EXPECTED_KEEPER_EVIDENCE_SHA256 = (
    "58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b"
)
EXPECTED_CONFIDENCE_IDENTITY = (
    "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
)
EXPECTED_CONFIDENCE_CONFIG_SHA256 = (
    "86c33147f167d708e4a18191e50c39bec5056a680b13e682551317ba9b916e85"
)
EXPECTED_STAGE1_EVIDENCE_SHA256 = (
    "d86625e268c7e8b8abcb6d37e48f87c3c01578c8a3c09024a57da93978614547"
)
EXPECTED_RESIDUAL_EVIDENCE_SHA256 = (
    "98299918d452695b96f639aaae4c2344c189a3351bd55f1d86a2441d5bcded0e"
)
EXPECTED_RESIDUAL_SEQUENCE_SHA256 = (
    "3fa2319cee9e1749405c0dc477e0f11ef9c31dd83c371b619bd33eda23c37c30"
)
EXPECTED_RESIDUAL_BLOCK_SHA256 = (
    "6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c"
)
EXPECTED_PORTFOLIOS = (
    "eth_only",
    "empirical_crypto",
    "balanced_crypto",
    "stable_supported",
    "stable_heavy",
)
EXPECTED_SHOCKS = (
    "eth_idiosyncratic_severe",
    "wbtc_idiosyncratic_severe",
    "joint_crypto_empirical_stress",
    "joint_crypto_high_correlation",
    "stable_depeg_moderate",
    "stable_depeg_severe",
    "joint_crypto_stable_stress",
)
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_RESULT_KEYS = {
    "benchmark",
    "experiment_results",
    "preferred_portfolio",
    "preferred_shock",
    "result",
    "results",
    "selected_portfolio",
    "selected_shock",
}


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_payload(payload: Any) -> str:
    encoded = json.dumps(
        _canonical(payload),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping.")
    return value


def _sequence(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list.")
    return value


def _decimal(value: Any, context: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{context} must be numeric.")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{context} must be numeric.") from exc
    if not result.is_finite():
        raise ValueError(f"{context} must be finite.")
    return result


def _repository_file(value: Any, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a repository-relative path.")
    path = (REPOSITORY_ROOT / value).resolve()
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise ValueError(f"{context} must remain inside the repository.") from exc
    if not path.is_file():
        raise ValueError(f"{context} does not exist: {value}.")
    return path


def _validate_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lowercase SHA-256 digest.")
    return value


def _validate_file_owner(
    raw: Mapping[str, Any],
    context: str,
    *,
    expected_sha256: str | None = None,
) -> Path:
    path = _repository_file(raw.get("path"), f"{context} path")
    expected = _validate_sha256(raw.get("sha256"), f"{context} SHA-256")
    if expected_sha256 is not None and expected != expected_sha256:
        raise ValueError(f"{context} does not match the frozen checksum.")
    observed = _sha256_file(path)
    if observed != expected:
        raise ValueError(
            f"{context} checksum mismatch: expected {expected}, "
            f"observed {observed}."
        )
    return path


def _reject_result_fields(value: Any, context: str = "programme") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _FORBIDDEN_RESULT_KEYS:
                raise ValueError(
                    f"{context} contains forbidden result field {key!r}."
                )
            _reject_result_fields(item, f"{context}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_result_fields(item, f"{context}[{index}]")


@dataclass(frozen=True)
class ResearchQuestion:
    """One approved dissertation research question."""

    identifier: str
    text: str


@dataclass(frozen=True)
class Hypothesis:
    """One approved dissertation hypothesis."""

    identifier: str
    title: str
    statement: str


@dataclass(frozen=True)
class ProgrammeCell:
    """One pre-registered final-programme simulation cell."""

    programme_order: int
    experiment_identifier: str
    cell_order: int
    identifier: str
    research_questions: tuple[str, ...]
    hypotheses: tuple[str, ...]
    portfolio_identifier: str
    shock_identifier: str
    capacity_profile_identifier: str
    maximum_liquidations_per_step: int
    confidence_scenario_identifier: str
    hurdle_profile_identifier: str
    risk_cost_rate: Decimal
    oracle_treatment_identifier: str | None
    oracle_delay_steps: int | None
    replication_count: int
    execution_status: str
    row_checksum: str


@dataclass(frozen=True)
class FinalExperiment:
    """One core experiment in the final programme."""

    order: int
    identifier: str
    primary_research_question: str
    research_questions: tuple[str, ...]
    primary_hypothesis: str
    hypotheses: tuple[str, ...]
    replication_count: int
    execution_status: str
    dependency_status: str
    cells: tuple[ProgrammeCell, ...]


@dataclass(frozen=True)
class EvidenceSynthesis:
    """The non-matrix H4 evidence-synthesis boundary."""

    identifier: str
    order: int
    research_questions: tuple[str, ...]
    hypotheses: tuple[str, ...]
    execution_status: str
    evidence_sources: tuple[str, ...]


@dataclass(frozen=True)
class FinalExperimentProgramme:
    """Fully validated, result-blind final experiment programme."""

    path: Path
    configuration_checksum: str
    identifier: str
    parent_commit: str
    package_taxonomy_path: str
    package_taxonomy_checksum: str
    package_boundary: str
    runtime_adopted: bool
    research_questions: tuple[ResearchQuestion, ...]
    hypotheses: tuple[Hypothesis, ...]
    experiments: tuple[FinalExperiment, ...]
    h4_synthesis: EvidenceSynthesis
    planned_core_cells: int
    planned_core_simulations: int
    authorised_current_pass_simulations: int
    frozen_inputs: Mapping[str, Any]
    common_treatment: Mapping[str, Any]
    final_validation_boundary: Mapping[str, Any]
    programme_identity: str

    @property
    def cells(self) -> tuple[ProgrammeCell, ...]:
        return tuple(
            cell for experiment in self.experiments for cell in experiment.cells
        )

    @property
    def experiments_by_identifier(self) -> dict[str, FinalExperiment]:
        return {
            experiment.identifier: experiment for experiment in self.experiments
        }


def _parse_questions(
    raw: Mapping[str, Any],
) -> tuple[ResearchQuestion, ...]:
    if tuple(raw) != RESEARCH_QUESTION_ORDER:
        raise ValueError("Research questions must be exactly RQ1 through RQ4.")
    result = []
    for identifier, values in raw.items():
        text = _mapping(values, identifier).get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{identifier} text must be explicit.")
        result.append(ResearchQuestion(identifier=identifier, text=text.strip()))
    return tuple(result)


def _parse_hypotheses(raw: Mapping[str, Any]) -> tuple[Hypothesis, ...]:
    if tuple(raw) != HYPOTHESIS_ORDER:
        raise ValueError("Hypotheses must be exactly H1 through H4.")
    result = []
    for identifier, values_raw in raw.items():
        values = _mapping(values_raw, identifier)
        title = values.get("title")
        statement = values.get("statement")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{identifier} title must be explicit.")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"{identifier} statement must be explicit.")
        result.append(
            Hypothesis(
                identifier=identifier,
                title=title.strip(),
                statement=statement.strip(),
            )
        )
    return tuple(result)


def _validate_frozen_inputs(raw: Mapping[str, Any]) -> None:
    profile = _mapping(raw.get("integrated_profile"), "integrated profile")
    profile_path = _validate_file_owner(
        profile,
        "integrated profile",
        expected_sha256=EXPECTED_PROFILE_SHA256,
    )
    if profile.get("identifier") != "empirical_integrated_multicollateral":
        raise ValueError("Unexpected integrated profile identifier.")
    if profile.get("identity") != EXPECTED_PROFILE_IDENTITY:
        raise ValueError("Unexpected integrated profile identity.")
    identity_path = _repository_file(
        profile.get("identity_source_path"),
        "integrated profile identity source",
    )
    identity_source_sha = _validate_sha256(
        profile.get("identity_source_sha256"),
        "integrated profile identity-source SHA-256",
    )
    if (
        identity_source_sha != EXPECTED_PROFILE_IDENTITY_SOURCE_SHA256
        or _sha256_file(identity_path) != identity_source_sha
    ):
        raise ValueError("Integrated profile identity-source checksum differs.")
    identity_payload = json.loads(identity_path.read_text(encoding="utf-8"))
    if (
        identity_payload.get("profile_identity") != EXPECTED_PROFILE_IDENTITY
        or identity_payload.get("profile_checksum") != EXPECTED_PROFILE_SHA256
    ):
        raise ValueError("Integrated profile evidence does not bind its identity.")
    if _sha256_file(profile_path) != EXPECTED_PROFILE_SHA256:
        raise ValueError("Integrated profile checksum differs.")

    for owner_name, expected_sha in EXPECTED_REGISTRY_SHA256.items():
        _validate_file_owner(
            _mapping(raw.get(owner_name), owner_name),
            owner_name,
            expected_sha256=expected_sha,
        )

    keeper = _mapping(raw["keeper_registry"], "keeper registry")
    keeper_evidence_path = _repository_file(
        keeper.get("evidence_path"), "keeper evidence"
    )
    keeper_evidence_sha = _validate_sha256(
        keeper.get("evidence_sha256"), "keeper evidence SHA-256"
    )
    if (
        keeper_evidence_sha != EXPECTED_KEEPER_EVIDENCE_SHA256
        or _sha256_file(keeper_evidence_path) != keeper_evidence_sha
    ):
        raise ValueError("Keeper evidence registry checksum differs.")

    confidence = _mapping(raw.get("confidence_registry"), "confidence registry")
    _validate_file_owner(
        confidence,
        "confidence registry",
        expected_sha256=EXPECTED_CONFIDENCE_CONFIG_SHA256,
    )
    if confidence.get("identity") != EXPECTED_CONFIDENCE_IDENTITY:
        raise ValueError("Confidence registry identity differs.")
    resolved_confidence = load_confidence_scenario_registry(
        _repository_file(confidence["path"], "confidence registry path")
    )
    if resolved_confidence.registry_sha256 != EXPECTED_CONFIDENCE_IDENTITY:
        raise ValueError("Resolved confidence registry identity differs.")

    stage1 = _mapping(raw.get("stage1"), "Stage 1")
    stage1_path = _repository_file(stage1.get("evidence_path"), "Stage 1 evidence")
    stage1_sha = _validate_sha256(
        stage1.get("evidence_sha256"), "Stage 1 evidence SHA-256"
    )
    if (
        stage1_sha != EXPECTED_STAGE1_EVIDENCE_SHA256
        or _sha256_file(stage1_path) != stage1_sha
    ):
        raise ValueError("Stage 1 evidence checksum differs.")
    stage1_payload = json.loads(stage1_path.read_text(encoding="utf-8"))
    expected_below = _decimal(stage1["below_peg_response"], "Stage 1 below peg")
    expected_above = _decimal(stage1["above_peg_response"], "Stage 1 above peg")
    observed_below = _decimal(
        stage1_payload["below_peg_response"]["point_estimate"],
        "observed Stage 1 below peg",
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    observed_above = _decimal(
        stage1_payload["above_peg_response"]["point_estimate"],
        "observed Stage 1 above peg",
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if (expected_below, expected_above) != (observed_below, observed_above):
        raise ValueError("Stage 1 rounded responses differ from frozen evidence.")

    residuals = _mapping(raw.get("residuals"), "residuals")
    residual_path = _repository_file(
        residuals.get("evidence_path"), "residual evidence"
    )
    residual_sha = _validate_sha256(
        residuals.get("evidence_sha256"), "residual evidence SHA-256"
    )
    if (
        residual_sha != EXPECTED_RESIDUAL_EVIDENCE_SHA256
        or _sha256_file(residual_path) != residual_sha
    ):
        raise ValueError("Residual evidence checksum differs.")
    residual_payload = json.loads(residual_path.read_text(encoding="utf-8"))
    if (
        residuals.get("sequence_sha256") != EXPECTED_RESIDUAL_SEQUENCE_SHA256
        or residual_payload.get("centred_residual_sequence_sha256")
        != EXPECTED_RESIDUAL_SEQUENCE_SHA256
        or residuals.get("block_sha256") != EXPECTED_RESIDUAL_BLOCK_SHA256
        or residual_payload.get("block_index_specification_sha256")
        != EXPECTED_RESIDUAL_BLOCK_SHA256
    ):
        raise ValueError("Stage 1 residual identities differ.")


def _portfolio_and_shock_identifiers(
    frozen_inputs: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    portfolio_owner = _mapping(
        frozen_inputs["portfolio_registry"], "portfolio registry"
    )
    portfolio_payload = yaml.safe_load(
        _repository_file(
            portfolio_owner["path"], "portfolio registry path"
        ).read_text(encoding="utf-8")
    )
    shock_owner = _mapping(frozen_inputs["shock_registry"], "shock registry")
    shock_payload = yaml.safe_load(
        _repository_file(
            shock_owner["path"], "shock registry path"
        ).read_text(encoding="utf-8")
    )
    portfolios = tuple(_mapping(portfolio_payload, "portfolio registry")["portfolios"])
    shocks = tuple(_mapping(shock_payload, "shock registry")["shocks"])
    if portfolios != EXPECTED_PORTFOLIOS or shocks != EXPECTED_SHOCKS:
        raise ValueError("Final portfolio or shock registry order differs.")
    return portfolios, shocks


def _common_cell_values(
    common: Mapping[str, Any],
) -> dict[str, Any]:
    keeper = _mapping(common.get("keeper"), "common keeper treatment")
    oracle = _mapping(common.get("oracle"), "common oracle treatment")
    if (
        common.get("profile_identifier")
        != "empirical_integrated_multicollateral"
        or int(common.get("total_vaults", 0)) != 500
        or _decimal(common.get("total_debt_dai"), "common total debt")
        != Decimal("2500000")
        or _decimal(
            common.get("target_system_collateral_ratio"),
            "common collateral ratio",
        )
        != Decimal("3.6089387701260205")
    ):
        raise ValueError("Common final-programme population differs.")
    if (
        keeper.get("capacity_profile_identifier")
        != "shared_keeper_capacity_central"
        or int(keeper.get("maximum_liquidations_per_step", 0)) != 26
        or keeper.get("hurdle_profile_identifier") != "direct_cost_only"
        or _decimal(keeper.get("risk_cost_rate"), "common keeper risk cost")
        != Decimal("0")
        or keeper.get("semantics") != "system_wide_shared_capacity"
    ):
        raise ValueError("Common keeper treatment differs.")
    if (
        common.get("confidence_scenario_identifier") != "stage1_only"
        or oracle.get("treatment_identifier")
        != "transparent_zero_delay_baseline"
        or int(oracle.get("delay_steps", -1)) != 0
        or common.get("recovery_path_identifier") != "full_week"
    ):
        raise ValueError("Common confidence, oracle or recovery treatment differs.")
    return {
        "capacity_profile_identifier": str(
            keeper["capacity_profile_identifier"]
        ),
        "maximum_liquidations_per_step": int(
            keeper["maximum_liquidations_per_step"]
        ),
        "confidence_scenario_identifier": str(
            common["confidence_scenario_identifier"]
        ),
        "hurdle_profile_identifier": str(
            keeper["hurdle_profile_identifier"]
        ),
        "risk_cost_rate": _decimal(
            keeper["risk_cost_rate"], "common keeper risk cost"
        ),
        "oracle_treatment_identifier": str(oracle["treatment_identifier"]),
        "oracle_delay_steps": int(oracle["delay_steps"]),
    }


def _cell(
    *,
    experiment_order: int,
    experiment_identifier: str,
    cell_order: int,
    identifier: str,
    research_questions: tuple[str, ...],
    hypotheses: tuple[str, ...],
    portfolio: str,
    shock: str,
    capacity_profile: str,
    capacity: int,
    confidence: str,
    hurdle: str,
    risk_cost_rate: Decimal,
    oracle_treatment: str | None,
    oracle_delay_steps: int | None,
    replication_count: int,
    execution_status: str,
) -> ProgrammeCell:
    raw = {
        "programme_order": experiment_order,
        "experiment_identifier": experiment_identifier,
        "cell_order": cell_order,
        "identifier": identifier,
        "research_questions": research_questions,
        "hypotheses": hypotheses,
        "portfolio_identifier": portfolio,
        "shock_identifier": shock,
        "capacity_profile_identifier": capacity_profile,
        "maximum_liquidations_per_step": capacity,
        "confidence_scenario_identifier": confidence,
        "hurdle_profile_identifier": hurdle,
        "risk_cost_rate": risk_cost_rate,
        "oracle_treatment_identifier": oracle_treatment,
        "oracle_delay_steps": oracle_delay_steps,
        "replication_count": replication_count,
        "execution_status": execution_status,
    }
    return ProgrammeCell(**raw, row_checksum=_sha256_payload(raw))


def _cross_product_cells(
    *,
    experiment_order: int,
    experiment_identifier: str,
    values: Mapping[str, Any],
    common: Mapping[str, Any],
    allowed_portfolios: set[str],
    allowed_shocks: set[str],
) -> tuple[ProgrammeCell, ...]:
    portfolios = tuple(
        str(value)
        for value in _sequence(values.get("portfolios"), "experiment portfolios")
    )
    shocks = tuple(
        str(value)
        for value in _sequence(values.get("shocks"), "experiment shocks")
    )
    expected_portfolios, expected_shocks = EXPECTED_CROSS_PRODUCTS[
        experiment_identifier
    ]
    if (portfolios, shocks) != (expected_portfolios, expected_shocks):
        raise ValueError(
            f"{experiment_identifier} treatment matrix differs."
        )
    if not set(portfolios) <= allowed_portfolios or not set(shocks) <= allowed_shocks:
        raise ValueError(f"{experiment_identifier} uses an unknown frozen input.")
    if values.get("cell_order") != "shock_then_portfolio":
        raise ValueError(f"{experiment_identifier} must use shock-first ordering.")
    questions = tuple(str(value) for value in values["research_questions"])
    hypotheses = tuple(str(value) for value in values["hypotheses"])
    replication_count = int(values["replication_count"])
    execution_status = str(values["execution_status"])
    cells = []
    for shock in shocks:
        for portfolio in portfolios:
            cells.append(
                _cell(
                    experiment_order=experiment_order,
                    experiment_identifier=experiment_identifier,
                    cell_order=len(cells) + 1,
                    identifier=f"{shock}__{portfolio}",
                    research_questions=questions,
                    hypotheses=hypotheses,
                    portfolio=portfolio,
                    shock=shock,
                    capacity_profile=common["capacity_profile_identifier"],
                    capacity=common["maximum_liquidations_per_step"],
                    confidence=common["confidence_scenario_identifier"],
                    hurdle=common["hurdle_profile_identifier"],
                    risk_cost_rate=common["risk_cost_rate"],
                    oracle_treatment=common["oracle_treatment_identifier"],
                    oracle_delay_steps=common["oracle_delay_steps"],
                    replication_count=replication_count,
                    execution_status=execution_status,
                )
            )
    return tuple(cells)


def _anchored_cells(
    *,
    experiment_order: int,
    experiment_identifier: str,
    values: Mapping[str, Any],
    common: Mapping[str, Any],
    allowed_portfolios: set[str],
    allowed_shocks: set[str],
) -> tuple[ProgrammeCell, ...]:
    anchors = [
        _mapping(value, f"{experiment_identifier} anchor")
        for value in _sequence(values.get("anchors"), "experiment anchors")
    ]
    for anchor in anchors:
        if (
            anchor.get("portfolio") not in allowed_portfolios
            or anchor.get("shock") not in allowed_shocks
        ):
            raise ValueError(f"{experiment_identifier} has an unknown anchor.")
    observed_anchors = tuple(
        (str(anchor["portfolio"]), str(anchor["shock"]))
        for anchor in anchors
    )
    if observed_anchors != EXPECTED_ANCHORS[experiment_identifier]:
        raise ValueError(f"{experiment_identifier} anchors differ.")
    questions = tuple(str(value) for value in values["research_questions"])
    hypotheses = tuple(str(value) for value in values["hypotheses"])
    replication_count = int(values["replication_count"])
    execution_status = str(values["execution_status"])
    cells = []
    if experiment_identifier == "D_shared_keeper_capacity":
        if values.get("cell_order") != "anchor_then_capacity":
            raise ValueError("Experiment D must use anchor-first ordering.")
        treatments = [
            _mapping(value, "capacity treatment")
            for value in _sequence(
                values.get("capacity_treatments"), "capacity treatments"
            )
        ]
        expected = (
            ("shared_keeper_capacity_low", 14),
            ("shared_keeper_capacity_central", 26),
            ("shared_keeper_capacity_high", 45),
        )
        observed = tuple(
            (
                str(item.get("identifier")),
                int(item.get("maximum_liquidations_per_step")),
            )
            for item in treatments
        )
        if observed != expected:
            raise ValueError("Experiment D capacity treatments differ.")
        for anchor in anchors:
            for capacity_profile, capacity in observed:
                cells.append(
                    _cell(
                        experiment_order=experiment_order,
                        experiment_identifier=experiment_identifier,
                        cell_order=len(cells) + 1,
                        identifier=(
                            f"{anchor['shock']}__{anchor['portfolio']}"
                            f"__{capacity_profile}"
                        ),
                        research_questions=questions,
                        hypotheses=hypotheses,
                        portfolio=str(anchor["portfolio"]),
                        shock=str(anchor["shock"]),
                        capacity_profile=capacity_profile,
                        capacity=capacity,
                        confidence=common["confidence_scenario_identifier"],
                        hurdle=common["hurdle_profile_identifier"],
                        risk_cost_rate=common["risk_cost_rate"],
                        oracle_treatment=common["oracle_treatment_identifier"],
                        oracle_delay_steps=common["oracle_delay_steps"],
                        replication_count=replication_count,
                        execution_status=execution_status,
                    )
                )
    else:
        if values.get("cell_order") != "anchor_then_oracle_treatment":
            raise ValueError("Experiment E must use anchor-first oracle ordering.")
        treatments = [
            _mapping(value, "oracle treatment")
            for value in _sequence(
                values.get("oracle_treatments"), "oracle treatments"
            )
        ]
        expected_identifiers = (
            "oracle_delay_low",
            "oracle_delay_central",
            "oracle_delay_high",
        )
        if any(tuple(item) != ("identifier",) for item in treatments):
            raise ValueError(
                "Experiment E oracle treatments may contain identifiers only."
            )
        observed_identifiers = tuple(
            str(item["identifier"]) for item in treatments
        )
        if observed_identifiers != expected_identifiers:
            raise ValueError("Experiment E oracle identifiers differ.")
        for anchor in anchors:
            for oracle_identifier in observed_identifiers:
                cells.append(
                    _cell(
                        experiment_order=experiment_order,
                        experiment_identifier=experiment_identifier,
                        cell_order=len(cells) + 1,
                        identifier=(
                            f"{anchor['shock']}__{anchor['portfolio']}"
                            f"__{oracle_identifier}"
                        ),
                        research_questions=questions,
                        hypotheses=hypotheses,
                        portfolio=str(anchor["portfolio"]),
                        shock=str(anchor["shock"]),
                        capacity_profile=common["capacity_profile_identifier"],
                        capacity=common["maximum_liquidations_per_step"],
                        confidence=common["confidence_scenario_identifier"],
                        hurdle=common["hurdle_profile_identifier"],
                        risk_cost_rate=common["risk_cost_rate"],
                        oracle_treatment=oracle_identifier,
                        oracle_delay_steps=None,
                        replication_count=replication_count,
                        execution_status=execution_status,
                    )
                )
    return tuple(cells)


def _parse_experiments(
    raw: Mapping[str, Any],
    common: Mapping[str, Any],
    allowed_portfolios: tuple[str, ...],
    allowed_shocks: tuple[str, ...],
) -> tuple[FinalExperiment, ...]:
    if tuple(raw) != EXPERIMENT_ORDER:
        raise ValueError("Final experiment order must be exactly A through E.")
    portfolio_set = set(allowed_portfolios)
    shock_set = set(allowed_shocks)
    result = []
    for identifier, values_raw in raw.items():
        values = _mapping(values_raw, identifier)
        order = int(values.get("order", 0))
        if order != len(result) + 1:
            raise ValueError("Final experiment order fields are not contiguous.")
        questions = tuple(str(value) for value in values["research_questions"])
        hypotheses = tuple(str(value) for value in values["hypotheses"])
        if (
            questions,
            hypotheses,
        ) != EXPECTED_EXPERIMENT_OWNERSHIP[identifier]:
            raise ValueError(f"{identifier} research ownership differs.")
        if not set(questions) <= set(RESEARCH_QUESTION_ORDER):
            raise ValueError(f"{identifier} has an unknown research question.")
        if not set(hypotheses) <= set(HYPOTHESIS_ORDER):
            raise ValueError(f"{identifier} has an unknown hypothesis.")
        if values.get("primary_research_question") != questions[0]:
            raise ValueError(f"{identifier} primary research question differs.")
        if values.get("primary_hypothesis") != hypotheses[0]:
            raise ValueError(f"{identifier} primary hypothesis differs.")
        if values.get("execution_status") != EXPECTED_EXECUTION_STATUSES[identifier]:
            raise ValueError(f"{identifier} execution status differs.")
        if values.get("dependency_status") != EXPECTED_DEPENDENCY_STATUSES[
            identifier
        ]:
            raise ValueError(f"{identifier} dependency status differs.")
        if int(values.get("replication_count", 0)) != 128:
            raise ValueError(f"{identifier} replication count differs.")
        if values.get("final_validation_data_used") is not False:
            raise ValueError(f"{identifier} may not use final-validation data.")
        if identifier in {
            "A_idiosyncratic_diversification",
            "B_correlated_stress",
            "C_stable_collateral_tradeoff",
        }:
            cells = _cross_product_cells(
                experiment_order=order,
                experiment_identifier=identifier,
                values=values,
                common=common,
                allowed_portfolios=portfolio_set,
                allowed_shocks=shock_set,
            )
        else:
            cells = _anchored_cells(
                experiment_order=order,
                experiment_identifier=identifier,
                values=values,
                common=common,
                allowed_portfolios=portfolio_set,
                allowed_shocks=shock_set,
            )
        if len(cells) != EXPECTED_EXPERIMENT_CELL_COUNTS[identifier]:
            raise ValueError(f"{identifier} has an unexpected cell count.")
        result.append(
            FinalExperiment(
                order=order,
                identifier=identifier,
                primary_research_question=str(
                    values["primary_research_question"]
                ),
                research_questions=questions,
                primary_hypothesis=str(values["primary_hypothesis"]),
                hypotheses=hypotheses,
                replication_count=int(values["replication_count"]),
                execution_status=str(values["execution_status"]),
                dependency_status=str(values["dependency_status"]),
                cells=cells,
            )
        )
    return tuple(result)


def _parse_synthesis(raw: Mapping[str, Any]) -> EvidenceSynthesis:
    if (
        raw.get("identifier") != "H4_recovery_and_behaviour_synthesis"
        or int(raw.get("order", 0)) != 6
        or tuple(raw.get("research_questions", ())) != ("RQ3",)
        or tuple(raw.get("hypotheses", ())) != ("H4",)
        or raw.get("execution_status") != "pending_evidence_synthesis"
        or raw.get("unrestricted_core_simulation_matrix") is not False
    ):
        raise ValueError("H4 evidence-synthesis boundary differs.")
    sources = tuple(
        str(value)
        for value in _sequence(
            raw.get("evidence_sources"), "H4 evidence sources"
        )
    )
    if not sources:
        raise ValueError("H4 evidence sources must be explicit.")
    return EvidenceSynthesis(
        identifier=str(raw["identifier"]),
        order=6,
        research_questions=("RQ3",),
        hypotheses=("H4",),
        execution_status="pending_evidence_synthesis",
        evidence_sources=sources,
    )


def _identity_payload(
    *,
    identifier: str,
    parent: Mapping[str, Any],
    package_boundary: str,
    questions: tuple[ResearchQuestion, ...],
    hypotheses: tuple[Hypothesis, ...],
    experiments: tuple[FinalExperiment, ...],
    synthesis: EvidenceSynthesis,
    totals: Mapping[str, Any],
    frozen_inputs: Mapping[str, Any],
    common_treatment: Mapping[str, Any],
    final_validation_boundary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "programme_identifier": identifier,
        "parent": parent,
        "package_boundary": package_boundary,
        "research_questions": [asdict(item) for item in questions],
        "hypotheses": [asdict(item) for item in hypotheses],
        "experiments": [
            {
                **{
                    key: value
                    for key, value in asdict(experiment).items()
                    if key != "cells"
                },
                "cells": [asdict(cell) for cell in experiment.cells],
            }
            for experiment in experiments
        ],
        "h4_synthesis": asdict(synthesis),
        "programme_totals": totals,
        "frozen_inputs": frozen_inputs,
        "common_treatment": common_treatment,
        "final_validation_boundary": final_validation_boundary,
        "runtime_adopted": False,
    }


def load_final_experiment_programme(
    path: Path | str = DEFAULT_PROGRAMME_PATH,
) -> FinalExperimentProgramme:
    """Load and validate the complete result-blind final programme."""
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    raw = _mapping(payload, "final experiment programme")
    _reject_result_fields(raw)
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported final-programme schema.")
    if raw.get("programme_identifier") != PROGRAMME_IDENTIFIER:
        raise ValueError("Unexpected final-programme identifier.")
    if raw.get("runtime_adopted") is not False:
        raise ValueError("Final programme must remain non-adopted.")
    if raw.get("package_boundary") != "src/dai_sim/experiments/final/":
        raise ValueError("Final programme package boundary differs.")

    parent = _mapping(raw.get("parent"), "programme parent")
    if (
        parent.get("commit") != EXPECTED_PARENT_COMMIT
        or parent.get("subject") != "Clarify scientific package taxonomy"
    ):
        raise ValueError("Final-programme parent boundary differs.")
    taxonomy = _mapping(parent.get("package_taxonomy"), "package taxonomy")
    taxonomy_path = _repository_file(taxonomy.get("path"), "package taxonomy path")
    taxonomy_sha = _validate_sha256(
        taxonomy.get("sha256"), "package taxonomy SHA-256"
    )
    if taxonomy.get("snapshot_semantics") != "parent_commit_blob":
        raise ValueError("Package taxonomy must use parent-commit semantics.")
    if taxonomy_sha != EXPECTED_TAXONOMY_SHA256:
        raise ValueError("Package taxonomy parent snapshot differs.")
    # The live document is expected to evolve when Experiment A is documented.
    # The identity therefore binds the parent-commit digest, not future bytes.
    if taxonomy_path.name != "scientific_package_taxonomy.md":
        raise ValueError("Unexpected package-taxonomy owner.")

    questions = _parse_questions(
        _mapping(raw.get("research_questions"), "research questions")
    )
    hypotheses = _parse_hypotheses(
        _mapping(raw.get("hypotheses"), "hypotheses")
    )
    frozen_inputs = _mapping(raw.get("frozen_inputs"), "frozen inputs")
    _validate_frozen_inputs(frozen_inputs)
    common_treatment = _mapping(
        raw.get("common_treatment"), "common treatment"
    )
    common_values = _common_cell_values(common_treatment)
    portfolios, shocks = _portfolio_and_shock_identifiers(frozen_inputs)
    if tuple(raw.get("experiment_order", ())) != EXPERIMENT_ORDER:
        raise ValueError("Experiment order must be exactly A through E.")
    experiments = _parse_experiments(
        _mapping(raw.get("experiments"), "experiments"),
        common_values,
        portfolios,
        shocks,
    )
    synthesis = _parse_synthesis(
        _mapping(raw.get("h4_synthesis"), "H4 synthesis")
    )
    totals = _mapping(raw.get("programme_totals"), "programme totals")
    if (
        int(totals.get("planned_core_cells", 0)) != 43
        or int(totals.get("planned_core_simulations", 0)) != 5504
        or int(totals.get("authorised_current_pass_simulations", 0)) != 1024
    ):
        raise ValueError("Final-programme totals differ.")
    cells = tuple(cell for experiment in experiments for cell in experiment.cells)
    if len(cells) != 43:
        raise ValueError("Final programme must contain exactly 43 cells.")
    if (
        sum(cell.replication_count for cell in cells) != 5504
        or sum(
            cell.replication_count
            for cell in experiments[0].cells
        )
        != 1024
    ):
        raise ValueError("Final-programme simulation counts differ.")
    if len({cell.row_checksum for cell in cells}) != 43:
        raise ValueError("Final-programme cell checksums must be unique.")

    boundary = _mapping(
        raw.get("final_validation_boundary"), "final-validation boundary"
    )
    if (
        boundary.get("final_validation_data_used") is not False
        or boundary.get("excluded_intervals") != ["ftx", "usdc_svb"]
        or boundary.get("outcome_based_portfolio_selection") is not False
        or boundary.get("outcome_based_shock_selection") is not False
        or boundary.get("retuning_permitted") is not False
    ):
        raise ValueError("Result-blind final-validation boundary differs.")

    identity_payload = _identity_payload(
        identifier=PROGRAMME_IDENTIFIER,
        parent=parent,
        package_boundary=str(raw["package_boundary"]),
        questions=questions,
        hypotheses=hypotheses,
        experiments=experiments,
        synthesis=synthesis,
        totals=totals,
        frozen_inputs=frozen_inputs,
        common_treatment=common_treatment,
        final_validation_boundary=boundary,
    )
    return FinalExperimentProgramme(
        path=resolved,
        configuration_checksum=_sha256_file(resolved),
        identifier=PROGRAMME_IDENTIFIER,
        parent_commit=str(parent["commit"]),
        package_taxonomy_path=str(taxonomy["path"]),
        package_taxonomy_checksum=taxonomy_sha,
        package_boundary=str(raw["package_boundary"]),
        runtime_adopted=False,
        research_questions=questions,
        hypotheses=hypotheses,
        experiments=experiments,
        h4_synthesis=synthesis,
        planned_core_cells=43,
        planned_core_simulations=5504,
        authorised_current_pass_simulations=1024,
        frozen_inputs=frozen_inputs,
        common_treatment=common_treatment,
        final_validation_boundary=boundary,
        programme_identity=_sha256_payload(identity_payload),
    )


def programme_identity(
    programme: FinalExperimentProgramme | None = None,
) -> str:
    """Return the deterministic result-blind master programme identity."""
    owner = programme or load_programme()
    return owner.programme_identity


def load_programme(
    path: Path | str = DEFAULT_PROGRAMME_PATH,
) -> FinalExperimentProgramme:
    """Load the sole YAML owner of the final dissertation programme."""
    return load_final_experiment_programme(path)


def build_programme_registry(
    programme: FinalExperimentProgramme | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return the deterministic 43-row simulation-cell registry."""
    owner = programme or load_programme()
    return tuple(
        {
            "programme_order": cell.programme_order,
            "experiment_identifier": cell.experiment_identifier,
            "research_question_identifiers": ";".join(
                cell.research_questions
            ),
            "hypothesis_identifiers": ";".join(cell.hypotheses),
            "cell_order": cell.cell_order,
            "cell_identifier": cell.identifier,
            "portfolio_identifier": cell.portfolio_identifier,
            "shock_identifier": cell.shock_identifier,
            "capacity_profile_identifier": (
                cell.capacity_profile_identifier
            ),
            "maximum_liquidations_per_step": (
                cell.maximum_liquidations_per_step
            ),
            "confidence_scenario_identifier": (
                cell.confidence_scenario_identifier
            ),
            "hurdle_profile_identifier": cell.hurdle_profile_identifier,
            "risk_cost_rate": format(cell.risk_cost_rate, "f"),
            "oracle_treatment_identifier": (
                cell.oracle_treatment_identifier
            ),
            "oracle_delay_steps": cell.oracle_delay_steps,
            "replication_count": cell.replication_count,
            "execution_status": cell.execution_status,
            "row_checksum": cell.row_checksum,
        }
        for cell in owner.cells
    )


def specification_payload(
    programme: FinalExperimentProgramme | None = None,
) -> dict[str, Any]:
    """Build the complete, result-blind programme specification payload."""
    owner = programme or load_programme()
    experiments = []
    for experiment in owner.experiments:
        experiments.append(
            {
                "order": experiment.order,
                "identifier": experiment.identifier,
                "primary_research_question": (
                    experiment.primary_research_question
                ),
                "research_questions": list(experiment.research_questions),
                "primary_hypothesis": experiment.primary_hypothesis,
                "hypotheses": list(experiment.hypotheses),
                "replication_count": experiment.replication_count,
                "planned_cells": len(experiment.cells),
                "planned_simulations": sum(
                    cell.replication_count for cell in experiment.cells
                ),
                "execution_status": experiment.execution_status,
                "dependency_status": experiment.dependency_status,
                "cells": [
                    _canonical(asdict(cell)) for cell in experiment.cells
                ],
            }
        )
    return {
        "schema_version": 1,
        "purpose": (
            "Result-blind pre-registration of the final dissertation "
            "experiment programme."
        ),
        "programme_identifier": owner.identifier,
        "programme_identity": owner.programme_identity,
        "configuration": {
            "path": owner.path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": owner.configuration_checksum,
        },
        "parent_commit": owner.parent_commit,
        "package_boundary": owner.package_boundary,
        "package_taxonomy": {
            "path": owner.package_taxonomy_path,
            "sha256": owner.package_taxonomy_checksum,
            "snapshot_semantics": "parent_commit_blob",
        },
        "research_questions": [
            asdict(item) for item in owner.research_questions
        ],
        "hypotheses": [asdict(item) for item in owner.hypotheses],
        "frozen_inputs": _canonical(owner.frozen_inputs),
        "common_treatment": _canonical(owner.common_treatment),
        "experiment_order": [
            experiment.identifier for experiment in owner.experiments
        ],
        "experiments": experiments,
        "h4_synthesis": _canonical(asdict(owner.h4_synthesis)),
        "programme_totals": {
            "planned_core_cells": owner.planned_core_cells,
            "planned_core_simulations": owner.planned_core_simulations,
            "authorised_current_pass_simulations": (
                owner.authorised_current_pass_simulations
            ),
        },
        "final_validation_boundary": _canonical(
            owner.final_validation_boundary
        ),
        "outcome_based_selection": False,
        "result_blind": True,
        "runtime_adopted": owner.runtime_adopted,
    }


def _decision_payload(owner: FinalExperimentProgramme) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "programme_identifier": owner.identifier,
        "programme_identity": owner.programme_identity,
        "programme_preregistered": True,
        "experiment_a_authorised": True,
        "experiments_b_to_d_frozen_unexecuted": True,
        "experiment_e_status": (
            "blocked_pending_result_blind_oracle_delay_freeze"
        ),
        "h4_synthesis_status": "pending_evidence_synthesis",
        "portfolio_selection_performed": False,
        "shock_selection_performed": False,
        "model_selection_performed": False,
        "final_validation_data_used": False,
        "runtime_adopted": False,
    }


def _reproducibility_payload(
    owner: FinalExperimentProgramme,
) -> dict[str, Any]:
    source_checksums = {
        "programme_configuration": owner.configuration_checksum,
        "package_taxonomy_parent_snapshot": (
            owner.package_taxonomy_checksum
        ),
    }
    for name, values in owner.frozen_inputs.items():
        if isinstance(values, Mapping):
            for field, value in values.items():
                if field == "sha256" or field.endswith("_sha256"):
                    source_checksums[f"{name}.{field}"] = str(value)
    return {
        "schema_version": 1,
        "programme_identifier": owner.identifier,
        "programme_identity": owner.programme_identity,
        "source_checksums": source_checksums,
        "registry_rows": len(owner.cells),
        "registry_row_checksums": [
            cell.row_checksum for cell in owner.cells
        ],
        "deterministic_reconstruction": True,
        "experiment_results_included": False,
        "network_acquisition_performed": False,
        "final_validation_data_used": False,
        "runtime_adopted": False,
    }


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            _canonical(payload),
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _registry_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise ValueError("Programme registry cannot be empty.")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(rows[0]),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Existing pre-registration differs: {path}.")
        return
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
        delete=False,
    ) as handle:
        partial = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    try:
        os.replace(partial, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def write_programme_preregistration(
    programme: FinalExperimentProgramme | None = None,
    *,
    output_dir: Path | str = DEFAULT_PREREGISTRATION_DIR,
) -> dict[str, Any]:
    """Atomically write the four immutable master pre-registration artefacts."""
    owner = programme or load_programme()
    destination = Path(output_dir).resolve()
    artefacts = {
        "specification": (
            destination / "final_programme_specification.json",
            _json_bytes(specification_payload(owner)),
        ),
        "registry": (
            destination / "final_programme_registry.csv",
            _registry_bytes(build_programme_registry(owner)),
        ),
        "decision": (
            destination / "final_programme_decision.json",
            _json_bytes(_decision_payload(owner)),
        ),
        "reproducibility": (
            destination / "final_programme_reproducibility.json",
            _json_bytes(_reproducibility_payload(owner)),
        ),
    }
    result: dict[str, Any] = {
        "programme_identity": owner.programme_identity,
        "registry_rows": len(owner.cells),
        "artefacts": {},
    }
    for name, (path, content) in artefacts.items():
        _write_immutable(path, content)
        try:
            relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            relative_path = path.as_posix()
        result["artefacts"][name] = {
            "path": relative_path,
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return result


def update_programme_manifest(
    programme: FinalExperimentProgramme | None = None,
    *,
    manifest_path: Path | str = EXPERIMENT_MANIFEST_PATH,
    output_dir: Path | str = DEFAULT_PREREGISTRATION_DIR,
) -> dict[str, Any]:
    """Register exactly the four durable master-programme artefacts."""
    owner = programme or load_programme()
    destination = Path(output_dir).resolve()
    manifest = Path(manifest_path).resolve()
    filenames = (
        "final_programme_specification.json",
        "final_programme_registry.csv",
        "final_programme_decision.json",
        "final_programme_reproducibility.json",
    )
    paths = [destination / filename for filename in filenames]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"Missing master-programme artefacts: {missing}.")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    prefix = "data/provenance/experiments/final_programme/"
    preserved = [
        row
        for row in payload["artefacts"]
        if not str(row["path"]).startswith(prefix)
    ]
    records = []
    for path in paths:
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        records.append(
            {
                "classification": (
                    "pre_registered_final_dissertation_experiment_programme"
                ),
                "path": relative,
                "runtime_adopted": False,
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    combined = sorted(
        [*preserved, *records], key=lambda row: str(row["path"])
    )
    manifest_paths = [str(row["path"]) for row in combined]
    if len(manifest_paths) != len(set(manifest_paths)):
        raise ValueError("Experiment manifest contains duplicate paths.")
    payload["artefacts"] = combined
    payload["artefact_count"] = len(combined)
    content = _json_bytes(payload)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=manifest.parent,
        prefix=f".{manifest.name}.",
        suffix=".partial",
        delete=False,
    ) as handle:
        partial = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    try:
        os.replace(partial, manifest)
        directory_descriptor = os.open(manifest.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {
        "programme_identity": owner.programme_identity,
        "registered_artefacts": len(records),
        "manifest_artefact_count": len(combined),
        "manifest_sha256": _sha256_file(manifest),
    }
