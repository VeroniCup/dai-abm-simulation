"""Pre-registered selected robustness layer for the final experiments.

This module varies only population size, empirical market-block length and the
registered keeper hurdle.  It composes the frozen experiment mechanics and
retains the 24-hour DAI residual owner.  It is evaluative and cannot update a
runtime profile, parameter or scenario.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator

import numpy as np
import pandas as pd
import yaml

from dai_sim.experiments.final import (
    correlated_stress as experiment_b,
    idiosyncratic_diversification as experiment_a,
    shared_keeper_capacity as experiment_d,
    stable_collateral_tradeoff as experiment_c,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs
from dai_sim.inputs.integrated_profile import resolve_integrated_empirical_eth_profile
from dai_sim.inputs.liquidations import (
    load_liquidation_arrival_pool,
)
from dai_sim.inputs.multicollateral import (
    FAMILY_ORDER,
    FTX_END,
    FTX_START,
    SVB_END,
    SVB_START,
    largest_remainder_counts,
    load_final_market_pool,
    resolve_multicollateral_inputs,
)
from dai_sim.model.vault import Vault
from dai_sim.validation import multicollateral as multicollateral_validation


PARENT_COMMIT = "26280a950286e4b0b88ca931a1ad1f24406f984b"
MASTER_PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
PROTECTED_EXPERIMENT_IDENTITIES = {
    "A": "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb",
    "B": "e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83",
    "C": "cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b",
    "D": "b324c31be7ef6dd7f61e504709b2086b0e88ce181c177f25dcaad182095c17e3",
    "E": "67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8",
}
H4_SYNTHESIS_IDENTITY = (
    "06f56e77ad56416483b2c010f0e63375b664baeff1830ec6306e37858c5920cb"
)
ORACLE_DELAY_REGISTRY_IDENTITY = (
    "2e562ef2618e472ce3b0551addf2596ddbe137910fa6d2ad5884ae71c674e46d"
)
REGISTRY_PATH = REPOSITORY_ROOT / "config/sensitivities/final_robustness_registry.yaml"
EVIDENCE_DIR = REPOSITORY_ROOT / "data/provenance/experiments/final/selected_robustness"
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs/experiments/final/selected_robustness"
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
EXPERIMENT_NAMESPACE = "registered-selected-robustness-v1"

REPLICATIONS = 64
TOTAL_HOURS = 768
TOTAL_DEBT_DAI = 2_500_000.0
TARGET_SYSTEM_COLLATERAL_RATIO = 3.6089387701260205
CAPACITY = 26
POPULATIONS = (250, 500, 1000)
MARKET_BLOCK_HOURS = (72, 168, 336)
RECOVERY_HOURS = (12, 24, 48)
SETTING_ORDER = (
    "baseline",
    "population_250",
    "population_1000",
    "market_block_72",
    "market_block_336",
    "keeper_hurdle_low",
    "keeper_hurdle_high",
)
CONTRAST_ORDER = ("R-A", "R-B", "R-C", "R-D")
PRIMARY_METRICS = (
    "backlog_area_share",
    "liquidated_debt_share",
    "maximum_unresolved_tab_share",
)
R_D_METRICS = (
    "stable_attributed_liquidated_debt_share",
    "stable_exposure_normalised_liquidated_debt",
)
COMPACT_FILENAMES = (
    "selected_robustness_specification.json",
    "selected_robustness_registry.csv",
    "selected_robustness_cell_summary.csv",
    "selected_robustness_contrast_summary.csv",
    "selected_robustness_recovery_definition_sensitivity.csv",
    "selected_robustness_decision.json",
    "selected_robustness_reproducibility.json",
    "selected_robustness_benchmark.json",
)


def _canonical(value: Any) -> Any:
    if isinstance(value, Path):
        return value.relative_to(REPOSITORY_ROOT).as_posix()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _json_bytes(payload: Any, *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            _canonical(payload),
            indent=2 if pretty else None,
            sort_keys=True,
            separators=None if pretty else (",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + ("\n" if pretty else "")
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    output = io.StringIO(newline="")
    frame.to_csv(output, index=False, lineterminator="\n")
    return output.getvalue().encode("utf-8")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_bytes(path, _json_bytes(payload, pretty=True))


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """Load and validate the immutable 56-cell OAT registry."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("registry_id") != "registered_selected_robustness":
        raise ValueError("Selected robustness registry identity differs.")
    if raw.get("parent_commit") != PARENT_COMMIT:
        raise ValueError("Selected robustness parent commit differs.")
    if raw.get("master_programme_identity") != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Master programme identity differs.")
    if raw.get("protected_experiment_identities") != PROTECTED_EXPERIMENT_IDENTITIES:
        raise ValueError("Protected experiment identities differ.")
    if int(raw.get("replications", 0)) != REPLICATIONS:
        raise ValueError("Robustness replication count differs.")
    if [int(value) for value in raw["population_coordinates"]] != list(POPULATIONS):
        raise ValueError("Population coordinates differ.")
    if [int(value) for value in raw["market_block_coordinates_hours"]] != list(MARKET_BLOCK_HOURS):
        raise ValueError("Market-block coordinates differ.")
    if [item["id"] for item in raw["settings"]] != list(SETTING_ORDER):
        raise ValueError("OAT setting order differs.")
    if [item["id"] for item in raw["contrast_families"]] != list(CONTRAST_ORDER):
        raise ValueError("Contrast-family order differs.")
    if raw.get("no_full_factorial") is not True or raw.get("no_retuning") is not True:
        raise ValueError("Robustness design must remain OAT and non-retuning.")
    return raw


