"""Deterministic consolidation of Phase 2 candidate and interface evidence."""

from __future__ import annotations

import ast
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_loading import PROJECT_ROOT, sha256_file


DEFAULT_OUTPUT = (
    PROJECT_ROOT / "outputs/diagnostics/calibration/parameter_adoption"
)
PARAMETER_REGISTRY = (
    PROJECT_ROOT
    / "data/provenance/calibration/parameter_adoption/parameter_adoption_matrix.csv"
)
CALIBRATION_EVIDENCE = PROJECT_ROOT / "data/provenance/calibration"
PHASE2A_STATUS = (
    CALIBRATION_EVIDENCE / "market_gas_protocol/parameter_status.csv"
)
REGISTRIES = {
    "phase2a": (
        CALIBRATION_EVIDENCE
        / "market_gas_protocol/candidate_parameters.json"
    ),
    "phase2a_review": (
        CALIBRATION_EVIDENCE
        / "market_gas_protocol/reviewed_candidates.json"
    ),
    "phase2b": (
        CALIBRATION_EVIDENCE / "vaults/candidate_parameters.json"
    ),
    "phase2c": (
        CALIBRATION_EVIDENCE / "liquidations/candidate_parameters.json"
    ),
}
PROTECTED = (
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "docs/archive/historical_plans/DATA_ACQUISITION_PLAN.md",
)
ADOPTION_CLASSES = {
    "configuration_ready",
    "protocol_constant_ready",
    "configuration_ready_with_sensitivity",
    "requires_scalar_reduction",
    "requires_distribution_interface",
    "requires_regime_interface",
    "requires_collateral_specific_interface",
    "requires_time_varying_interface",
    "requires_new_model_mechanism",
    "scenario_only",
    "literature_required",
    "descriptive_only",
    "not_identifiable",
    "superseded_or_unused",
}
PARAMETER_HEADING_PATTERN = re.compile(
    r"^#### (4\.\d+\.\d+) (.+)$", re.MULTILINE
)
EXPECTED_PARAMETER_COUNT = 56


@dataclass(frozen=True)
class AdoptionReviewConfig:
    """Configuration for one local-only deterministic audit run."""

    output_dir: Path = DEFAULT_OUTPUT


CURRENT_VALUES = {
    "4.1.1": "200",
    "4.1.2": "100",
    "4.1.3": "42",
    "4.1.4": "true",
    "4.1.5": "None; implicit ETH-only portfolio",
    "4.1.6": "ETH in legacy default; ETH/BTC/STABLE supported",
    "4.1.7": "eth_price / oracle_eth_price legacy defaults",
    "4.2.1": "2000 USD for ETH; portfolio-specific otherwise",
    "4.2.2": "1.0 USD",
    "4.2.3": "1.0 ETH in default portfolio",
    "4.2.4": "5000 DAI",
    "4.2.5": "1000 DAI",
    "4.2.6": "2.0",
    "4.2.7": "0.25",
    "4.2.8": "0.05 absolute ratio points",
    "4.3.1": "generated or supplied path",
    "4.3.2": "0.0 per GBM time unit",
    "4.3.3": "0.80 per square-root GBM time unit",
    "4.3.4": "1/365",
    "4.3.5": "1e-8 USD",
    "4.3.6": "50 in generator; normally 30 in experiments",
    "4.3.7": "-0.43 crypto; -0.20 stable in multi-collateral scenarios",
    "4.3.8": "0.0 / 0.0",
    "4.3.9": "40",
    "4.3.10": "90",
    "4.3.11": "0.5",
    "4.3.12": "0 steps",
    "4.4.1": "1.5 global; collateral override supported",
    "4.4.2": "0.13 global; collateral override supported",
    "4.4.3": "100 USD/DAI per attempted liquidation",
    "4.4.4": "0.0 share of repaid debt",
    "4.4.5": "1.0 global; collateral override supported",
    "4.4.6": "None default; 2–20 in established experiments",
    "4.5.1": "0.99 USD/DAI",
    "4.5.2": "1.01 USD/DAI",
    "4.5.3": "0.97 USD/DAI",
    "4.5.4": "0.05 share",
    "4.5.5": "0.30 share",
    "4.5.6": "1000 DAI",
    "4.5.7": "1.0",
    "4.5.8": "0.5",
    "4.5.9": "0.1",
    "4.5.10": "2.0 multiplier",
    "4.6.1": "1.0 USD/DAI",
    "4.6.2": "0.02 per step",
    "4.6.3": "1.0",
    "4.6.4": "1.0",
    "4.6.5": "1.0",
    "4.6.6": "0.0005 USD/DAI per step",
    "4.6.7": "0.50 USD/DAI",
    "4.6.8": "1.50 USD/DAI",
    "4.6.9": "false",
    "4.6.10": "0.0",
    "4.6.11": "0.0",
    "4.6.12": "1.0",
    "4.6.13": "0.0",
}

PRIMARY_CLASSES = {
    "4.1.1": "scenario_only",
    "4.1.2": "configuration_ready_with_sensitivity",
    "4.1.3": "scenario_only",
    "4.1.4": "scenario_only",
    "4.1.5": "scenario_only",
    "4.1.6": "protocol_constant_ready",
    "4.1.7": "superseded_or_unused",
    "4.2.1": "configuration_ready_with_sensitivity",
    "4.2.2": "configuration_ready_with_sensitivity",
    "4.2.3": "configuration_ready_with_sensitivity",
    "4.2.4": "requires_distribution_interface",
    "4.2.5": "requires_distribution_interface",
    "4.2.6": "requires_distribution_interface",
    "4.2.7": "requires_distribution_interface",
    "4.2.8": "configuration_ready_with_sensitivity",
    "4.3.1": "requires_distribution_interface",
    "4.3.2": "configuration_ready_with_sensitivity",
    "4.3.3": "configuration_ready_with_sensitivity",
    "4.3.4": "scenario_only",
    "4.3.5": "scenario_only",
    "4.3.6": "scenario_only",
    "4.3.7": "scenario_only",
    "4.3.8": "scenario_only",
    "4.3.9": "scenario_only",
    "4.3.10": "scenario_only",
    "4.3.11": "scenario_only",
    "4.3.12": "literature_required",
    "4.4.1": "protocol_constant_ready",
    "4.4.2": "protocol_constant_ready",
    "4.4.3": "requires_scalar_reduction",
    "4.4.4": "requires_new_model_mechanism",
    "4.4.5": "configuration_ready",
    "4.4.6": "requires_scalar_reduction",
    "4.5.1": "configuration_ready_with_sensitivity",
    "4.5.2": "configuration_ready_with_sensitivity",
    "4.5.3": "configuration_ready_with_sensitivity",
    "4.5.4": "configuration_ready_with_sensitivity",
    "4.5.5": "requires_regime_interface",
    "4.5.6": "not_identifiable",
    "4.5.7": "scenario_only",
    "4.5.8": "scenario_only",
    "4.5.9": "scenario_only",
    "4.5.10": "not_identifiable",
    "4.6.1": "protocol_constant_ready",
    "4.6.2": "not_identifiable",
    "4.6.3": "not_identifiable",
    "4.6.4": "not_identifiable",
    "4.6.5": "not_identifiable",
    "4.6.6": "not_identifiable",
    "4.6.7": "scenario_only",
    "4.6.8": "scenario_only",
    "4.6.9": "scenario_only",
    "4.6.10": "not_identifiable",
    "4.6.11": "not_identifiable",
    "4.6.12": "not_identifiable",
    "4.6.13": "not_identifiable",
}