@dataclass(frozen=True)
class RobustnessCell:
    order: int
    identifier: str
    contrast_family: str
    shock: str
    role: str
    portfolio: str
    setting: str
    population: int
    market_block_hours: int
    hurdle: str
    risk_cost_rate: float
    replication_count: int
    row_checksum: str


def build_cell_registry() -> tuple[RobustnessCell, ...]:
    owner = load_registry()
    hurdles = owner["keeper_hurdles"]
    rows: list[RobustnessCell] = []
    for contrast in owner["contrast_families"]:
        for setting in owner["settings"]:
            for role, portfolio in (
                ("reference", contrast["reference_portfolio"]),
                ("treatment", contrast["treatment_portfolio"]),
            ):
                base = {
                    "order": len(rows) + 1,
                    "identifier": f"{contrast['id']}__{setting['id']}__{role}",
                    "contrast_family": contrast["id"],
                    "shock": contrast["shock"],
                    "role": role,
                    "portfolio": portfolio,
                    "setting": setting["id"],
                    "population": int(setting["population"]),
                    "market_block_hours": int(setting["market_block_hours"]),
                    "hurdle": setting["hurdle"],
                    "risk_cost_rate": float(hurdles[setting["hurdle"]]["risk_cost_rate"]),
                    "replication_count": REPLICATIONS,
                }
                rows.append(RobustnessCell(**base, row_checksum=_payload_sha256(base)))
    if len(rows) != 56 or len({row.identifier for row in rows}) != 56:
        raise ValueError("Selected robustness registry must contain 56 cells.")
    return tuple(rows)


def seed_record(replication: int) -> dict[str, Any]:
    return {
        "namespace": EXPERIMENT_NAMESPACE,
        "replication": replication,
        **{
            stream: derive_seed(replication, stream)
            for stream in (
                "initialisation_master",
                "market_block_uniforms",
                "keeper_gas_units",
                "liquidation_arrivals",
                "stage1_residual_blocks",
            )
        },
    }


def derive_seed(replication: int, stream: str, substream: str = "") -> int:
    allowed = {
        "initialisation_master",
        "vault_ETH",
        "vault_WBTC",
        "vault_STABLE",
        "market_block_uniforms",
        "keeper_gas_units",
        "liquidation_arrivals",
        "stage1_residual_blocks",
    }
    if stream not in allowed:
        raise ValueError(f"Unregistered selected-robustness stream: {stream}.")
    digest = hashlib.sha256(
        f"{EXPERIMENT_NAMESPACE}|{replication}|{stream}|{substream}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def seed_registry_checksum() -> str:
    return _payload_sha256([seed_record(value) for value in range(REPLICATIONS)])


def _population_counts(portfolio_payload: Mapping[str, Any], portfolio: str, population: int) -> dict[str, int]:
    definition = multicollateral_validation._portfolio_payload(portfolio_payload, portfolio)
    shares = {family: float(definition["target_debt_shares"][family]) for family in FAMILY_ORDER}
    return largest_remainder_counts(shares=shares, total_count=population, family_order=FAMILY_ORDER)


def _draw_maximum_streams(
    replication: int,
    attempt: int,
    collateral: Mapping[str, Any],
    portfolios: Mapping[str, Any],
    pool: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[dict[str, Any]]]:
    required: dict[str, dict[str, int]] = {"ETH": {}, "WBTC": {}}
    portfolio_ids = tuple(dict.fromkeys(cell.portfolio for cell in build_cell_registry()))
    for family in ("ETH", "WBTC"):
        owner = multicollateral_validation._family_payload(collateral, family)
        required[family] = {ilk: 0 for ilk in owner["exact_ilks"]}
        for population in POPULATIONS:
            for portfolio in portfolio_ids:
                family_count = _population_counts(portfolios, portfolio, population)[family]
                counts = multicollateral_validation._within_family_ilk_counts(owner, family_count)
                for ilk, count in counts.items():
                    required[family][ilk] = max(required[family][ilk], int(count))
    empirical: dict[str, dict[str, list[dict[str, Any]]]] = {"ETH": {}, "WBTC": {}}
    master = derive_seed(replication, "initialisation_master")
    for family in ("ETH", "WBTC"):
        owner = multicollateral_validation._family_payload(collateral, family)
        rng = np.random.default_rng(
            derive_seed(replication, f"vault_{family}", f"master:{master}:attempt:{attempt}")
        )
        for ilk, count in required[family].items():
            values = multicollateral_validation._sample_empirical_family(
                pool=pool,
                family=family,
                family_config=experiment_a._single_ilk_config(owner, ilk),
                count=count,
                rng=rng,
            )
            for position, row in enumerate(values):
                row["family_stream_position"] = position
            empirical[family][ilk] = values
    stable_max = max(
        _population_counts(portfolios, portfolio, population)["STABLE"]
        for population in POPULATIONS
        for portfolio in portfolio_ids
    )
    stable_rng = np.random.default_rng(
        derive_seed(replication, "vault_STABLE", f"master:{master}:attempt:{attempt}")
    )
    stable = multicollateral_validation._sample_stable_family(
        family_config=multicollateral_validation._family_payload(collateral, "STABLE"),
        count=stable_max,
        rng=stable_rng,
    )
    for position, row in enumerate(stable):
        row["family_stream_position"] = position
    return empirical, stable


def _normalise_state(
    *,
    portfolio: str,
    population: int,
    replication: int,
    attempt: int,
    empirical: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    stable: Sequence[Mapping[str, Any]],
    collateral: Mapping[str, Any],
    portfolios: Mapping[str, Any],
) -> experiment_a.NestedInitialisation:
    definition = multicollateral_validation._portfolio_payload(portfolios, portfolio)
    counts = _population_counts(portfolios, portfolio, population)
    shares = {family: float(definition["target_debt_shares"][family]) for family in FAMILY_ORDER}
    rows: list[dict[str, Any]] = []
    for family in ("ETH", "WBTC"):
        owner = multicollateral_validation._family_payload(collateral, family)
        ilk_counts = multicollateral_validation._within_family_ilk_counts(owner, counts[family])
        for ilk in owner["exact_ilks"]:
            rows.extend(deepcopy(list(empirical[family][ilk][: ilk_counts[ilk]])))
    rows.extend(deepcopy(list(stable[: counts["STABLE"]])))
    frame = pd.DataFrame(rows)
    if len(frame) != population:
        raise ValueError("Population-specific initialisation count differs.")
    frame.insert(0, "vault_id", np.arange(population, dtype=int))
    frame["debt_dai"] = 0.0
    for family in FAMILY_ORDER:
        mask = frame["family"].eq(family)
        if not mask.any():
            continue
        raw_total = float(frame.loc[mask, "raw_debt_dai"].sum())
        frame.loc[mask, "debt_dai"] = frame.loc[mask, "raw_debt_dai"] * TOTAL_DEBT_DAI * shares[family] / raw_total
    raw_ratio = float(np.sum(frame["debt_dai"] * frame["raw_collateral_ratio"]) / TOTAL_DEBT_DAI)
    frame["collateral_ratio"] = frame["raw_collateral_ratio"] * TARGET_SYSTEM_COLLATERAL_RATIO / raw_ratio
    initial_prices = {
        family: float(multicollateral_validation._family_payload(collateral, family)["initial_price_usd"])
        for family in FAMILY_ORDER
    }
    frame["initial_price_usd"] = frame["family"].map(initial_prices)
    frame["collateral_amount"] = frame["debt_dai"] * frame["collateral_ratio"] / frame["initial_price_usd"]
    margins = frame["collateral_ratio"] - frame["liquidation_ratio"]
    if (margins <= 0.0).any():
        raise ValueError("Population state contains an initially unsafe vault.")
    if not math.isclose(float(frame["debt_dai"].sum()), TOTAL_DEBT_DAI, abs_tol=1e-6):
        raise ValueError("Population total debt changed.")
    final_ratio = float(np.sum(frame["debt_dai"] * frame["collateral_ratio"]) / TOTAL_DEBT_DAI)
    if not math.isclose(final_ratio, TARGET_SYSTEM_COLLATERAL_RATIO, abs_tol=1e-10):
        raise ValueError("Population collateralisation changed.")
    vaults = tuple(
        Vault(
            vault_id=int(row.vault_id),
            owner_id=int(row.vault_id),
            collateral_amount=float(row.collateral_amount),
            debt_dai=float(row.debt_dai),
            liquidation_ratio=float(row.liquidation_ratio),
            collateral_type=str(row.model_family),
            exact_ilk=None if pd.isna(row.exact_ilk) else str(row.exact_ilk),
        )
        for row in frame.itertuples(index=False)
    )
    stream = frame[["family", "exact_ilk", "source_row_id", "family_stream_position"]].where(pd.notna(frame[["family", "exact_ilk", "source_row_id", "family_stream_position"]]), None)
    return experiment_a.NestedInitialisation(
        portfolio=portfolio,
        replication=replication,
        accepted_attempt=attempt,
        vaults=vaults,
        sampled=frame,
        identity=multicollateral_validation._initialisation_identity(frame),
        stream_identity=_payload_sha256(stream.to_dict(orient="records")),
        final_system_collateral_ratio=final_ratio,
        minimum_liquidation_distance=float(margins.min()),
    )


def initialise_nested_populations(replication: int) -> dict[int, dict[str, experiment_a.NestedInitialisation]]:
    """Draw one maximum stream and use population/family/ilk prefixes."""
    collateral, portfolios, pool = experiment_a._design_payloads()
    portfolio_ids = tuple(dict.fromkeys(cell.portfolio for cell in build_cell_registry()))
    for attempt in range(100):
        empirical, stable = _draw_maximum_streams(replication, attempt, collateral, portfolios, pool)
        try:
            states = {
                population: {
                    portfolio: _normalise_state(
                        portfolio=portfolio,
                        population=population,
                        replication=replication,
                        attempt=attempt,
                        empirical=empirical,
                        stable=stable,
                        collateral=collateral,
                        portfolios=portfolios,
                    )
                    for portfolio in portfolio_ids
                }
                for population in POPULATIONS
            }
        except ValueError as exc:
            if "initially unsafe" in str(exc):
                continue
            raise
        audit_population_nesting(states)
        return states
    raise ValueError("No common safe population initialisation was accepted.")


def audit_population_nesting(states: Mapping[int, Mapping[str, experiment_a.NestedInitialisation]]) -> dict[str, Any]:
    failures: list[str] = []
    for portfolio in next(iter(states.values())):
        for family in FAMILY_ORDER:
            ilks = sorted({str(value) for group in states.values() for value in group[portfolio].sampled.loc[group[portfolio].sampled["family"].eq(family), "exact_ilk"].dropna()})
            for ilk in ilks or [None]:
                sequences = []
                for population in POPULATIONS:
                    selected = states[population][portfolio].sampled.loc[lambda frame: frame["family"].eq(family)]
                    if ilk is not None:
                        selected = selected.loc[selected["exact_ilk"].eq(ilk)]
                    sequences.append(selected.sort_values("family_stream_position", kind="mergesort")["source_row_id"].astype(str).tolist())
                if sequences[0] != sequences[1][: len(sequences[0])] or sequences[1] != sequences[2][: len(sequences[1])]:
                    failures.append(f"{portfolio}/{family}/{ilk}")
    if failures:
        raise ValueError(f"Population nesting failed: {failures}.")
    return {"passed": True, "failure_count": 0}


def _sample_market_paths(replication: int) -> dict[int, pd.DataFrame]:
    profile = resolve_multicollateral_inputs("eth_only").profile
    pool = load_final_market_pool(profile.market_pool_path, profile.market_pool_sha256)
    timestamps = pd.to_datetime(pool["timestamp_utc"], utc=True)
    if (((timestamps >= FTX_START) & (timestamps < FTX_END)) | ((timestamps >= SVB_START) & (timestamps < SVB_END))).any():
        raise ValueError("Held-out rows entered the robustness market pool.")
    uniforms = np.random.default_rng(derive_seed(replication, "market_block_uniforms")).random(math.ceil(TOTAL_HOURS / min(MARKET_BLOCK_HOURS)))
    result: dict[int, pd.DataFrame] = {}
    for block_length in MARKET_BLOCK_HOURS:
        valid = multicollateral_validation._valid_market_block_starts(pool, block_length)
        count = math.ceil(TOTAL_HOURS / block_length)
        starts = [int(valid[min(int(value * len(valid)), len(valid) - 1)]) for value in uniforms[:count]]
        sampled = pd.concat([pool.iloc[start : start + block_length].copy() for start in starts], ignore_index=True).iloc[:TOTAL_HOURS].copy()
        sampled.insert(0, "simulation_step", np.arange(TOTAL_HOURS, dtype=int))
        sampled.attrs["block_starts"] = starts
        result[block_length] = sampled
    return result


def _arrival_stream(replication: int, horizon: int = TOTAL_HOURS) -> dict[str, Any]:
    integrated = resolve_integrated_empirical_eth_profile()
    config = integrated.liquidation_demand
    pool = load_liquidation_arrival_pool(config.pool_path, config.pool_sha256)
    positive = pool.loc[pool["positive_count_eligible"].astype(bool), "grab_count"].to_numpy(dtype=int)
    rng = np.random.default_rng(derive_seed(replication, "liquidation_arrivals"))
    uniforms = rng.random(horizon)
    counts = rng.choice(positive, size=horizon, replace=True)
    return {
        "uniforms": uniforms,
        "positive_counts": counts,
        "hurdle_probability": float(config.hurdle_probability),
        "checksum": _payload_sha256({"uniforms": hashlib.sha256(np.asarray(uniforms, dtype="<f8").tobytes()).hexdigest(), "counts": hashlib.sha256(np.asarray(counts, dtype="<i8").tobytes()).hexdigest()}),
    }


@contextmanager
def keeper_hurdle_adapter(risk_cost_rate: float) -> Iterator[None]:
    """Apply one registered hurdle at the experiment-composition boundary."""
    original_rank = experiment_d.rank_liquidation_candidates
    original_execute = experiment_d.execute_keeper_liquidation

    def rank(vaults: list[Vault], prices: Any = None, config: Any = None, portfolio: Any = None) -> pd.DataFrame:
        return original_rank(vaults, prices=prices, config=replace(config, risk_cost_rate=risk_cost_rate), portfolio=portfolio)

    def execute(vault: Vault, prices: Any, config: Any, portfolio: Any = None) -> dict[str, Any]:
        return original_execute(vault, prices, replace(config, risk_cost_rate=risk_cost_rate), portfolio=portfolio)

    experiment_d.rank_liquidation_candidates = rank
    experiment_d.execute_keeper_liquidation = execute
    try:
        yield
    finally:
        experiment_d.rank_liquidation_candidates = original_rank
        experiment_d.execute_keeper_liquidation = original_execute


def _treatment_paths(sampled: pd.DataFrame, shock: str) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, Any]]:
    if shock == "eth_idiosyncratic_severe":
        paths, audit = experiment_a.build_price_paths(sampled, shock)
        return paths, sampled.copy(), {**audit, "path_valid": audit["price_isolation_valid"], "final_validation_data_used": False}
    if shock == "joint_crypto_high_correlation":
        paths, gas_rows, audit = experiment_b.build_treatment_paths(sampled, shock)
        return paths, gas_rows, {**audit, "path_valid": bool(audit["price_isolation_valid"] and not audit["final_validation_data_used"])}
    return experiment_c.build_treatment_paths(sampled, shock)