UNITS = {
    "4.1.1": "simulation steps",
    "4.1.2": "synthetic vaults",
    "4.1.3": "integer seed",
    "4.1.4": "boolean",
    "4.1.5": "portfolio object",
    "4.1.6": "categorical identifier",
    "4.1.7": "column identifier",
    "4.2.1": "USD per collateral unit",
    "4.2.2": "USD per DAI",
    "4.2.3": "share of system debt",
    "4.2.4": "DAI per vault",
    "4.2.5": "DAI per vault",
    "4.2.6": "collateral-value/debt multiple",
    "4.2.7": "collateral-value/debt multiple",
    "4.2.8": "absolute ratio difference",
    "4.3.1": "USD price path",
    "4.3.2": "log return per model time unit",
    "4.3.3": "log return per square-root model time unit",
    "4.3.4": "years per step in GBM",
    "4.3.5": "USD per collateral unit",
    "4.3.6": "simulation step",
    "4.3.7": "proportional price change",
    "4.3.8": "drift per model time unit",
    "4.3.9": "simulation step",
    "4.3.10": "simulation step",
    "4.3.11": "fraction of shock recovered",
    "4.3.12": "simulation steps",
    "4.4.1": "collateral-value/debt multiple",
    "4.4.2": "fraction of repaid debt",
    "4.4.3": "USD/DAI per attempted liquidation",
    "4.4.4": "fraction of repaid debt",
    "4.4.5": "fraction of one vault's debt",
    "4.4.6": "liquidations per simulation step",
    "4.5.1": "USD per DAI",
    "4.5.2": "USD per DAI",
    "4.5.3": "USD per DAI",
    "4.5.4": "share of all active vaults",
    "4.5.5": "share of all active vaults",
    "4.5.6": "DAI bad debt",
    "4.5.7": "dimensionless confidence index",
    "4.5.8": "dimensionless confidence index",
    "4.5.9": "dimensionless confidence index",
    "4.5.10": "dimensionless multiplier",
    "4.6.1": "USD per DAI",
    "4.6.2": "per simulation step",
    "4.6.3": "dimensionless response coefficient",
    "4.6.4": "dimensionless response coefficient",
    "4.6.5": "dimensionless response coefficient",
    "4.6.6": "USD per DAI per step",
    "4.6.7": "USD per DAI",
    "4.6.8": "USD per DAI",
    "4.6.9": "boolean",
    "4.6.10": "dimensionless response coefficient",
    "4.6.11": "dimensionless response coefficient",
    "4.6.12": "dimensionless drag coefficient",
    "4.6.13": "dimensionless confidence index",
}

CANONICAL_CANDIDATE_KEYS = {
    "n_vaults": "4.1.2",
    "initial_eth_price": "4.2.1",
    "collateral initial_price": "4.2.1",
    "initial_dai_price": "4.2.2",
    "target_debt_share": "4.2.3",
    "debt_mean": "4.2.4",
    "debt_std": "4.2.5",
    "collateral_ratio_mean": "4.2.6",
    "collateral_ratio_std": "4.2.7",
    "min_collateral_ratio_buffer": "4.2.8",
    "price_path": "4.3.1",
    "mu": "4.3.2",
    "sigma": "4.3.3",
    "shock_size": "4.3.7",
    "liquidation_ratio": "4.4.1",
    "liquidation_penalty": "4.4.2",
    "gas_cost": "4.4.3",
    "max_close_factor": "4.4.5",
    "max_liquidations_per_step": "4.4.6",
    "normal_lower_price": "4.5.1",
    "normal_upper_price": "4.5.2",
    "stress_lower_price": "4.5.3",
    "max_normal_liquidatable_share": "4.5.4",
    "max_stress_liquidatable_share": "4.5.5",
    "peg_price": "4.6.1",
}