def _prepare_common_streams(replication: int) -> dict[str, Any]:
    states = initialise_nested_populations(replication)
    market = _sample_market_paths(replication)
    arrivals = _arrival_stream(replication)
    _, _, stage1 = experiment_a.load_stage1_owners()
    rng = np.random.default_rng(derive_seed(replication, "stage1_residual_blocks"))
    residuals = experiment_a.sample_residual_blocks(stage1["source"], block_count=math.ceil(TOTAL_HOURS / 24), rng=rng)[:TOTAL_HOURS]
    components = {
        "state_identities": {str(pop): {name: state.identity for name, state in group.items()} for pop, group in states.items()},
        "market_rows": {str(length): _payload_sha256(frame["pool_row_id"].astype(str).tolist()) for length, frame in market.items()},
        "market_starts": {str(length): frame.attrs["block_starts"] for length, frame in market.items()},
        "arrival_checksum": arrivals["checksum"],
        "residual_checksum": hashlib.sha256(np.asarray(residuals, dtype="<f8").tobytes()).hexdigest(),
    }
    return {"states": states, "market": market, "arrivals": arrivals, "stage1": stage1, "residuals": residuals, "components": components, "paired_stream_checksum": _payload_sha256(components)}


def _recovery_sensitivity(path: Sequence[float]) -> list[dict[str, Any]]:
    prices = np.asarray(path, dtype=float)
    design = experiment_a.load_recovery_design()
    rows = []
    for hours in RECOVERY_HOURS:
        metrics = experiment_a._recovery_metrics(prices, design=replace(design, stability_hours=hours))
        rows.append({"consecutive_hours": hours, **metrics})
    return rows