IMPLEMENTED_CONFIG_FIELDS = {
    "SimulationConfig.n_steps": "4.1.1",
    "SimulationConfig.n_vaults": "4.1.2",
    "SimulationConfig.initial_eth_price": "4.2.1",
    "SimulationConfig.liquidation_ratio": "4.4.1",
    "SimulationConfig.oracle_delay_steps": "4.3.12",
    "SimulationConfig.debt_mean": "4.2.4",
    "SimulationConfig.debt_std": "4.2.5",
    "SimulationConfig.collateral_ratio_mean": "4.2.6",
    "SimulationConfig.collateral_ratio_std": "4.2.7",
    "SimulationConfig.random_seed": "4.1.3",
    "SimulationConfig.collateral_portfolio": "4.1.5",
    "CollateralConfig.name": "4.1.6",
    "CollateralConfig.initial_price": "4.2.1",
    "CollateralConfig.liquidation_ratio": "4.4.1",
    "CollateralConfig.liquidation_penalty": "4.4.2",
    "CollateralConfig.target_debt_share": "4.2.3",
    "CollateralConfig.max_close_factor": "4.4.5",
    "CollateralPortfolioConfig.name": "4.1.5",
    "CollateralPortfolioConfig.collaterals": "4.1.5",
    "LiquidationConfig.liquidation_penalty": "4.4.2",
    "LiquidationConfig.gas_cost": "4.4.3",
    "LiquidationConfig.risk_cost_rate": "4.4.4",
    "LiquidationConfig.max_close_factor": "4.4.5",
    "LiquidationConfig.max_liquidations_per_step": "4.4.6",
    "ConfidenceConfig.normal_lower_price": "4.5.1",
    "ConfidenceConfig.normal_upper_price": "4.5.2",
    "ConfidenceConfig.stress_lower_price": "4.5.3",
    "ConfidenceConfig.max_normal_liquidatable_share": "4.5.4",
    "ConfidenceConfig.max_stress_liquidatable_share": "4.5.5",
    "ConfidenceConfig.bad_debt_panic_threshold": "4.5.6",
    "ConfidenceConfig.normal_confidence": "4.5.7",
    "ConfidenceConfig.stress_confidence": "4.5.8",
    "ConfidenceConfig.panic_confidence": "4.5.9",
    "ConfidenceConfig.panic_selling_multiplier": "4.5.10",
    "DAIMarketConfig.peg_price": "4.6.1",
    "DAIMarketConfig.price_adjustment_speed": "4.6.2",
    "DAIMarketConfig.arbitrage_strength": "4.6.3",
    "DAIMarketConfig.above_peg_supply_strength": "4.6.4",
    "DAIMarketConfig.panic_strength": "4.6.5",
    "DAIMarketConfig.noise_std": "4.6.6",
    "DAIMarketConfig.min_price": "4.6.7",
    "DAIMarketConfig.max_price": "4.6.8",
    "DAIMarketConfig.enable_peg_recovery": "4.6.9",
    "DAIMarketConfig.arbitrage_recovery_strength": "4.6.10",
    "DAIMarketConfig.policy_feedback_strength": "4.6.11",
    "DAIMarketConfig.bad_debt_recovery_drag": "4.6.12",
    "DAIMarketConfig.min_recovery_confidence": "4.6.13",
    "PriceProcessConfig.n_steps": "4.1.1",
    "PriceProcessConfig.initial_price": "4.2.1",
    "PriceProcessConfig.random_seed": "4.1.3",
    "run_simulation.execute_liquidations": "4.1.4",
    "run_simulation.initial_dai_price": "4.2.2",
    "run_simulation.price_paths": "4.3.1",
    "generate_*_vaults.min_collateral_ratio_buffer": "4.2.8",
    "generate_gbm_price_path.mu": "4.3.2",
    "generate_gbm_price_path.sigma": "4.3.3",
    "generate_gbm_price_path.dt": "4.3.4",
    "generate_gbm_price_path.floor_price": "4.3.5",
    "generate_shock_price_path.shock_time": "4.3.6",
    "generate_shock_price_path.shock_size": "4.3.7",
    "generate_shock_price_path.pre_shock_drift": "4.3.8",
    "generate_shock_price_path.post_shock_drift": "4.3.8",
    "generate_shock_recovery_price_path.recovery_start": "4.3.9",
    "generate_shock_recovery_price_path.recovery_end": "4.3.10",
    "generate_shock_recovery_price_path.recovery_fraction": "4.3.11",
    "apply_oracle_delay.delay_steps": "4.3.12",
    "prepare_price_data.price_col": "4.1.7",
    "prepare_price_data.oracle_col": "4.1.7",
    "multi_collateral_scenario.crypto_crash_size": "4.3.7",
    "multi_collateral_scenario.stable_depeg_size": "4.3.7",
}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_text(
        path,
        frame.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return _relative(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload, indent=2, sort_keys=True, allow_nan=False,
            default=_json_default,
        ) + "\n",
    )


def authoritative_parameter_headings(
    text: str | None = None,
) -> list[tuple[str, str]]:
    """Return the compact parameter registry headings or parse supplied text."""
    if text is None:
        registry = pd.read_csv(PARAMETER_REGISTRY, dtype=str)
        headings = list(
            registry[["parameter_subsection", "parameter"]].itertuples(
                index=False, name=None
            )
        )
    else:
        headings = PARAMETER_HEADING_PATTERN.findall(text)
    if len(headings) != len(set(code for code, _ in headings)):
        raise ValueError("Duplicate authoritative parameter subsection")
    return headings