def simulate_replication(replication: int) -> dict[str, Any]:
    """Run all 56 registered cells for one common-random-number replication."""
    streams = _prepare_common_streams(replication)
    cells = build_cell_registry()
    collateral_payload, portfolio_payload, _ = experiment_a._design_payloads()
    design = experiment_a.load_recovery_design()
    full_week = next(item for item in design.path_definitions if item.identifier == "full_week")
    scaling = json.loads(experiment_a.SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8"))
    path_cache: dict[tuple[str, int], tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, Any], np.ndarray, str]] = {}
    cell_rows: list[dict[str, Any]] = []
    recovery_rows: list[dict[str, Any]] = []
    for cell in cells:
        path_key = (cell.shock, cell.market_block_hours)
        if path_key not in path_cache:
            paths, gas_rows, audit = _treatment_paths(streams["market"][cell.market_block_hours], cell.shock)
            integrated = resolve_integrated_empirical_eth_profile()
            gas = component_gas_costs(
                sampled_market_gas_rows=gas_rows,
                simulated_eth_prices=paths["ETH"],
                config=replace(integrated.gas, seed=derive_seed(replication, "keeper_gas_units")),
            )
            if gas.gas_cost_usd is None or gas.sampled_rows is None:
                raise ValueError("Keeper gas path is unavailable.")
            gas_checksum = _payload_sha256(gas.sampled_rows[["gas_pool_row_id", "gas_units"]].to_dict(orient="records"))
            path_cache[path_key] = (paths, gas_rows, audit, np.asarray(gas.gas_cost_usd, dtype="<f8"), gas_checksum)
        paths, _, audit, gas_costs, gas_checksum = path_cache[path_key]
        with keeper_hurdle_adapter(cell.risk_cost_rate):
            liquidation = experiment_d._simulate_capacity_liquidations(
                initialisation=streams["states"][cell.population][cell.portfolio],
                price_paths=paths,
                gas_costs=gas_costs,
                arrivals=streams["arrivals"],
                portfolio_config=experiment_a._portfolio_config(cell.portfolio, collateral_payload, portfolio_payload),
                capacity=CAPACITY,
            )
        market = experiment_a._simulate_market_scenario(
            design=design,
            definition=full_week,
            eth_prices=paths["ETH"],
            liquidation=liquidation["arrays"],
            innovations=streams["residuals"],
            scenario_identifier="stage1_only",
            stage1_owners=streams["stage1"],
            peg_scale=float(scaling["lagged_below_peg_gap"]["positive_q95"]),
            eth_scale=float(scaling["lagged_24h_eth_downside"]["positive_q95"]),
            initial_vault_count=cell.population,
        )
        stable = next(row for row in liquidation["collateral_rows"] if row["family"] == "STABLE")
        stable_exposure = float(stable["initial_debt_exposure"])
        row = {
            **asdict(cell),
            "replication": replication,
            **liquidation["system_summary"],
            "unresolved_tab_share": liquidation["system_summary"]["maximum_unresolved_tab_share"],
            "stable_attributed_liquidated_debt_share": float(stable["liquidated_debt"]) / TOTAL_DEBT_DAI,
            "stable_exposure_normalised_liquidated_debt": None if stable_exposure == 0.0 else float(stable["liquidated_debt"]) / stable_exposure,
            "minimum_dai_price": market["summary"]["minimum_dai_price"],
            "mean_absolute_peg_deviation": market["summary"]["mean_absolute_peg_deviation"],
            "below_peg_burden": market["summary"]["below_peg_burden"],
            "restricted_mean_recovery_time": market["summary"]["restricted_mean_recovery_time"],
            "recovery_probability_720h": market["summary"]["recovery_probability_720h"],
            "state_checksum": streams["states"][cell.population][cell.portfolio].identity,
            "paired_stream_checksum": streams["paired_stream_checksum"],
            "gas_unit_draw_checksum": gas_checksum,
            "path_valid": bool(audit.get("path_valid", True)),
            "accounting_valid": bool(liquidation["accounting"]["passed"]),
            "numerical_valid": bool(liquidation["system_summary"]["numerical_valid"] and market["summary"]["numerical_valid"]),
            "held_out_data_used": bool(audit.get("final_validation_data_used", False)),
        }
        cell_rows.append(row)
        for recovery in _recovery_sensitivity(market["dai_price_path"]):
            recovery_rows.append({"cell_identifier": cell.identifier, "contrast_family": cell.contrast_family, "setting": cell.setting, "role": cell.role, "portfolio": cell.portfolio, "replication": replication, **recovery})
    if len(cell_rows) != 56 or any(row["held_out_data_used"] for row in cell_rows):
        raise ValueError("Robustness cell count or held-out boundary failed.")
    if not all(row["accounting_valid"] and row["numerical_valid"] and row["path_valid"] for row in cell_rows):
        raise ValueError("Robustness technical validity failed.")
    return {
        "schema_version": 1,
        "robustness_identity": robustness_identity(),
        "replication": replication,
        "seed_record": seed_record(replication),
        "seed_registry_sha256": seed_registry_checksum(),
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "population_nesting": audit_population_nesting(streams["states"]),
        "cell_rows": cell_rows,
        "recovery_rows": recovery_rows,
    }


def scientific_source_identity() -> str:
    paths = (Path(__file__).resolve(), REGISTRY_PATH)
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(REPOSITORY_ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def robustness_identity() -> str:
    return _payload_sha256(
        {
            "parent_commit": PARENT_COMMIT,
            "scientific_source_identity": scientific_source_identity(),
            "registry_sha256": sha256_file(REGISTRY_PATH),
            "master_programme_identity": MASTER_PROGRAMME_IDENTITY,
            "protected_experiments": PROTECTED_EXPERIMENT_IDENTITIES,
            "h4_synthesis_identity": H4_SYNTHESIS_IDENTITY,
            "oracle_delay_registry_identity": ORACLE_DELAY_REGISTRY_IDENTITY,
            "cells": [asdict(cell) for cell in build_cell_registry()],
            "seed_registry_sha256": seed_registry_checksum(),
            "result_fields_excluded": True,
        }
    )


def specification_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scientific_status": "registered_selected_robustness",
        "parent_commit": PARENT_COMMIT,
        "robustness_identity": robustness_identity(),
        "scientific_source_identity": scientific_source_identity(),
        "registry_path": REGISTRY_PATH,
        "registry_sha256": sha256_file(REGISTRY_PATH),
        "master_programme_identity": MASTER_PROGRAMME_IDENTITY,
        "protected_experiment_identities": PROTECTED_EXPERIMENT_IDENTITIES,
        "h4_synthesis_identity": H4_SYNTHESIS_IDENTITY,
        "oracle_delay_registry_identity": ORACLE_DELAY_REGISTRY_IDENTITY,
        "matrix": {"contrast_families": 4, "settings": 7, "treatment_cells": 2, "cells": 56, "replications": 64, "simulations": 3584, "full_factorial": False},
        "population": {"coordinates": list(POPULATIONS), "total_debt_dai": TOTAL_DEBT_DAI, "target_system_collateral_ratio": TARGET_SYSTEM_COLLATERAL_RATIO, "nested_family_draws": True},
        "market_blocks": {"coordinates_hours": list(MARKET_BLOCK_HOURS), "aligned_eth_wbtc": True, "dai_residual_block_hours": 24, "ftx_excluded": True},
        "recovery_definition": {"band": [0.995, 1.005], "consecutive_hours": list(RECOVERY_HOURS), "primary_hours": 24, "metric_only": True},
        "no_retuning": True,
        "runtime_adopted": False,
    }


def _registry_frame() -> pd.DataFrame:
    return pd.DataFrame(asdict(cell) for cell in build_cell_registry())


def write_preregistration() -> dict[str, Any]:
    spec = specification_payload()
    _atomic_json(EVIDENCE_DIR / COMPACT_FILENAMES[0], spec)
    _atomic_bytes(EVIDENCE_DIR / COMPACT_FILENAMES[1], _csv_bytes(_registry_frame()))
    return spec


def _checkpoint_dir() -> Path:
    return OUTPUT_ROOT / robustness_identity() / "checkpoints"


def _checkpoint_path(replication: int) -> Path:
    return _checkpoint_dir() / f"replication_{replication:03d}.json"


def _valid_checkpoint(path: Path, replication: int) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload["robustness_identity"] == robustness_identity() and payload["replication"] == replication and len(payload["cell_rows"]) == 56 and len(payload["recovery_rows"]) == 168
    except Exception:
        return False


def audit_checkpoints() -> dict[str, Any]:
    valid = [value for value in range(REPLICATIONS) if _valid_checkpoint(_checkpoint_path(value), value)]
    existing = sorted(_checkpoint_dir().glob("replication_*.json")) if _checkpoint_dir().exists() else []
    expected_names = {f"replication_{value:03d}.json" for value in range(REPLICATIONS)}
    orphans = [path.name for path in existing if path.name not in expected_names]
    return {
        "complete": len(valid) == REPLICATIONS and not orphans,
        "valid_count": len(valid),
        "missing_count": REPLICATIONS - len(valid),
        "duplicate_count": 0,
        "orphan_count": len(orphans),
        "orphan_paths": orphans,
        "checkpoint_bytes": sum(path.stat().st_size for path in existing),
    }


def _run_one(replication: int) -> int:
    started = time.perf_counter()
    result = simulate_replication(replication)
    result["worker_elapsed_seconds"] = time.perf_counter() - started
    _atomic_json(_checkpoint_path(replication), result)
    return replication


def run_matrix(*, workers: int = 4, resume: bool = True, max_replications: int | None = None) -> dict[str, Any]:
    pending = [value for value in range(REPLICATIONS) if not (resume and _valid_checkpoint(_checkpoint_path(value), value))]
    if max_replications is not None:
        pending = pending[:max_replications]
    reused = REPLICATIONS - len(pending) if max_replications is None else 0
    started = time.perf_counter()
    completed: list[int] = []
    if workers == 1:
        completed = [_run_one(value) for value in pending]
    elif pending:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            futures = {executor.submit(_run_one, value): value for value in pending}
            for future in as_completed(futures):
                completed.append(future.result())
    elapsed = time.perf_counter() - started
    audit = audit_checkpoints()
    return {"completed_replications": len(completed), "reused_replications": reused, "elapsed_seconds": elapsed, "complete": audit["complete"], "checkpoint_audit": audit}


def load_results() -> tuple[pd.DataFrame, pd.DataFrame]:
    audit = audit_checkpoints()
    if not audit["complete"]:
        raise ValueError("Selected robustness checkpoints are incomplete.")
    cells: list[dict[str, Any]] = []
    recovery: list[dict[str, Any]] = []
    for replication in range(REPLICATIONS):
        payload = json.loads(_checkpoint_path(replication).read_text(encoding="utf-8"))
        cells.extend(payload["cell_rows"])
        recovery.extend(payload["recovery_rows"])
    return pd.DataFrame(cells), pd.DataFrame(recovery)