def discover_dataclass_fields() -> set[str]:
    """Read implemented configuration fields directly from source ASTs."""
    targets = {
        "src/dai_sim/model/simulation.py": {"SimulationConfig"},
        "src/dai_sim/model/collateral.py": {
            "CollateralConfig",
            "CollateralPortfolioConfig",
        },
        "src/dai_sim/model/liquidation.py": {"LiquidationConfig"},
        "src/dai_sim/model/confidence.py": {"ConfidenceConfig"},
        "src/dai_sim/model/market.py": {"DAIMarketConfig"},
        "src/dai_sim/model/collateral_prices.py": {"PriceProcessConfig"},
    }
    fields: set[str] = set()
    for relative_path, classes in targets.items():
        tree = ast.parse(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in classes:
                for statement in node.body:
                    if isinstance(statement, ast.AnnAssign) and isinstance(
                        statement.target, ast.Name
                    ):
                        fields.add(f"{node.name}.{statement.target.id}")
    return fields


def _serialise(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, allow_nan=False)
    return str(value)


def consolidate_candidates(
    payloads: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Preserve all Phase 2 candidates while standardising their audit fields."""
    source = payloads or {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in REGISTRIES.items()
    }
    phase2a = source["phase2a"]["candidates"]
    reviewed = source["phase2a_review"]["reviewed_candidates"]
    if len(phase2a) != len(reviewed):
        raise ValueError("Phase 2A original/review candidate count differs")
    rows: list[dict[str, Any]] = []
    for index, (original, review) in enumerate(zip(phase2a, reviewed, strict=True)):
        if review["candidate_index"] != index:
            raise ValueError("Phase 2A review candidate ordering differs")
        rows.append({
            "candidate_key": f"phase2a:{index:03d}",
            "phase": "2A",
            "parameter": original["estimate_name"],
            "canonical_parameter": _canonical_candidate_key(
                original.get("simulator_field", ""),
                original["estimate_name"],
            ),
            "simulator_field": original.get("simulator_field", ""),
            "estimate_value": _serialise(original.get("estimate_value")),
            "distribution_reference": original.get("distribution_reference", ""),
            "units": original.get("units", ""),
            "frequency": original.get("simulation_frequency", ""),
            "regime": original.get("regime_scope", ""),
            "collateral": original.get("collateral_scope", ""),
            "uncertainty": _serialise(original.get("uncertainty_measure")),
            "sample_size": _serialise(original.get("sample_size")),
            "provenance_class": original.get("provenance_classification", ""),
            "source_dataset": original.get("input_dataset", ""),
            "estimator": original.get("estimator", ""),
            "original_status": original.get("validation_status", ""),
            "review_status": review.get("review_status", ""),
            "recommended_treatment": review.get(
                "recommended_later_treatment", ""
            ),
            "adoption_gate": review.get("adoption_gate", ""),
            "original_candidate_sha256": review.get(
                "original_candidate_sha256", ""
            ),
            "source_registry": _relative(REGISTRIES["phase2a"]),
            "source_registry_sha256": sha256_file(REGISTRIES["phase2a"]),
            "notes": " | ".join(filter(None, [
                original.get("notes", ""),
                review.get("reviewer_notes", ""),
                review.get("unresolved_limitation", ""),
            ])),
        })
    for phase, key in (("2B", "phase2b"), ("2C", "phase2c")):
        for index, candidate in enumerate(source[key]["candidates"]):
            parameter = candidate.get("parameter_name", candidate.get("parameter"))
            simulator = candidate.get(
                "simulator_field",
                _phase2c_simulator_field(parameter),
            )
            notes = candidate.get("notes", "")
            if phase == "2C" and parameter == "auction_duration":
                provenance_warning = (
                    "Known source-registry inconsistency: this registry preserves "
                    "sample size 581, whereas the durable auction identity "
                    "(clipper_contract, auction_id) and the Phase 2C report establish "
                    "649 auctions. Preserve the registry value here; do not use the "
                    "duration sample size for adoption until a separately authorised "
                    "registry regeneration."
                )
                notes = " | ".join(filter(None, [notes, provenance_warning]))
            rows.append({
                "candidate_key": f"phase{phase.lower()}:{index:03d}",
                "phase": phase,
                "parameter": parameter,
                "canonical_parameter": _canonical_candidate_key(
                    simulator, parameter
                ),
                "simulator_field": simulator,
                "estimate_value": _serialise(candidate.get(
                    "estimate",
                    candidate.get("candidate value or distribution reference"),
                )),
                "distribution_reference": _serialise(candidate.get(
                    "sensitivity_alternatives",
                    candidate.get("candidate value or distribution reference")
                    if isinstance(
                        candidate.get("candidate value or distribution reference"),
                        str,
                    ) else "",
                )),
                "units": candidate.get("units", ""),
                "frequency": candidate.get(
                    "boundary_or_temporal_scope",
                    candidate.get("regime", ""),
                ),
                "regime": candidate.get("regime", ""),
                "collateral": candidate.get(
                    "collateral_scope",
                    candidate.get("collateral scope", ""),
                ),
                "uncertainty": _serialise(candidate.get(
                    "uncertainty_interval",
                    candidate.get("uncertainty"),
                )),
                "sample_size": _serialise(candidate.get(
                    "sample_size",
                    candidate.get("sample size"),
                )),
                "provenance_class": "empirical_review",
                "source_dataset": candidate.get(
                    "input_dataset",
                    candidate.get("empirical analogue", ""),
                ),
                "estimator": candidate.get("estimator", ""),
                "original_status": candidate.get(
                    "validation_status",
                    candidate.get("review status", ""),
                ),
                "review_status": candidate.get(
                    "review status",
                    candidate.get("validation_status", ""),
                ),
                "recommended_treatment": candidate.get(
                    "semantic compatibility",
                    candidate.get("model_interface_compatibility", ""),
                ),
                "adoption_gate": candidate.get(
                    "adoption prerequisite",
                    candidate.get("review_requirement", ""),
                ),
                "original_candidate_sha256": "",
                "source_registry": _relative(REGISTRIES[key]),
                "source_registry_sha256": sha256_file(REGISTRIES[key]),
                "notes": notes,
            })
    result = pd.DataFrame(rows)
    if result["candidate_key"].duplicated().any():
        raise ValueError("Candidate consolidation contains duplicate keys")
    return result


def _phase2c_simulator_field(parameter: str) -> str:
    return {
        "max_close_factor": (
            "LiquidationConfig.max_close_factor / "
            "CollateralConfig.max_close_factor"
        ),
        "max_liquidations_per_step": (
            "LiquidationConfig.max_liquidations_per_step"
        ),
        "max_stress_liquidatable_share": (
            "ConfidenceConfig.max_stress_liquidatable_share"
        ),
        "min_collateral_ratio_buffer": (
            "generate_*_vaults.min_collateral_ratio_buffer"
        ),
        "auction_execution_fraction": "auction_execution.missing",
        "liquidation_arrival_process": "liquidation_arrival.missing",
        "auction_duration": "auction_duration.missing",
    }.get(parameter, "")


def _canonical_candidate_key(simulator_field: str, parameter: str) -> str:
    lowered = simulator_field.lower()
    for name, code in CANONICAL_CANDIDATE_KEYS.items():
        if (
            name.lower() == parameter.lower()
            or re.search(rf"(?<![a-z_]){re.escape(name.lower())}(?![a-z_])", lowered)
        ):
            return code
    special = {
        "market_regime": "interface:market_regime",
        "liquidation.arrival_process": "interface:liquidation_arrival",
        "liquidation_arrival_process": "interface:liquidation_arrival",
        "liquidation.auction_duration": "interface:auction_execution",
        "auction_execution_fraction": "interface:auction_execution",
        "auction_duration": "interface:auction_execution",
    }
    return special.get(parameter, f"unmapped:{parameter}")


def _candidate_summary(
    candidates: pd.DataFrame, code: str, field: str
) -> tuple[str, str, str, str, str]:
    matched = candidates.loc[candidates["canonical_parameter"].eq(code)]
    if matched.empty:
        return "", "", "", "", ""
    summaries = [
        {
            "candidate_key": row["candidate_key"],
            "parameter": row["parameter"],
            "value": row["estimate_value"],
            "distribution": row["distribution_reference"],
            "status": row["review_status"],
            "regime": row["regime"],
            "collateral": row["collateral"],
        }
        for _, row in matched.iterrows()
    ]
    return (
        json.dumps(summaries, sort_keys=True),
        "; ".join(sorted(set(matched["phase"]))),
        "; ".join(sorted(filter(None, set(matched["uncertainty"])))),
        "; ".join(sorted(filter(None, set(matched["units"])))),
        "; ".join(sorted(filter(None, set(matched["frequency"])))),
    )


def _implementation_location(code: str) -> str:
    group = code.split(".")[1]
    return {
        "1": "SimulationConfig, CollateralPortfolioConfig or run_simulation",
        "2": "SimulationConfig, CollateralConfig and vault generators",
        "3": "price_process path generators and oracle-delay adapters",
        "4": "LiquidationConfig and liquidation execution",
        "5": "ConfidenceConfig and confidence classification",
        "6": "DAIMarketConfig and DAI price update",
    }[group]


def _scope(code: str) -> str:
    if code in {"4.1.6", "4.2.1", "4.2.3", "4.4.1", "4.4.2", "4.4.5"}:
        return "global with collateral-specific support"
    if code.startswith("4.5") or code.startswith("4.6"):
        return "global; confidence state may alter use"
    return "global"


def _frequency(code: str) -> str:
    if code.startswith("4.1") or code.startswith("4.2"):
        return "initialisation or run-level"
    if code.startswith("4.3"):
        return "per price-path step or scenario boundary"
    if code.startswith("4.4"):
        return "per liquidation attempt or simulation step"
    return "per simulation step"


def _semantics(code: str, field: str) -> str:
    special = {
        "4.2.8": "Lower clipping floor above the liquidation ratio during synthetic vault generation.",
        "4.3.1": "Exogenous collateral market/oracle path supplied to the simulation.",
        "4.4.3": "Fixed top-level USD/DAI cost subtracted from each keeper attempt.",
        "4.4.4": "Proportional reduced-form cost subtracted from keeper profit.",
        "4.4.5": "Maximum fraction of one vault's debt repaid in one simulated liquidation.",
        "4.4.6": "Global count cap on profitable liquidations executed in one step.",
        "4.5.4": "Largest liquidatable share still consistent with normal confidence.",
        "4.5.5": "Liquidatable share above which panic may be triggered.",
    }
    return special.get(
        code,
        f"Implemented runtime or experimental control for {field}.",
    )


def _existing_tests(code: str) -> str:
    """Describe presently available coverage without implying future tests exist."""
    group = code.split(".")[1]
    return {
        "1": (
            "module smoke checks in simulation.py/collateral.py; "
            "multi-collateral experiment diagnostics; no dedicated pytest for every field"
        ),
        "2": (
            "vault.py/simulation.py smoke checks; "
            "tests/calibration/test_vaults.py"
        ),
        "3": (
            "price_process.py smoke checks; tests/calibration/test_market_gas_protocol.py; "
            "tests/calibration/test_validation.py"
        ),
        "4": (
            "liquidation.py smoke checks; tests/calibration/test_market_gas_protocol.py; "
            "tests/calibration/test_liquidations.py"
        ),
        "5": (
            "confidence.py validation/smoke checks and Phase 2A threshold diagnostics; "
            "no dedicated pytest for every behavioural field"
        ),
        "6": (
            "dai_market.py validation/smoke checks and established experiment regressions; "
            "no dedicated pytest for every behavioural field"
        ),
    }[group]


def _treatment(code: str, adoption_class: str) -> tuple[str, str, str, str]:
    if code == "4.4.5":
        return (
            "Retain the field and review 1.0 in an empirical configuration; "
            "do not rename until a compatibility migration is separately approved.",
            "configuration only",
            "profit, partial/full liquidation and established-scenario regression tests",
            "high",
        )
    if code in {"4.2.4", "4.2.5", "4.2.6", "4.2.7"}:
        return (
            "Primary: collateral-specific empirical joint resampling. Fallback: "
            "collateral-specific truncated/lognormal marginals with an explicit "
            "dependence model.",
            "optional vault-initialisation distribution schema and sampler",
            "distribution fit, support, dependence, deterministic seed and ETH-only fallback tests",
            "high",
        )
    if code == "4.3.1":
        return (
            "Primary: aligned 168-hour moving blocks with 72–336-hour "
            "sensitivity. Fallback: current GBM with reviewed hourly moments.",
            "optional empirical price-process strategy",
            "block continuity, cross-collateral dependence, seed and GBM fallback tests",
            "medium",
        )
    if code == "4.4.3":
        return (
            "Reduce the clean successful-Take USD-cost distribution to a declared "
            "scalar only for the compatibility baseline; preserve gas units and "
            "gas price separately in the future sampler.",
            "none for scalar; optional gas sampler later",
            "zero-cost exclusion, units, regime sensitivity and keeper-profit tests",
            "high",
        )
    if code == "4.4.4":
        return (
            "Deprecate arbitrary tuning in favour of an empirically defined "
            "minimum expected-profit participation threshold; retain the legacy "
            "field until a migration is approved.",
            "keeper participation-threshold mechanism or semantic migration",
            "profit threshold, gas/risk separation and legacy regression tests",
            "medium",
        )
    if code == "4.4.6":
        return (
            "Keep deterministic capacity separate from endogenous liquidation "
            "demand; review an active-hour scalar before any hurdle sampler.",
            "none for scalar reduction; distribution interface for hurdle process",
            "capacity, backlog, zero-hour and clustered-demand tests",
            "medium",
        )
    if code == "4.5.5":
        return (
            "Preserve moderate USDC/SVB and severe Terra/CeFi thresholds as named "
            "evidence; select only within an explicit scenario until a regime "
            "override interface exists.",
            "optional regime-specific confidence thresholds",
            "threshold ordering, named-regime and withheld FTX validation tests",
            "medium",
        )
    if adoption_class == "protocol_constant_ready":
        return (
            "Historical replay uses effective-dated exact-ilk values; generic "
            "experiments use one declared baseline timestamp and explicit overrides.",
            "configuration mapping only for represented fields",
            "exact-ilk mapping, baseline timestamp and override tests",
            "high",
        )
    if adoption_class == "configuration_ready_with_sensitivity":
        return (
            "Review in a separate empirical configuration with the recorded "
            "uncertainty and current hand-set baseline retained.",
            "configuration only",
            "schema, units, sensitivity and baseline regression tests",
            "medium",
        )
    if adoption_class == "not_identifiable":
        return (
            "Estimate later by simulation matching or retain as an explicitly "
            "labelled scenario control; do not claim direct empirical identification.",
            "none until behavioural calibration is designed",
            "simulation-matching, ablation and withheld-validation tests",
            "low",
        )
    if adoption_class == "scenario_only":
        return (
            "Retain as a labelled experimental control, outside empirical adoption.",
            "none",
            "scenario schema and established-experiment regression tests",
            "low",
        )
    return (
        f"Resolve according to primary class {adoption_class}.",
        "interface-specific review",
        "unit, semantic and backward-compatibility tests",
        "low",
    )


def parameter_adoption_matrix(candidates: pd.DataFrame) -> pd.DataFrame:
    """Build one authoritative row for each of the 56 documented subsections."""
    headings = authoritative_parameter_headings()
    status = pd.read_csv(PHASE2A_STATUS)
    status["code"] = status["parameter_subsection"].str.extract(
        r"^(4\.\d+\.\d+)"
    )
    status_by_code = status.set_index("code")
    rows: list[dict[str, Any]] = []
    for code, title in headings:
        if code not in PRIMARY_CLASSES or code not in CURRENT_VALUES:
            raise ValueError(f"Missing adoption decision for {code}")
        source = status_by_code.loc[code]
        candidate, candidate_source, uncertainty, candidate_units, candidate_frequency = (
            _candidate_summary(candidates, code, source["simulator_field"])
        )
        adoption_class = PRIMARY_CLASSES[code]
        treatment, code_change, required_test, priority = _treatment(
            code, adoption_class
        )
        semantic_compatibility = (
            "mismatch: empirical evidence identifies a participation threshold, "
            "not an arbitrary proportional risk cost"
            if code == "4.4.4"
            else "compatible at protocol-close stage; auction execution remains distinct"
            if code == "4.4.5"
            else "compatible subject to stated units and scope"
        )
        interface_compatibility = (
            "no mechanics change"
            if adoption_class in {
                "configuration_ready",
                "configuration_ready_with_sensitivity",
                "protocol_constant_ready",
                "scenario_only",
                "literature_required",
                "superseded_or_unused",
            }
            else adoption_class
        )
        unit_compatibility = (
            "requires explicit conversion from hourly empirical moments to the "
            "configured GBM dt convention"
            if code in {"4.3.2", "4.3.3"}
            else "compatible"
        )
        frequency_compatibility = (
            "requires confirmation that one simulation step is one hour"
            if code in {"4.3.1", "4.3.2", "4.3.3", "4.4.6", "4.5.4", "4.5.5"}
            else "compatible or not applicable"
        )
        rows.append({
            "parameter_subsection": code,
            "parameter": title,
            "simulator_field": source["simulator_field"],
            "implementing_class_or_function": _implementation_location(code),
            "current_value": CURRENT_VALUES[code],
            "current_semantics": _semantics(code, source["simulator_field"]),
            "units": UNITS[code],
            "timestep_frequency": _frequency(code),
            "representation": (
                "distribution/path" if code == "4.3.1" else "scalar/control"
            ),
            "scope": _scope(code),
            "mechanics_or_experiment": (
                "experimental configuration"
                if adoption_class == "scenario_only" else "model mechanics"
            ),
            "current_tests": _existing_tests(code),
            "empirical_candidate": candidate,
            "candidate_source": candidate_source or source["source_dataset"],
            "uncertainty": uncertainty,
            "candidate_units": candidate_units,
            "candidate_frequency": candidate_frequency,
            "latest_candidate_status": (
                "; ".join(sorted(set(
                    candidates.loc[
                        candidates["canonical_parameter"].eq(code),
                        "review_status",
                    ]
                ))) or source["current_status"]
            ),
            "regime": (
                "; ".join(sorted(filter(None, set(
                    candidates.loc[
                        candidates["canonical_parameter"].eq(code), "regime"
                    ]
                )))) or "not regime-specific"
            ),
            "collateral": (
                "; ".join(sorted(filter(None, set(
                    candidates.loc[
                        candidates["canonical_parameter"].eq(code), "collateral"
                    ]
                )))) or _scope(code)
            ),
            "primary_adoption_class": adoption_class,
            "semantic_compatibility": semantic_compatibility,
            "interface_compatibility": interface_compatibility,
            "unit_compatibility": unit_compatibility,
            "frequency_compatibility": frequency_compatibility,
            "proposed_treatment": treatment,
            "required_code_change": code_change,
            "required_test": required_test,
            "adoption_priority": priority,
            "adopted": False,
            "notes": (
                "One row represents one authoritative subsection; grouped "
                "subsections retain all named implementation fields."
            ),
        })
    frame = pd.DataFrame(rows)
    validate_matrix(frame)
    return frame


def validate_matrix(frame: pd.DataFrame) -> None:
    """Enforce completeness and one primary adoption class per parameter."""
    if len(frame) != EXPECTED_PARAMETER_COUNT:
        raise ValueError("Authoritative parameter count is not 56")
    if frame["parameter_subsection"].duplicated().any():
        raise ValueError("Parameter subsection appears more than once")
    invalid = set(frame["primary_adoption_class"]) - ADOPTION_CLASSES
    if invalid or frame["primary_adoption_class"].isna().any():
        raise ValueError(f"Invalid or missing adoption class: {invalid}")
    missing = set(IMPLEMENTED_CONFIG_FIELDS.values()) - set(
        frame["parameter_subsection"]
    )
    if missing:
        raise ValueError(f"Implemented field is absent from matrix: {missing}")
    discovered = discover_dataclass_fields()
    missing_from_inventory = discovered - set(IMPLEMENTED_CONFIG_FIELDS)
    if missing_from_inventory:
        raise ValueError(
            f"Live dataclass field is absent from inventory: {missing_from_inventory}"
        )
    source_root = PROJECT_ROOT / "src"
    source_paths = sorted(source_root.glob("*.py"))
    source_paths.extend(sorted((source_root / "dai_sim").rglob("*.py")))
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in source_paths
    )
    absent_runtime_names = {
        field for field in IMPLEMENTED_CONFIG_FIELDS
        if field.split(".")[-1] not in source_text
    }
    if absent_runtime_names:
        raise ValueError(
            f"Inventoried runtime field is absent from source: {absent_runtime_names}"
        )
    if frame["adopted"].astype(bool).any():
        raise ValueError("Adoption review must not mark candidates adopted")


def interface_gaps(candidates: pd.DataFrame) -> pd.DataFrame:
    """Return the minimum justified model-interface backlog."""
    rows = [
        ("vault_joint_distribution", "debt_mean; debt_std; collateral_ratio_mean; collateral_ratio_std",
         "Global Gaussian moments lose heavy tails and joint dependence.",
         "requires_distribution_interface",
         "Optional collateral-specific empirical joint sampler; lognormal/truncated fallback.",
         "Tranche B", "high"),
        ("collateral_specific_vault_pools", "initial vault generator",
         "One global debt and ratio distribution is shared across collateral.",
         "requires_collateral_specific_interface",
         "Distribution specifications keyed by ETH/BTC/STABLE with exact-ilk provenance.",
         "Tranche B", "high"),
        ("empirical_market_blocks", "price_path",
         "No registry-backed aligned moving-block sampler exists.",
         "requires_distribution_interface",
         "168-hour aligned block sampler; 72–336-hour sensitivity; GBM fallback.",
         "Tranche C", "medium"),
        ("gas_process", "LiquidationConfig.gas_cost",
         "One USD scalar conflates gas units, gas price and regime.",
         "requires_distribution_interface",
         "Separate transaction gas units and hourly gas price; scalar compatibility mode.",
         "Tranche C", "medium"),
        ("regime_overrides", "confidence and empirical samplers",
         "Evidence distinguishes normal, moderate stress and severe stress, but "
         "the empirical two-state classifier is not a three-state causal model.",
         "requires_regime_interface",
         "Named normal/moderate/severe override blocks; retain endogenous confidence states.",
         "Tranche C", "medium"),
        ("liquidation_arrival_hurdle", "no current field",
         "Endogenous liquidatability is distinct from Bark demand and keeper capacity.",
         "requires_distribution_interface",
         "Optional hurdle demand overlay: activity probability plus conditional positive count.",
         "Tranche D", "low"),
        ("auction_execution", "no current field",
         "Full Vat.grab closure coexists with partial and multiple Takes.",
         "requires_new_model_mechanism",
         "Defer from core; optional auction-friction extension if required.",
         "Future work", "low"),
        ("keeper_participation_threshold", "LiquidationConfig.risk_cost_rate",
         "Arbitrary proportional risk cost is not the empirical minimum-profit concept.",
         "requires_new_model_mechanism",
         "Add explicit minimum expected profit or participation threshold; retain legacy field.",
         "Tranche D", "medium"),
        ("protocol_replay", "partial CollateralConfig mapping",
         "Debt ceilings, dust, stability fees and auction-stopped histories are "
         "not all consumed by current mechanics.",
         "requires_time_varying_interface",
         "Historical replay adapter only; generic experiments use a baseline timestamp.",
         "Future replay", "low"),
        ("behavioural_calibration", "15 model-calibration parameters",
         "Direct observations do not identify latent confidence and DAI response coefficients.",
         "not_identifiable",
         "Simulation matching, sensitivity, ablation and withheld FTX validation.",
         "Tranche E", "medium"),
    ]
    return pd.DataFrame(rows, columns=[
        "gap_id", "affected_fields", "current_gap", "required_interface_class",
        "minimum_design", "implementation_tranche", "priority",
    ])


def implementation_tranches() -> pd.DataFrame:
    """Return the dependency-ordered implementation plan."""
    rows = [
        ("A", 1, "", "Configuration-only empirical bundle",
         "max_close_factor; liquidation ratios; liquidation penalties; initial prices; "
         "target debt shares; reviewed scalar thresholds",
         "configuration loader; experiments; existing config classes",
         "schema, units, exact-ilk mapping, established baseline regression",
         "Withheld FTX is validation only; stop if any field needs mechanics changes.",
         "Existing defaults and Experiments 1–5 remain unchanged unless empirical config is selected."),
        ("B", 2, "A", "Distribution-aware vault initialisation",
         "debt and collateral-ratio joint distributions; collateral-specific pools",
         "vault.py; simulation.py; collateral.py; new optional schema adapter",
         "support, tails, dependence, seed, small-ilk fallback and ETH-only equivalence",
         "Stop if empirical pools are too small or generated states violate invariants.",
         "Global Gaussian path remains the default fallback."),
        ("C", 3, "A", "Empirical market and gas sampling",
         "aligned moving blocks; regime-labelled gas distributions; gas units and prices",
         "price_process.py; liquidation.py adapter; simulation.py",
         "block boundaries, correlation, seeds, zero-gas exclusion and unit reconciliation",
         "Stop if hourly frequency or gas-unit conversion is ambiguous.",
         "GBM and scalar gas paths remain supported."),
        ("D", 4, "B,C", "Liquidation demand and throughput separation",
         "optional hurdle demand; capacity scalar/distribution; minimum-profit threshold",
         "liquidation.py; simulation.py; optional arrival module",
         "liquidatable/Bark/grab/Take distinctions, backlog, capacity and profit tests",
         "Stop if endogenous liquidatability is double-counted.",
         "Deterministic capacity and current one-stage liquidation remain available."),
        ("E", 5, "A,B,C,D", "Confidence and behavioural calibration",
         "15 simulation-calibration controls; confidence, panic, arbitrage and recovery",
         "confidence.py; dai_market.py; calibration runner",
         "SMM/minimum-distance, ablation, sensitivity and withheld FTX validation",
         "Stop if FTX enters fitting or latent coefficients are presented as direct estimates.",
         "Existing hand-set behaviour remains the reference baseline."),
    ]
    return pd.DataFrame(rows, columns=[
        "tranche", "order", "depends_on", "name", "fields", "modules",
        "required_tests", "stop_conditions", "backward_compatibility",
    ])


def validate_tranche_order(frame: pd.DataFrame) -> None:
    order = dict(zip(frame["tranche"], frame["order"], strict=True))
    for _, row in frame.iterrows():
        dependencies = [item for item in str(row["depends_on"]).split(",") if item]
        if any(order[item] >= row["order"] for item in dependencies):
            raise ValueError("Implementation tranche dependency is not ordered")


def validation_plan() -> pd.DataFrame:
    rows = [
        ("unit_tests", "Each new schema, conversion, sampler and decision function", "All deterministic and boundary cases pass", "every tranche"),
        ("deterministic_seeds", "Repeat identical empirical and fallback runs", "Byte-identical candidate artefacts and equal simulation arrays", "B–E"),
        ("schema_validation", "Parse illustrative/future configuration before execution", "Units, frequency, collateral and representation explicit", "A–E"),
        ("distributional_checks", "Compare generated and empirical quantiles, tails and dependence", "Pre-specified tolerance or documented sensitivity failure", "B–D"),
        ("economic_invariants", "Debt, collateral, liquidation, bad-debt and keeper-profit accounting", "No invariant regression or silent clipping", "A–E"),
        ("baseline_regression", "Current hand-set configuration and Experiments 1–5", "Existing seeded outputs unchanged under legacy mode", "A–E"),
        ("historical_episode_validation", "Representative windows not used for the candidate under test", "Direction, magnitude and persistence diagnostics reported", "B–E"),
        ("withheld_ftx", "November 2022 withheld interval", "Validation only; never enters fitting or threshold selection", "C–E"),
        ("sensitivity_analysis", "Candidate intervals, 72–336-hour blocks and scalar reductions", "Conclusions robust or explicitly qualified", "A–E"),
        ("ablation_tests", "Remove each new mechanism independently", "Incremental effect is interpretable and attributable", "B–E"),
        ("baseline_comparison", "Empirical configuration versus current hand-set baseline", "All directional changes and failures reported", "A–E"),
    ]
    return pd.DataFrame(rows, columns=[
        "validation_type", "procedure", "pass_condition", "applicable_tranches"
    ])


def _configuration_ready(matrix: pd.DataFrame) -> pd.DataFrame:
    ready_classes = {
        "configuration_ready",
        "configuration_ready_with_sensitivity",
        "protocol_constant_ready",
    }
    result = matrix.loc[
        matrix["primary_adoption_class"].isin(ready_classes)
        & matrix["empirical_candidate"].ne("")
    ].copy()
    preferred = {
        "4.1.2": ("500", "+400 vaults"),
        "4.2.3": (
            '{"ETH": 0.8483941126796408, "BTC": 0.1516058873203592}',
            "ETH -0.151606; BTC +0.151606 versus implicit ETH-only default",
        ),
        "4.2.8": ("0.4927578319238673", "+0.4427578319238673"),
        "4.3.2": (
            '{"ETH": 2.0683874929400927e-05, "WBTC": '
            '2.8097430039838248e-05, "STABLE_proxy_USDC": '
            '-9.961245747512497e-08}',
            "not meaningful until hourly/GBM-time conversion is fixed",
        ),
        "4.3.3": (
            '{"ETH": 0.006082614959678903, "WBTC": '
            '0.0047429127302706054, "STABLE_proxy_USDC": '
            '0.0006672093036257861}',
            "not meaningful until hourly/GBM-time conversion is fixed",
        ),
        "4.4.1": (
            "exact-ilk value effective at a pre-registered baseline timestamp",
            "timestamp- and ilk-specific; no pooled numerical difference",
        ),
        "4.4.2": (
            "exact-ilk value effective at a pre-registered baseline timestamp",
            "timestamp- and ilk-specific; no pooled numerical difference",
        ),
        "4.4.5": ("1.0", "0.0 versus default; +0.5 versus common 0.5 experiment"),
        "4.5.1": ("0.9992875", "+0.0092875"),
        "4.5.2": ("1.0030259166666666", "-0.0069740833333334"),
        "4.5.3": ("0.9967380166666668", "+0.0267380166666668"),
        "4.5.4": ("0.0", "-0.05"),
    }
    result["proposed_value"] = result["parameter_subsection"].map(
        lambda code: preferred.get(code, (result.loc[
            result["parameter_subsection"].eq(code), "empirical_candidate"
        ].iloc[0], "review individually"))[0]
    )
    result["numerical_difference"] = result["parameter_subsection"].map(
        lambda code: preferred.get(code, ("", "review individually"))[1]
    )
    result["expected_directional_effect"] = result["proposed_treatment"]
    result["adoption_risk"] = np.where(
        result["primary_adoption_class"].eq("configuration_ready"),
        "medium: existing scenarios may use different deliberate values",
        "medium-to-high: sensitivity or effective-time choice required",
    )
    result["baseline_or_empirical_config"] = (
        "separate empirical configuration; current baseline retained"
    )
    columns = [
        "parameter_subsection", "parameter", "simulator_field", "current_value",
        "proposed_value", "candidate_source", "uncertainty", "units",
        "primary_adoption_class", "semantic_compatibility",
        "unit_compatibility", "frequency_compatibility",
        "numerical_difference", "expected_directional_effect", "adoption_risk",
        "required_test", "baseline_or_empirical_config",
    ]
    return result[columns]


def _metadata_outputs(output_dir: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for path in sorted(output_dir.iterdir()):
        if not path.is_file() or path.name == "adoption_review_metadata.json":
            continue
        if path.suffix == ".csv":
            frame = pd.read_csv(path)
            dimensions = [len(frame), len(frame.columns)]
        else:
            json.loads(path.read_text(encoding="utf-8"))
            dimensions = None
        records[path.name] = {
            "path": _relative(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "dimensions": dimensions,
        }
    return records


def run_adoption_review(
    config: AdoptionReviewConfig = AdoptionReviewConfig(),
) -> dict[str, Any]:
    """Generate all adoption-review artefacts without touching configuration."""
    protected = tuple(path for path in PROTECTED if path.is_file())
    protected_initial = {_relative(path): sha256_file(path) for path in protected}
    registry_hashes = {
        name: sha256_file(path) for name, path in REGISTRIES.items()
    }
    candidates = consolidate_candidates()
    if len(candidates) != 80:
        raise ValueError("Expected 80 consolidated Phase 2 candidates")
    matrix = parameter_adoption_matrix(candidates)
    gaps = interface_gaps(candidates)
    ready = _configuration_ready(matrix)
    tranches = implementation_tranches()
    validate_tranche_order(tranches)
    validations = validation_plan()
    outputs = {
        "parameter_adoption_matrix.csv": matrix,
        "candidate_consolidation.csv": candidates,
        "model_interface_gaps.csv": gaps,
        "configuration_ready_candidates.csv": ready,
        "proposed_implementation_tranches.csv": tranches,
        "adoption_validation_plan.csv": validations,
    }
    for name, frame in outputs.items():
        _write_csv(config.output_dir / name, frame)
    protected_final = {_relative(path): sha256_file(path) for path in protected}
    if protected_initial != protected_final:
        raise ValueError("Protected file changed during adoption review")
    metadata = {
        "phase": "parameter_adoption_review",
        "status": "plan_only_no_candidates_adopted",
        "authoritative_parameter_count": len(matrix),
        "count_reconciliation": (
            "56 numbered subsections are authoritative. The earlier count of 55 "
            "missed one grouped/multiline heading (4.3.7); no simulator field "
            "was added or removed by this audit."
        ),
        "consolidated_candidate_count": len(candidates),
        "candidate_counts": {
            key: int(value)
            for key, value in candidates["phase"].value_counts().sort_index().items()
        },
        "known_provenance_conflicts": [
            {
                "source": _relative(REGISTRIES["phase2c"]),
                "candidate": "auction_duration",
                "preserved_registry_sample_size": 581,
                "durable_composite_key_sample_size": 649,
                "treatment": (
                    "Preserve the source registry unchanged and exclude the "
                    "sample-size field from adoption until separately authorised "
                    "regeneration."
                ),
            }
        ],
        "adoption_class_totals": {
            key: int(value)
            for key, value in (
                matrix["primary_adoption_class"].value_counts().sort_index().items()
            )
        },
        "implemented_field_count": len(IMPLEMENTED_CONFIG_FIELDS),
        "live_dataclass_field_count": len(discover_dataclass_fields()),
        "implemented_fields": IMPLEMENTED_CONFIG_FIELDS,
        "registry_checksums": registry_hashes,
        "protected_initial_sha256": protected_initial,
        "protected_final_sha256": protected_final,
        "configuration_written": False,
        "simulator_mechanics_written": False,
        "candidate_adopted": False,
        "ftx_used_for_calibration": False,
        "recommended_next_tranche": (
            "Tranche A: create a separate empirical configuration containing "
            "only semantically compatible existing fields, with legacy defaults "
            "and Experiments 1–5 unchanged."
        ),
        "outputs": _metadata_outputs(config.output_dir),
        "tool_sha256": sha256_file(Path(__file__)),
    }
    metadata_path = config.output_dir / "adoption_review_metadata.json"
    _write_json(metadata_path, metadata)
    return {
        "output_dir": _relative(config.output_dir),
        "metadata_path": _relative(metadata_path),
        "parameter_count": len(matrix),
        "candidate_count": len(candidates),
        "configuration_ready_count": len(ready),
        "adoption_class_totals": metadata["adoption_class_totals"],
        "output_checksums": {
            name: record["sha256"]
            for name, record in metadata["outputs"].items()
        },
    }