def _distribution(values: Iterable[float]) -> dict[str, float]:
    array = np.asarray(list(values), dtype=float)
    return {
        "count": int(len(array)),
        "mean": float(array.mean()),
        "standard_error": float(array.std(ddof=1) / math.sqrt(len(array))),
        "ci95_lower": float(array.mean() - 1.96 * array.std(ddof=1) / math.sqrt(len(array))),
        "ci95_upper": float(array.mean() + 1.96 * array.std(ddof=1) / math.sqrt(len(array))),
        "median": float(np.quantile(array, 0.50)),
        "p05": float(np.quantile(array, 0.05)),
        "p25": float(np.quantile(array, 0.25)),
        "p75": float(np.quantile(array, 0.75)),
        "p95": float(np.quantile(array, 0.95)),
    }


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = (*PRIMARY_METRICS, *R_D_METRICS, "minimum_dai_price", "mean_absolute_peg_deviation")
    for cell in build_cell_registry():
        selected = frame.loc[frame["identifier"].eq(cell.identifier)]
        for metric in metrics:
            values = pd.to_numeric(selected[metric], errors="coerce").dropna()
            rows.append({"cell_order": cell.order, "cell_identifier": cell.identifier, "contrast_family": cell.contrast_family, "setting": cell.setting, "role": cell.role, "portfolio": cell.portfolio, "metric": metric, "operationality": "not_operational" if values.empty else ("degenerate" if values.nunique() == 1 else "operational"), **({"count": 0, "mean": None, "standard_error": None, "ci95_lower": None, "ci95_upper": None, "median": None, "p05": None, "p25": None, "p75": None, "p95": None} if values.empty else _distribution(values))})
    return pd.DataFrame(rows)


def contrast_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family in CONTRAST_ORDER:
        metrics = (*PRIMARY_METRICS, *(R_D_METRICS if family == "R-D" else ()))
        for setting in SETTING_ORDER:
            selected = frame.loc[frame["contrast_family"].eq(family) & frame["setting"].eq(setting)]
            left = selected.loc[selected["role"].eq("treatment")].sort_values("replication")
            right = selected.loc[selected["role"].eq("reference")].sort_values("replication")
            if left["replication"].tolist() != right["replication"].tolist():
                raise ValueError("Paired robustness replications differ.")
            for metric in metrics:
                raw = pd.to_numeric(left[metric], errors="coerce").to_numpy() - pd.to_numeric(right[metric], errors="coerce").to_numpy()
                finite = np.isfinite(raw)
                if not finite.any():
                    rows.append({"contrast_family": family, "setting": setting, "metric": metric, "operationality": "not_operational", "materiality": "not_operational", "sign_relative_to_core": "not_operational", "raw_paired_mean": None, "direction_normalised_advantage": None})
                    continue
                distribution = _distribution((-raw[finite]).tolist())
                raw_distribution = _distribution(raw[finite].tolist())
                if family == "R-D":
                    # The inherited C2 conclusion is an inconsistent exposure
                    # gradient, not a directional stable-heavy advantage.  It
                    # reverses only when heavier stable exposure produces a
                    # clear adverse increase in this metric.
                    sign = (
                        "reversed"
                        if raw_distribution["ci95_lower"] > 0.0
                        else "retained"
                    )
                else:
                    sign = "retained" if distribution["mean"] > 0.0 else ("reversed" if distribution["mean"] < 0.0 else "null")
                rows.append({"contrast_family": family, "setting": setting, "metric": metric, "operationality": "degenerate" if np.unique(raw[finite]).size == 1 else "operational", "materiality": "material" if abs(distribution["mean"]) > 1e-6 else "immaterial", "sign_relative_to_core": sign, "raw_paired_mean": raw_distribution["mean"], "direction_normalised_advantage": distribution["mean"], **{key: value for key, value in distribution.items() if key not in {"mean"}}})
    return pd.DataFrame(rows)


def classify_contrast_family(*, retained_settings: int, clear_reversal_settings: int, operational: bool = True, valid: bool = True) -> str:
    if not valid:
        return "invalid"
    if not operational:
        return "not_operational"
    if clear_reversal_settings >= 2:
        return "reversed_under_sensitivity"
    if retained_settings >= 5:
        return "robust"
    if retained_settings >= 4:
        return "robust_with_qualification"
    return "sensitivity_dependent"


def classify_overall(classifications: Sequence[str]) -> str:
    if "invalid" in classifications:
        return "robustness_invalid"
    if "reversed_under_sensitivity" in classifications:
        return "core_conclusions_not_robust"
    if "sensitivity_dependent" in classifications or "not_operational" in classifications:
        return "core_conclusions_sensitivity_dependent"
    if "robust_with_qualification" in classifications:
        return "core_conclusions_robust_with_qualifications"
    return "core_conclusions_robust"


def decision_payload(contrasts: pd.DataFrame, frame: pd.DataFrame) -> dict[str, Any]:
    valid = bool(frame["accounting_valid"].all() and frame["numerical_valid"].all() and frame["path_valid"].all() and not frame["held_out_data_used"].any())
    decisions = {}
    for family in CONTRAST_ORDER:
        selected = contrasts.loc[contrasts["contrast_family"].eq(family)]
        family_metrics = (*PRIMARY_METRICS, *(R_D_METRICS if family == "R-D" else ()))
        primary = selected.loc[selected["metric"].isin(family_metrics)]
        baseline = primary.loc[primary["setting"].eq("baseline")]
        if family == "R-D":
            baseline_retained = int(baseline["sign_relative_to_core"].eq("reversed").sum()) < 2
        else:
            baseline_retained = int(baseline["sign_relative_to_core"].eq("retained").sum()) >= 2
        retained = 0
        reversals = 0
        for setting in SETTING_ORDER[1:]:
            values = primary.loc[primary["setting"].eq(setting)]
            clear_reversals = int(values["sign_relative_to_core"].eq("reversed").sum())
            if family == "R-D":
                retained += int(clear_reversals < 2)
                reversals += int(clear_reversals >= 2)
            else:
                retained += int(values["sign_relative_to_core"].eq("retained").sum() >= 2)
                reversals += int(clear_reversals >= 2 and (values["ci95_upper"].fillna(0.0) < 0.0).sum() >= 2)
        classification = classify_contrast_family(retained_settings=retained, clear_reversal_settings=reversals, operational=not primary.empty and not primary["operationality"].eq("not_operational").all(), valid=valid and baseline_retained)
        decisions[family] = {"classification": classification, "baseline_direction_reconstructed": baseline_retained, "retained_nonbaseline_settings": retained, "clear_reversal_settings": reversals}
    overall = classify_overall([value["classification"] for value in decisions.values()])
    return {"schema_version": 1, "robustness_identity": robustness_identity(), "contrast_families": decisions, "overall_classification": overall, "prior_experiment_decisions_changed": False, "parameter_selection": False, "runtime_adopted": False, "validity": {"passed": valid, "held_out_leakage": int(frame["held_out_data_used"].sum()), "accounting_failures": int((~frame["accounting_valid"]).sum()), "numerical_failures": int((~frame["numerical_valid"]).sum())}}


def recovery_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in frame.groupby(["contrast_family", "setting", "role", "portfolio", "consecutive_hours"], sort=False):
        for metric in ("restricted_mean_recovery_time", "recovery_probability_720h", "right_censored"):
            rows.append({"contrast_family": keys[0], "setting": keys[1], "role": keys[2], "portfolio": keys[3], "consecutive_hours": keys[4], "metric": metric, **_distribution(pd.to_numeric(group[metric], errors="raise"))})
    return pd.DataFrame(rows)


def _manifest_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [{"bytes": path.stat().st_size, "path": path.relative_to(REPOSITORY_ROOT).as_posix(), "runtime_input": False, "semantic_owner": "registered_selected_robustness", "sha256": sha256_file(path)} for path in paths]


def update_manifest(paths: Sequence[Path]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prefix = "data/provenance/experiments/final/selected_robustness/"
    manifest["entries"] = [entry for entry in manifest["entries"] if not entry["path"].startswith(prefix)] + _manifest_records(paths)
    manifest["entries"] = sorted(manifest["entries"], key=lambda item: item["path"])
    manifest["entry_count"] = len(manifest["entries"])
    manifest["duplicate_paths"] = len(manifest["entries"]) - len({entry["path"] for entry in manifest["entries"]})
    _atomic_json(MANIFEST_PATH, manifest)


def write_evidence(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    frame, recovery = load_results()
    cells = cell_summary(frame)
    contrasts = contrast_summary(frame)
    recovery_evidence = recovery_summary(recovery)
    decision = decision_payload(contrasts, frame)
    reproducibility = {
        "schema_version": 1,
        "robustness_identity": robustness_identity(),
        "seed_registry_sha256": seed_registry_checksum(),
        "checkpoint_audit": audit_checkpoints(),
        "registry_sha256": sha256_file(REGISTRY_PATH),
        "scientific_source_identity": scientific_source_identity(),
        "held_out_exclusions_enforced": True,
        "calibration_runs": 0,
        "parameter_changes": 0,
        "scenario_changes": 0,
        "runtime_adopted": False,
    }
    payloads: list[tuple[str, bytes]] = [
        (COMPACT_FILENAMES[0], _json_bytes(specification_payload(), pretty=True)),
        (COMPACT_FILENAMES[1], _csv_bytes(_registry_frame())),
        (COMPACT_FILENAMES[2], _csv_bytes(cells)),
        (COMPACT_FILENAMES[3], _csv_bytes(contrasts)),
        (COMPACT_FILENAMES[4], _csv_bytes(recovery_evidence)),
        (COMPACT_FILENAMES[5], _json_bytes(decision, pretty=True)),
        (COMPACT_FILENAMES[6], _json_bytes(reproducibility, pretty=True)),
        (COMPACT_FILENAMES[7], _json_bytes(dict(benchmark), pretty=True)),
    ]
    paths = []
    for name, payload in payloads:
        path = EVIDENCE_DIR / name
        _atomic_bytes(path, payload)
        paths.append(path)
    update_manifest(paths)
    return {"robustness_identity": robustness_identity(), "decision": decision, "artefacts": {path.name: sha256_file(path) for path in paths}}


def validate_evidence() -> dict[str, Any]:
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise ValueError("Selected robustness compact evidence is incomplete.")
    frame, recovery = load_results()
    if len(frame) != 3584 or len(recovery) != 10752:
        raise ValueError("Selected robustness detailed dimensions differ.")
    decision = json.loads((EVIDENCE_DIR / COMPACT_FILENAMES[5]).read_text(encoding="utf-8"))
    if decision["validity"]["passed"] is not True:
        raise ValueError("Selected robustness decision is invalid.")
    return {"passed": True, "simulations": len(frame), "recovery_metric_rows": len(recovery), "artefact_count": len(paths), "decision": decision["overall_classification"]}


def benchmark_payload(*, workers: int, elapsed_seconds: float, smoke_seconds: float = 0.0) -> dict[str, Any]:
    audit = audit_checkpoints()
    return {
        "schema_version": 1,
        "measurement_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_command": f"PYTHONPATH=src python workflows/experiments/final/selected_robustness.py all --workers {workers}",
        "worker_count": workers,
        "smoke_wall_time_seconds": smoke_seconds,
        "full_wall_time_seconds": elapsed_seconds,
        "throughput_simulations_per_second": 0.0 if elapsed_seconds == 0.0 else 3584 / elapsed_seconds,
        "completed_simulations": 3584,
        "checkpoint_count": audit["valid_count"],
        "output_size_bytes": audit["checkpoint_bytes"],
        "network_calls": 0,
        "calibration_runs": 0,
        "prior_experiment_reruns": 0,
        "held_out_validation_runs": 0,
    }
