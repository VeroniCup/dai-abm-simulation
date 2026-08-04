"""Pre-registered final Experiment A: idiosyncratic diversification.

This module owns treatment assignment, common-random-number composition,
compact accounting, paired contrasts and resumable execution.  Economic
mechanics remain owned by the existing vault, liquidation, confidence, gas,
arrival and DAI-market modules.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import csv
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable

import numpy as np
import pandas as pd

from dai_sim.common.serialization import to_json_compatible
from dai_sim.calibration.event_simulation import (
    SPARSE_SCALING_EVIDENCE,
    load_stage1_owners,
)
from dai_sim.calibration.market import sample_residual_blocks
from dai_sim.experiments.mechanism.eth_recovery import (
    _recovery_metrics,
    _simulate_market_scenario,
    load_recovery_design,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs
from dai_sim.inputs.integrated_profile import (
    EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
    EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
    EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    resolve_integrated_empirical_eth_profile,
)
from dai_sim.inputs.liquidations import (
    LiquidationDemandDecision,
    load_liquidation_arrival_pool,
)
from dai_sim.inputs.market import (
    prices_from_log_returns,
)
from dai_sim.inputs.multicollateral import (
    FAMILY_ORDER,
    load_final_market_pool,
    resolve_multicollateral_inputs,
)
from dai_sim.model.collateral import CollateralConfig, CollateralPortfolioConfig
from dai_sim.model.liquidation import (
    LiquidationConfig,
    execute_keeper_liquidation,
    rank_liquidation_candidates,
)
from dai_sim.model.vault import Vault
from dai_sim.validation import multicollateral as multicollateral_validation


STARTING_CODE_PARENT = "0fabe5192b7942969fd01b602fc1031b6dcf8f62"
REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY = (
    "759748068fec4d45c257a649189b37234d7dd6d23e7ccf4273067bd4c2d1c00a"
)
REGISTERED_EXPERIMENT_IDENTITY = (
    "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb"
)
SERIALIZATION_REPAIR_CLASSIFICATION = "evidence_serialization_infrastructure"
PROFILE_IDENTITY = "d0241808701d0472532c1f7c502ab6637afd60a50082b94bed9ff66f7ec2d53e"
PROFILE_SHA256 = "a2da654cdc9fc053c50f13aacb18e63ce7854bf47d6ad1519352467f6c7986fc"
COLLATERAL_REGISTRY_SHA256 = (
    "75268fed6b3db5a80a822a80b8629291491cd73ce62b4c3e6cf3975060b4eb6d"
)
PORTFOLIO_REGISTRY_SHA256 = (
    "76aa03afa352d86be76fbc7e0153981589f50798c52aed7dfad897061b7960b1"
)
SHOCK_REGISTRY_SHA256 = (
    "a98df90e3e743fc22d9f92c38d53cf46a893928d3fe48eda9e609a20aa108581"
)
KEEPER_REGISTRY_SHA256 = (
    "58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b"
)
CONFIDENCE_REGISTRY_SHA256 = (
    "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
)
SHOCK_EVIDENCE_SHA256 = (
    "5b5167f93f138cc08ba345f8af687d509da8c620dadbb537befcd4be22f8a750"
)
SHOCK_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "data/provenance/validation/multicollateral_integration"
    / "final_shock_registry.csv"
)
PROGRAMME_CONFIG_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_experiment_programme.yaml"
)
EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "data/provenance/experiments/final/idiosyncratic_diversification"
)
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
OUTPUT_ROOT = (
    REPOSITORY_ROOT
    / "outputs/experiments/final/idiosyncratic_diversification"
)

EXPERIMENT_ID = "A_idiosyncratic_diversification"
EXPERIMENT_NAMESPACE = "final-idiosyncratic-diversification-v1"
PORTFOLIO_ORDER = (
    "eth_only",
    "empirical_crypto",
    "balanced_crypto",
    "stable_supported",
)
SHOCK_ORDER = (
    "eth_idiosyncratic_severe",
    "wbtc_idiosyncratic_severe",
)
CELL_ORDER = tuple(
    f"{shock}__{portfolio}"
    for shock in SHOCK_ORDER
    for portfolio in PORTFOLIO_ORDER
)
REPLICATIONS = 128
VAULT_COUNT = 500
TOTAL_DEBT_DAI = 2_500_000.0
TARGET_SYSTEM_COLLATERAL_RATIO = 3.6089387701260205
CAPACITY = 26
PRE_SHOCK_HOURS = 48
POST_SHOCK_HOURS = 720
TOTAL_HOURS = 768
REGISTERED_KERNEL_HOURS = 216
REGISTERED_KERNEL_ONSET = 24
KERNEL_EMBEDDING_START = PRE_SHOCK_HOURS - REGISTERED_KERNEL_ONSET
MAXIMUM_OUTPUT_BYTES = 500 * 1024**2
MINIMUM_FREE_BYTES = 10 * 1024**3

SEED_STREAMS = (
    "initialisation_master",
    "vault_ETH",
    "vault_WBTC",
    "vault_STABLE",
    "market_gas_blocks",
    "keeper_gas_units",
    "liquidation_arrivals",
    "stage1_residual_blocks",
)

SYSTEM_METRICS = (
    "realised_bad_debt_share",
    "positive_realised_bad_debt",
    "active_bad_debt_share",
    "unresolved_tab_share",
    "backlog_area_share",
    "liquidated_debt_share",
    "debt_weighted_liquidated_vault_share",
    "successful_closure_count",
    "capacity_rejected_opportunities",
    "below_peg_burden",
    "mean_absolute_peg_deviation",
    "minimum_dai_price",
    "restricted_mean_recovery_time",
    "recovery_probability_720h",
)
SYSTEM_DIAGNOSTICS = (
    "positive_demand_hours",
    "binding_hours",
    "mean_capacity_utilisation",
    "maximum_capacity_utilisation",
    "maximum_simultaneously_unsafe_families",
    "maximum_backlog_duration",
)
BINARY_METRICS = {
    "positive_realised_bad_debt",
    "recovery_probability_720h",
}
ZERO_HEAVY_METRICS = {
    "realised_bad_debt_share",
    "active_bad_debt_share",
    "unresolved_tab_share",
    "capacity_rejected_opportunities",
}
COLLATERAL_METRICS = (
    "initial_debt_exposure",
    "unsafe_vault_count",
    "liquidation_arrivals",
    "selected_attempts",
    "capacity_rejections",
    "successful_closures",
    "liquidated_debt",
    "backlog_area",
    "active_bad_debt",
    "realised_bad_debt",
    "keeper_profit_proxy",
    "exposure_normalised_liquidated_debt",
    "exposure_normalised_backlog",
    "exposure_normalised_bad_debt",
    "contribution_to_system_backlog",
    "contribution_to_system_bad_debt",
    "displaced_candidates",
)
CONTRASTS = {
    "eth_idiosyncratic_severe": (
        ("empirical_crypto", "eth_only"),
        ("balanced_crypto", "eth_only"),
        ("stable_supported", "eth_only"),
        ("balanced_crypto", "empirical_crypto"),
        ("stable_supported", "empirical_crypto"),
    ),
    "wbtc_idiosyncratic_severe": (
        ("balanced_crypto", "empirical_crypto"),
        ("stable_supported", "empirical_crypto"),
        ("stable_supported", "balanced_crypto"),
    ),
}
COMPACT_FILENAMES = (
    "idiosyncratic_diversification_specification.json",
    "idiosyncratic_diversification_registry.csv",
    "idiosyncratic_diversification_cell_summary.csv",
    "idiosyncratic_diversification_collateral_summary.csv",
    "idiosyncratic_diversification_contrasts.csv",
    "idiosyncratic_diversification_decision.json",
    "idiosyncratic_diversification_reproducibility.json",
    "idiosyncratic_diversification_benchmark.json",
)
DETERMINISTIC_FILENAMES = COMPACT_FILENAMES[:-1]


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        to_json_compatible(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _row_checksum(row: Mapping[str, Any]) -> str:
    return _payload_sha256(dict(row))


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_bytes(
        path,
        _pretty_json(payload),
    )


def _pretty_json(payload: Any) -> bytes:
    """Return deterministic indented JSON after boundary normalisation."""
    return (
        json.dumps(
            to_json_compatible(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    output = io.StringIO(newline="")
    frame.to_csv(output, index=False, lineterminator="\n", float_format="%.12g")
    return output.getvalue().encode("utf-8")


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def derive_seed(replication: int, stream: str, substream: str = "") -> int:
    """Derive one treatment-invariant 64-bit Experiment A seed."""
    if stream not in SEED_STREAMS:
        raise ValueError(f"Unknown Experiment A seed stream: {stream}.")
    if isinstance(replication, bool) or replication < 0:
        raise ValueError("replication must be a non-negative integer.")
    return int.from_bytes(
        hashlib.sha256(
            _canonical_json(
                {
                    "registry_id": EXPERIMENT_NAMESPACE,
                    "replication": int(replication),
                    "stream": stream,
                    "substream": str(substream),
                    "version": 1,
                }
            )
        ).digest()[:8],
        "big",
    )


def seed_record(replication: int) -> dict[str, Any]:
    record = {
        "replication": replication,
        **{
            f"{stream}_seed": derive_seed(replication, stream)
            for stream in SEED_STREAMS
        },
    }
    return {**record, "seed_record_checksum": _payload_sha256(record)}


def seed_registry_checksum(replications: int = REPLICATIONS) -> str:
    return _payload_sha256(
        [seed_record(replication) for replication in range(replications)]
    )


@dataclass(frozen=True)
class ExperimentACell:
    """One frozen shock-by-portfolio Experiment A cell."""

    order: int
    identifier: str
    shock: str
    portfolio: str
    capacity: int
    hurdle: str
    confidence: str
    oracle_delay: int
    replication_count: int
    row_checksum: str


@dataclass(frozen=True)
class NestedInitialisation:
    """One portfolio state drawn from treatment-invariant family streams."""

    portfolio: str
    replication: int
    accepted_attempt: int
    vaults: tuple[Vault, ...]
    sampled: pd.DataFrame
    identity: str
    stream_identity: str
    final_system_collateral_ratio: float
    minimum_liquidation_distance: float


def build_cell_registry() -> tuple[ExperimentACell, ...]:
    """Return the exact eight-cell, shock-first Experiment A registry."""
    cells: list[ExperimentACell] = []
    for shock in SHOCK_ORDER:
        for portfolio in PORTFOLIO_ORDER:
            base = {
                "order": len(cells) + 1,
                "identifier": f"{shock}__{portfolio}",
                "shock": shock,
                "portfolio": portfolio,
                "capacity": CAPACITY,
                "hurdle": "direct_cost_only",
                "confidence": "stage1_only",
                "oracle_delay": 0,
                "replication_count": REPLICATIONS,
            }
            cells.append(
                ExperimentACell(**base, row_checksum=_row_checksum(base))
            )
    if tuple(cell.identifier for cell in cells) != CELL_ORDER:
        raise ValueError("Experiment A cell order differs.")
    return tuple(cells)


def _design_payloads() -> tuple[Mapping[str, Any], Mapping[str, Any], pd.DataFrame]:
    collateral, portfolios, _, _ = (
        multicollateral_validation._design_payloads()
    )
    pool = multicollateral_validation._quiet_empirical_pool(collateral)
    return collateral, portfolios, pool


def _single_ilk_config(
    family_config: Mapping[str, Any], ilk: str
) -> dict[str, Any]:
    payload = deepcopy(dict(family_config))
    protocol = deepcopy(dict(family_config["exact_ilks"][ilk]))
    protocol["quiet_mature_debt_weight"] = 1.0
    payload["exact_ilks"] = {ilk: protocol}
    return payload


def _draw_nested_family_streams(
    *,
    replication: int,
    attempt: int,
    collateral_payload: Mapping[str, Any],
    portfolio_payload: Mapping[str, Any],
    pool: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[dict[str, Any]]]:
    """Draw maximum per-ilk prefixes shared by every portfolio."""
    empirical: dict[str, dict[str, list[dict[str, Any]]]] = {
        "ETH": {},
        "WBTC": {},
    }
    master_seed = derive_seed(replication, "initialisation_master")
    for family in ("ETH", "WBTC"):
        family_config = multicollateral_validation._family_payload(
            collateral_payload, family
        )
        required: dict[str, int] = {
            ilk: 0 for ilk in family_config["exact_ilks"]
        }
        for portfolio in PORTFOLIO_ORDER:
            definition = multicollateral_validation._portfolio_payload(
                portfolio_payload, portfolio
            )
            family_count = int(definition["expected_vault_counts"][family])
            counts = multicollateral_validation._within_family_ilk_counts(
                family_config, family_count
            )
            for ilk, count in counts.items():
                required[ilk] = max(required[ilk], int(count))
        family_rng = np.random.default_rng(
            derive_seed(
                replication,
                f"vault_{family}",
                f"master:{master_seed}:attempt:{attempt}",
            )
        )
        for ilk, count in required.items():
            empirical[family][ilk] = (
                multicollateral_validation._sample_empirical_family(
                    pool=pool,
                    family=family,
                    family_config=_single_ilk_config(family_config, ilk),
                    count=count,
                    rng=family_rng,
                )
            )
            for position, row in enumerate(empirical[family][ilk]):
                row["family_stream_position"] = position
    stable_count = max(
        int(
            multicollateral_validation._portfolio_payload(
                portfolio_payload, portfolio
            )["expected_vault_counts"]["STABLE"]
        )
        for portfolio in PORTFOLIO_ORDER
    )
    stable_rng = np.random.default_rng(
        derive_seed(
            replication,
            "vault_STABLE",
            f"master:{master_seed}:attempt:{attempt}",
        )
    )
    stable = multicollateral_validation._sample_stable_family(
        family_config=multicollateral_validation._family_payload(
            collateral_payload, "STABLE"
        ),
        count=stable_count,
        rng=stable_rng,
    )
    for position, row in enumerate(stable):
        row["family_stream_position"] = position
    return empirical, stable


def _normalise_nested_portfolio(
    *,
    portfolio: str,
    replication: int,
    attempt: int,
    empirical: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    stable: Sequence[Mapping[str, Any]],
    collateral_payload: Mapping[str, Any],
    portfolio_payload: Mapping[str, Any],
) -> NestedInitialisation:
    """Apply the frozen exact-debt and common-CR normalisation to CRN prefixes."""
    definition = multicollateral_validation._portfolio_payload(
        portfolio_payload, portfolio
    )
    counts = {
        family: int(definition["expected_vault_counts"][family])
        for family in FAMILY_ORDER
    }
    shares = {
        family: float(definition["target_debt_shares"][family])
        for family in FAMILY_ORDER
    }
    rows: list[dict[str, Any]] = []
    for family in ("ETH", "WBTC"):
        family_config = multicollateral_validation._family_payload(
            collateral_payload, family
        )
        ilk_counts = multicollateral_validation._within_family_ilk_counts(
            family_config, counts[family]
        )
        for ilk in family_config["exact_ilks"]:
            rows.extend(
                deepcopy(list(empirical[family][ilk][: ilk_counts[ilk]]))
            )
    rows.extend(deepcopy(list(stable[: counts["STABLE"]])))
    frame = pd.DataFrame(rows)
    if len(frame) != VAULT_COUNT:
        raise ValueError(f"{portfolio} did not resolve to exactly 500 vaults.")
    frame.insert(0, "vault_id", np.arange(VAULT_COUNT, dtype=int))
    frame["debt_dai"] = 0.0
    for family in FAMILY_ORDER:
        mask = frame["family"].eq(family)
        if not mask.any():
            continue
        target = TOTAL_DEBT_DAI * shares[family]
        raw_total = float(frame.loc[mask, "raw_debt_dai"].sum())
        if raw_total <= 0.0:
            raise ValueError(f"{family} raw debt is not positive.")
        frame.loc[mask, "debt_dai"] = (
            frame.loc[mask, "raw_debt_dai"] * target / raw_total
        )
    raw_ratio = float(
        np.sum(
            frame["debt_dai"].to_numpy(dtype=float)
            * frame["raw_collateral_ratio"].to_numpy(dtype=float)
        )
        / TOTAL_DEBT_DAI
    )
    scale = TARGET_SYSTEM_COLLATERAL_RATIO / raw_ratio
    frame["collateral_ratio"] = frame["raw_collateral_ratio"] * scale
    initial_prices = {
        family: float(
            multicollateral_validation._family_payload(
                collateral_payload, family
            )["initial_price_usd"]
        )
        for family in FAMILY_ORDER
    }
    frame["initial_price_usd"] = frame["family"].map(initial_prices)
    frame["collateral_amount"] = (
        frame["debt_dai"]
        * frame["collateral_ratio"]
        / frame["initial_price_usd"]
    )
    margins = frame["collateral_ratio"] - frame["liquidation_ratio"]
    if (margins <= 0.0).any():
        raise ValueError(f"{portfolio} contains an initially unsafe vault.")
    final_ratio = float(
        np.sum(frame["debt_dai"] * frame["collateral_ratio"])
        / frame["debt_dai"].sum()
    )
    if not math.isclose(
        float(frame["debt_dai"].sum()),
        TOTAL_DEBT_DAI,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ValueError(f"{portfolio} total debt normalisation failed.")
    if not math.isclose(
        final_ratio,
        TARGET_SYSTEM_COLLATERAL_RATIO,
        rel_tol=0.0,
        abs_tol=1e-10,
    ):
        raise ValueError(f"{portfolio} system collateral ratio differs.")
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
    identity = multicollateral_validation._initialisation_identity(frame)
    stream_rows = frame[
        [
            "family",
            "exact_ilk",
            "source_row_id",
            "family_stream_position",
        ]
    ]
    stream_rows = stream_rows.where(pd.notna(stream_rows), None)
    return NestedInitialisation(
        portfolio=portfolio,
        replication=replication,
        accepted_attempt=attempt,
        vaults=vaults,
        sampled=frame,
        identity=identity,
        stream_identity=_payload_sha256(
            stream_rows.to_dict(orient="records")
        ),
        final_system_collateral_ratio=final_ratio,
        minimum_liquidation_distance=float(margins.min()),
    )


def initialise_nested_portfolios(
    replication: int,
    *,
    maximum_attempts: int = 100,
) -> dict[str, NestedInitialisation]:
    """Create all four portfolio states from nested family/ilk draw prefixes."""
    collateral, portfolios, pool = _design_payloads()
    for attempt in range(maximum_attempts):
        empirical, stable = _draw_nested_family_streams(
            replication=replication,
            attempt=attempt,
            collateral_payload=collateral,
            portfolio_payload=portfolios,
            pool=pool,
        )
        try:
            states = {
                portfolio: _normalise_nested_portfolio(
                    portfolio=portfolio,
                    replication=replication,
                    attempt=attempt,
                    empirical=empirical,
                    stable=stable,
                    collateral_payload=collateral,
                    portfolio_payload=portfolios,
                )
                for portfolio in PORTFOLIO_ORDER
            }
        except ValueError as exc:
            if "initially unsafe" in str(exc):
                continue
            raise
        audit_nested_initialisations(states)
        return states
    raise ValueError(
        "No common safe four-portfolio initialisation was accepted after "
        f"{maximum_attempts} attempts."
    )


def audit_nested_initialisations(
    states: Mapping[str, NestedInitialisation],
) -> dict[str, Any]:
    """Require every smaller family/ilk sample to be a prefix of the larger."""
    if tuple(states) != PORTFOLIO_ORDER:
        raise ValueError("Nested initialisation portfolio order differs.")
    failures: list[str] = []
    for family in FAMILY_ORDER:
        ilks = sorted(
            {
                str(value)
                for state in states.values()
                for value in state.sampled.loc[
                    state.sampled["family"].eq(family), "exact_ilk"
                ].dropna()
            }
        )
        keys: list[str | None] = ilks or [None]
        for ilk in keys:
            sequences: list[tuple[str, list[str]]] = []
            for portfolio, state in states.items():
                selected = state.sampled.loc[state.sampled["family"].eq(family)]
                if ilk is not None:
                    selected = selected.loc[selected["exact_ilk"].eq(ilk)]
                values = selected.sort_values(
                    "family_stream_position", kind="mergesort"
                )["source_row_id"].astype(str).tolist()
                sequences.append((portfolio, values))
            ordered = sorted(sequences, key=lambda item: len(item[1]))
            for (left_name, left), (right_name, right) in zip(
                ordered, ordered[1:], strict=False
            ):
                if left != right[: len(left)]:
                    failures.append(
                        f"{family}/{ilk}:{left_name}->{right_name}"
                    )
    if failures:
        raise ValueError(f"Nested family draws failed: {failures}.")
    return {
        "passed": True,
        "portfolio_count": len(states),
        "failure_count": 0,
        "initialisation_identities": {
            name: state.identity for name, state in states.items()
        },
    }


def _shock_evidence() -> pd.DataFrame:
    if sha256_file(SHOCK_EVIDENCE_PATH) != SHOCK_EVIDENCE_SHA256:
        raise ValueError("Frozen final-shock evidence checksum changed.")
    frame = pd.read_csv(SHOCK_EVIDENCE_PATH)
    required = {
        "shock_identifier",
        "family",
        "onset_hour",
        "price_multiplier_at_trough",
        "recovery_path",
        "duration_hours",
        "path_checksum",
    }
    if not required.issubset(frame):
        raise ValueError("Frozen final-shock evidence schema changed.")
    return frame


def registered_shock_kernels(
    shock: str,
) -> dict[str, np.ndarray]:
    """Reconstruct and checksum the frozen 216-hour multiplier kernels."""
    if shock not in SHOCK_ORDER:
        raise ValueError(f"Unexpected Experiment A shock: {shock}.")
    evidence = _shock_evidence()
    collateral, _, shock_payload, _ = (
        multicollateral_validation._design_payloads()
    )
    profile = resolve_multicollateral_inputs("eth_only").profile
    market_pool = load_final_market_pool(
        profile.market_pool_path, profile.market_pool_sha256
    )
    resolved, _ = multicollateral_validation.shock_registry_frame(
        shock_payload, market_pool
    )
    if multicollateral_validation._csv_bytes(resolved) != (
        SHOCK_EVIDENCE_PATH.read_bytes()
    ):
        raise ValueError("Frozen shock registry does not reconstruct exactly.")
    if not resolved["row_checksum"].equals(evidence["row_checksum"]):
        raise ValueError("Frozen shock row checksums differ.")
    selected = resolved.loc[resolved["shock_identifier"].eq(shock)]
    kernels: dict[str, np.ndarray] = {}
    for family in FAMILY_ORDER:
        row = selected.loc[selected["family"].eq(family)]
        if len(row) != 1:
            raise ValueError(f"Missing one frozen {shock}/{family} row.")
        values = row.iloc[0]
        onset = int(values["onset_hour"])
        if onset != REGISTERED_KERNEL_ONSET:
            raise ValueError("Frozen shock-kernel onset changed.")
        multiplier = float(values["price_multiplier_at_trough"])
        recovery = str(values["recovery_path"])
        duration = int(values["duration_hours"])
        kernel = multicollateral_validation._controlled_path(
            multiplier=multiplier,
            onset=onset,
            recovery=recovery,
            recovery_hours=max(duration, 1),
            horizon=REGISTERED_KERNEL_HOURS,
        )
        checksum = hashlib.sha256(
            np.asarray(kernel, dtype="<f8").tobytes()
        ).hexdigest()
        if checksum != str(values["path_checksum"]):
            raise ValueError(f"Frozen {shock}/{family} kernel checksum differs.")
        kernels[family] = kernel
    return kernels


def embed_registered_kernel(kernel: Sequence[float]) -> np.ndarray:
    """Embed an unchanged hour-24 kernel after the unique 24-hour warm-up."""
    values = np.asarray(kernel, dtype="<f8")
    if values.shape != (REGISTERED_KERNEL_HOURS,):
        raise ValueError("Registered shock kernel must contain 216 hours.")
    embedded = np.ones(TOTAL_HOURS, dtype="<f8")
    stop = KERNEL_EMBEDDING_START + len(values)
    embedded[KERNEL_EMBEDDING_START:stop] = values
    embedded[stop:] = values[-1]
    if not math.isclose(
        embedded[PRE_SHOCK_HOURS],
        values[REGISTERED_KERNEL_ONSET],
        abs_tol=1e-15,
    ):
        raise ValueError("Registered shock did not align to experiment hour 48.")
    if not np.allclose(
        embedded[:PRE_SHOCK_HOURS],
        1.0,
        atol=0.0,
        rtol=0.0,
    ):
        raise ValueError("Experiment A pre-shock path is not ordinary.")
    return embedded


def _stable_prices(
    sampled: pd.DataFrame, initial_price: float
) -> np.ndarray:
    returns = pd.to_numeric(
        sampled["usdc_log_return"], errors="raise"
    ).to_numpy(dtype=float)
    if not np.isfinite(returns).all():
        raise ValueError("Stable ordinary log returns are invalid.")
    prices = np.empty(len(returns), dtype="<f8")
    prices[0] = initial_price
    for position in range(1, len(returns)):
        prices[position] = prices[position - 1] * math.exp(returns[position])
    if not np.isfinite(prices).all() or np.any(prices <= 0.0):
        raise ValueError("Stable ordinary price path is invalid.")
    return prices


def build_price_paths(
    sampled_market: pd.DataFrame,
    shock: str,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Overlay one frozen shock kernel on shared ordinary empirical paths."""
    collateral, _, _ = _design_payloads()
    initial = {
        family: float(
            multicollateral_validation._family_payload(collateral, family)[
                "initial_price_usd"
            ]
        )
        for family in FAMILY_ORDER
    }
    ordinary = prices_from_log_returns(
        sampled_market,
        initial_prices={"ETH": initial["ETH"], "BTC": initial["WBTC"]},
    )
    ordinary["STABLE"] = _stable_prices(sampled_market, initial["STABLE"])
    kernels = registered_shock_kernels(shock)
    multipliers = {
        family: embed_registered_kernel(kernels[family])
        for family in FAMILY_ORDER
    }
    paths = {
        "ETH": ordinary["ETH"] * multipliers["ETH"],
        "BTC": ordinary["BTC"] * multipliers["WBTC"],
        "STABLE": ordinary["STABLE"] * multipliers["STABLE"],
    }
    for values in paths.values():
        if not np.isfinite(values).all() or np.any(values <= 0.0):
            raise ValueError("Experiment A price path is invalid.")
    shocked = "ETH" if shock.startswith("eth_") else "WBTC"
    non_shocked = tuple(family for family in FAMILY_ORDER if family != shocked)
    if not all(np.array_equal(multipliers[family], np.ones(TOTAL_HOURS)) for family in non_shocked):
        raise ValueError("Idiosyncratic shock leaked across collateral prices.")
    audit = {
        "shock": shock,
        "registered_kernel_onset_hour": REGISTERED_KERNEL_ONSET,
        "kernel_embedding_start_hour": KERNEL_EMBEDDING_START,
        "experiment_shock_hour": PRE_SHOCK_HOURS,
        "registered_kernel_checksums": {
            family: hashlib.sha256(
                np.asarray(kernels[family], dtype="<f8").tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "embedded_multiplier_checksums": {
            family: hashlib.sha256(
                np.asarray(multipliers[family], dtype="<f8").tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "full_price_checksums": {
            family: hashlib.sha256(
                np.asarray(
                    paths["BTC" if family == "WBTC" else family],
                    dtype="<f8",
                ).tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "price_isolation_valid": True,
    }
    return paths, audit


def _portfolio_config(
    portfolio_id: str,
    collateral_payload: Mapping[str, Any],
    portfolio_payload: Mapping[str, Any],
) -> CollateralPortfolioConfig:
    definition = multicollateral_validation._portfolio_payload(
        portfolio_payload, portfolio_id
    )
    collaterals = []
    for family in FAMILY_ORDER:
        share = float(definition["target_debt_shares"][family])
        if share == 0.0:
            continue
        owner = multicollateral_validation._family_payload(
            collateral_payload, family
        )
        collaterals.append(
            CollateralConfig(
                name=str(owner["simulator_collateral_name"]),
                initial_price=float(owner["initial_price_usd"]),
                liquidation_ratio=float(owner["liquidation_ratio"]),
                liquidation_penalty=float(owner["liquidation_penalty_rate"]),
                target_debt_share=share,
                max_close_factor=float(owner["max_close_factor"]),
            )
        )
    return CollateralPortfolioConfig(
        name=f"final_{portfolio_id}",
        collaterals=tuple(collaterals),
    )


def _arrival_stream(
    *,
    replication: int,
    horizon: int,
) -> dict[str, Any]:
    integrated = resolve_integrated_empirical_eth_profile()
    config = integrated.liquidation_demand
    pool = load_liquidation_arrival_pool(config.pool_path, config.pool_sha256)
    positive = pool.loc[
        pool["positive_count_eligible"].astype(bool), "grab_count"
    ].to_numpy(dtype=int)
    rng = np.random.default_rng(
        derive_seed(replication, "liquidation_arrivals")
    )
    uniforms = rng.random(horizon)
    counts = rng.choice(positive, size=horizon, replace=True)
    return {
        "uniforms": uniforms,
        "positive_counts": counts,
        "hurdle_probability": float(config.hurdle_probability),
        "checksum": _payload_sha256(
            {
                "uniforms": hashlib.sha256(
                    np.asarray(uniforms, dtype="<f8").tobytes()
                ).hexdigest(),
                "counts": hashlib.sha256(
                    np.asarray(counts, dtype="<i8").tobytes()
                ).hexdigest(),
            }
        ),
    }


def _demand_decision(
    *,
    step: int,
    inventory: int,
    uniform: float,
    positive_count: int,
    hurdle_probability: float,
) -> LiquidationDemandDecision:
    if inventory == 0:
        active = False
        sampled = 0
    else:
        active = bool(uniform < hurdle_probability)
        sampled = int(positive_count) if active else 0
    bounded = min(sampled, inventory)
    attempts = min(bounded, CAPACITY)
    return LiquidationDemandDecision(
        step=step,
        liquidatable_inventory=inventory,
        activity_draw=active,
        raw_positive_count_draw=int(positive_count) if active else 0,
        sampled_demand=sampled,
        bounded_demand=bounded,
        keeper_capacity=CAPACITY,
        attempt_budget=attempts,
        demand_truncated_by_inventory=max(sampled - bounded, 0),
        demand_truncated_by_capacity=max(bounded - attempts, 0),
        demand_inactive_unresolved=inventory if inventory and not active else 0,
        inventory_not_sampled_unresolved=inventory - bounded if active else 0,
    )


def _family(value: str) -> str:
    return "WBTC" if value == "BTC" else value


def _max_run(values: Sequence[bool]) -> int:
    maximum = current = 0
    for value in values:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _simulate_cell_liquidations(
    *,
    initialisation: NestedInitialisation,
    price_paths: Mapping[str, np.ndarray],
    gas_costs: np.ndarray,
    arrivals: Mapping[str, Any],
    portfolio_config: CollateralPortfolioConfig,
    reporting_observer: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Compose canonical ranking/execution into one compact cell result."""
    vaults = deepcopy(list(initialisation.vaults))
    vault_by_id = {int(vault.vault_id): vault for vault in vaults}
    if len(vault_by_id) != len(vaults):
        raise ValueError("Initial vault identifiers are not unique.")
    integrated = resolve_integrated_empirical_eth_profile()
    base_liquidation = integrated.bundle.base_bundle.liquidation_config
    array_names = {
        "liquidatable_before": "<i8",
        "sampled_arrivals": "<i8",
        "selected_attempts": "<i8",
        "successful_liquidations": "<i8",
        "successful_closures": "<i8",
        "failed_liquidation_attempts": "<i8",
        "capacity_rejected_opportunities": "<i8",
        "unresolved_tab_dai": "<f8",
        "active_bad_debt_dai": "<f8",
        "realised_bad_debt_dai": "<f8",
        "terminal_debt_writeoff_dai": "<f8",
        "cleared_tab_dai": "<f8",
        "keeper_profit_dai": "<f8",
        "liquidation_gate_open": "?",
        "material_active_bad_debt": "?",
    }
    arrays = {
        name: np.zeros(TOTAL_HOURS, dtype=dtype)
        for name, dtype in array_names.items()
    }
    family_arrays = {
        family: {
            name: np.zeros(TOTAL_HOURS, dtype="<f8")
            for name in (
                "unsafe",
                "arrivals",
                "attempts",
                "capacity_rejections",
                "successful",
                "closures",
                "liquidated_debt",
                "backlog",
                "active_bad_debt",
                "realised_bad_debt",
                "terminal_debt_writeoff",
                "keeper_profit",
                "displaced_candidates",
            )
        }
        for family in FAMILY_ORDER
    }
    initial_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    initial_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    initial_debt_by_vault = {
        int(vault.vault_id): float(vault.debt_dai) for vault in vaults
    }
    unsafe_ever = {family: set() for family in FAMILY_ORDER}
    closed_ids: set[int] = set()
    liquidated_initial_debt_ids: set[int] = set()
    removed_collateral = defaultdict(float)
    repaid_debt = defaultdict(float)
    terminal_debt_writeoff = defaultdict(float)
    maximum_unsafe_families = 0
    duplicate_attempt = False
    duplicate_closure = False
    reconciliation_failures = 0
    for step in range(TOTAL_HOURS):
        prices = {
            "ETH": float(price_paths["ETH"][step]),
            "BTC": float(price_paths["BTC"][step]),
            "STABLE": float(price_paths["STABLE"][step]),
        }
        candidates = [
            vault
            for vault in vaults
            if vault.is_active and vault.is_liquidatable(prices)
        ]
        if step >= PRE_SHOCK_HOURS:
            for vault in candidates:
                unsafe_ever[_family(vault.collateral_type)].add(
                    int(vault.vault_id)
                )
        if step >= PRE_SHOCK_HOURS:
            maximum_unsafe_families = max(
                maximum_unsafe_families,
                len({_family(vault.collateral_type) for vault in candidates}),
            )
        step_config = replace(
            base_liquidation,
            gas_cost=float(gas_costs[step]),
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=CAPACITY,
        )
        ranked = rank_liquidation_candidates(
            candidates,
            prices=prices,
            config=step_config,
            portfolio=portfolio_config,
        )
        decision = _demand_decision(
            step=step,
            inventory=len(candidates),
            uniform=float(arrivals["uniforms"][step]),
            positive_count=int(arrivals["positive_counts"][step]),
            hurdle_probability=float(arrivals["hurdle_probability"]),
        )
        demand_selected = ranked.head(decision.bounded_demand)
        attempt_selected = ranked.head(decision.attempt_budget)
        attempt_ids = attempt_selected["vault_id"].astype(int).tolist()
        duplicate_attempt = duplicate_attempt or len(attempt_ids) != len(
            set(attempt_ids)
        )
        demand_by_family = Counter(
            _family(value) for value in demand_selected["collateral_type"]
        )
        attempt_by_family = Counter(
            _family(value) for value in attempt_selected["collateral_type"]
        )
        candidate_by_family = Counter(
            _family(value) for value in ranked["collateral_type"]
        )
        selected_set = set(attempt_ids)
        displaced_by_family: dict[str, int] = {}
        for family in FAMILY_ORDER:
            if decision.demand_truncated_by_capacity <= 0:
                displaced_by_family[family] = 0
                continue
            isolated = (
                ranked.loc[
                    ranked["collateral_type"].map(_family).eq(family),
                    "vault_id",
                ]
                .head(CAPACITY)
                .astype(int)
            )
            displaced_by_family[family] = len(set(isolated) - selected_set)
        executions: list[dict[str, Any]] = []
        for vault_id in attempt_ids:
            vault = vault_by_id[vault_id]
            before_collateral = float(vault.collateral_amount)
            before_debt = float(vault.debt_dai)
            result = execute_keeper_liquidation(
                vault,
                prices,
                step_config,
                portfolio=portfolio_config,
            )
            family = _family(vault.collateral_type)
            result["family"] = family
            result["collateral_removed"] = (
                before_collateral - float(vault.collateral_amount)
            )
            result["terminal_debt_writeoff"] = max(
                before_debt
                - float(vault.debt_dai)
                - float(result["debt_repaid"]),
                0.0,
            )
            if bool(result["fully_liquidated"]):
                if vault_id in closed_ids:
                    duplicate_closure = True
                closed_ids.add(vault_id)
            if bool(result["liquidated"]) and step >= PRE_SHOCK_HOURS:
                liquidated_initial_debt_ids.add(vault_id)
            executions.append(result)
        execution = pd.DataFrame(executions)
        for family in FAMILY_ORDER:
            selected = (
                execution.loc[execution["family"].eq(family)]
                if not execution.empty
                else execution
            )
            successful = (
                selected.loc[selected["liquidated"].astype(bool)]
                if not selected.empty
                else selected
            )
            closures = (
                selected.loc[selected["fully_liquidated"].astype(bool)]
                if not selected.empty
                else selected
            )
            liquidated_debt = (
                float(successful["debt_repaid"].sum())
                if not successful.empty
                else 0.0
            )
            realised_bad_debt = (
                float(closures["bad_debt"].sum())
                if not closures.empty
                else 0.0
            )
            debt_writeoff = (
                float(closures["terminal_debt_writeoff"].sum())
                if not closures.empty
                else 0.0
            )
            keeper_profit = (
                float(successful["realised_keeper_profit"].sum())
                if not successful.empty
                else 0.0
            )
            collateral_removed = (
                float(successful["collateral_removed"].sum())
                if not successful.empty
                else 0.0
            )
            repaid_debt[family] += liquidated_debt
            terminal_debt_writeoff[family] += debt_writeoff
            removed_collateral[family] += collateral_removed
            backlog = float(
                sum(
                    vault.debt_dai
                    for vault in vaults
                    if vault.is_active
                    and _family(vault.collateral_type) == family
                    and vault.is_liquidatable(prices)
                )
            )
            active_bad_debt = float(
                sum(
                    vault.bad_debt(prices)
                    for vault in vaults
                    if vault.is_active
                    and _family(vault.collateral_type) == family
                )
            )
            values = family_arrays[family]
            values["unsafe"][step] = candidate_by_family[family]
            values["arrivals"][step] = demand_by_family[family]
            values["attempts"][step] = attempt_by_family[family]
            values["capacity_rejections"][step] = (
                demand_by_family[family] - attempt_by_family[family]
            )
            values["successful"][step] = len(successful)
            values["closures"][step] = len(closures)
            values["liquidated_debt"][step] = liquidated_debt
            values["backlog"][step] = backlog
            values["active_bad_debt"][step] = active_bad_debt
            values["realised_bad_debt"][step] = realised_bad_debt
            values["terminal_debt_writeoff"][step] = debt_writeoff
            values["keeper_profit"][step] = keeper_profit
            values["displaced_candidates"][step] = displaced_by_family[family]
        arrays["liquidatable_before"][step] = len(candidates)
        arrays["sampled_arrivals"][step] = len(demand_selected)
        arrays["selected_attempts"][step] = len(attempt_selected)
        arrays["successful_liquidations"][step] = sum(
            family_arrays[family]["successful"][step]
            for family in FAMILY_ORDER
        )
        arrays["successful_closures"][step] = sum(
            family_arrays[family]["closures"][step]
            for family in FAMILY_ORDER
        )
        arrays["failed_liquidation_attempts"][step] = (
            len(attempt_selected) - arrays["successful_liquidations"][step]
        )
        arrays["capacity_rejected_opportunities"][step] = (
            len(demand_selected) - len(attempt_selected)
        )
        arrays["unresolved_tab_dai"][step] = sum(
            family_arrays[family]["backlog"][step] for family in FAMILY_ORDER
        )
        arrays["active_bad_debt_dai"][step] = sum(
            family_arrays[family]["active_bad_debt"][step]
            for family in FAMILY_ORDER
        )
        arrays["realised_bad_debt_dai"][step] = sum(
            family_arrays[family]["realised_bad_debt"][step]
            for family in FAMILY_ORDER
        )
        arrays["terminal_debt_writeoff_dai"][step] = sum(
            family_arrays[family]["terminal_debt_writeoff"][step]
            for family in FAMILY_ORDER
        )
        arrays["cleared_tab_dai"][step] = sum(
            family_arrays[family]["liquidated_debt"][step]
            for family in FAMILY_ORDER
        )
        arrays["keeper_profit_dai"][step] = sum(
            family_arrays[family]["keeper_profit"][step]
            for family in FAMILY_ORDER
        )
        arrays["liquidation_gate_open"][step] = (
            arrays["unresolved_tab_dai"][step] <= 1e-9
        )
        arrays["material_active_bad_debt"][step] = (
            arrays["active_bad_debt_dai"][step] > 1e-6
        )
        for metric, array_name in (
            ("unsafe", "liquidatable_before"),
            ("arrivals", "sampled_arrivals"),
            ("attempts", "selected_attempts"),
            ("capacity_rejections", "capacity_rejected_opportunities"),
            ("successful", "successful_liquidations"),
            ("closures", "successful_closures"),
            ("liquidated_debt", "cleared_tab_dai"),
            ("backlog", "unresolved_tab_dai"),
            ("active_bad_debt", "active_bad_debt_dai"),
            ("realised_bad_debt", "realised_bad_debt_dai"),
            ("terminal_debt_writeoff", "terminal_debt_writeoff_dai"),
            ("keeper_profit", "keeper_profit_dai"),
        ):
            if not math.isclose(
                float(arrays[array_name][step]),
                sum(
                    float(family_arrays[family][metric][step])
                    for family in FAMILY_ORDER
                ),
                rel_tol=0.0,
                abs_tol=1e-8,
            ):
                reconciliation_failures += 1
        if reporting_observer is not None:
            active_snapshot = tuple(
                (
                    int(vault.vault_id),
                    _family(vault.collateral_type),
                    float(vault.debt_dai),
                    float(vault.collateral_ratio(prices)),
                    float(vault.liquidation_ratio),
                    bool(vault.is_liquidatable(prices)),
                    int(vault.vault_id) in selected_set,
                )
                for vault in vaults
                if vault.is_active
            )
            reporting_observer(
                step,
                tuple((family, float(prices[family])) for family in prices),
                active_snapshot,
            )
    final_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if vault.is_active and _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    final_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if vault.is_active and _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    debt_errors = {
        family: (
            initial_debt[family]
            - final_debt[family]
            - repaid_debt[family]
            - terminal_debt_writeoff[family]
        )
        for family in FAMILY_ORDER
    }
    collateral_errors = {
        family: (
            initial_collateral[family]
            - final_collateral[family]
            - removed_collateral[family]
        )
        for family in FAMILY_ORDER
    }
    accounting_valid = bool(
        reconciliation_failures == 0
        and not duplicate_attempt
        and not duplicate_closure
        and all(abs(value) <= 1e-5 for value in debt_errors.values())
        and all(abs(value) <= 1e-5 for value in collateral_errors.values())
    )
    post = slice(PRE_SHOCK_HOURS, None)
    system_summary = {
        "initial_total_debt_dai": TOTAL_DEBT_DAI,
        "realised_bad_debt_share": float(
            arrays["realised_bad_debt_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "positive_realised_bad_debt": int(
            arrays["realised_bad_debt_dai"][post].sum() > 1e-9
        ),
        "active_bad_debt_share": float(
            arrays["active_bad_debt_dai"][-1] / TOTAL_DEBT_DAI
        ),
        "unresolved_tab_share": float(
            arrays["unresolved_tab_dai"][-1] / TOTAL_DEBT_DAI
        ),
        "backlog_area_share": float(
            arrays["unresolved_tab_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "liquidated_debt_share": float(
            arrays["cleared_tab_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "debt_weighted_liquidated_vault_share": float(
            sum(
                initial_debt_by_vault[vault_id]
                for vault_id in liquidated_initial_debt_ids
            )
            / TOTAL_DEBT_DAI
        ),
        "successful_closure_count": int(
            arrays["successful_closures"][post].sum()
        ),
        "capacity_rejected_opportunities": int(
            arrays["capacity_rejected_opportunities"][post].sum()
        ),
        "positive_demand_hours": int(
            np.count_nonzero(arrays["sampled_arrivals"][post] > 0)
        ),
        "binding_hours": int(
            np.count_nonzero(
                arrays["capacity_rejected_opportunities"][post] > 0
            )
        ),
        "mean_capacity_utilisation": float(
            np.mean(arrays["selected_attempts"][post] / CAPACITY)
        ),
        "maximum_capacity_utilisation": float(
            np.max(arrays["selected_attempts"][post] / CAPACITY)
        ),
        "maximum_simultaneously_unsafe_families": maximum_unsafe_families,
        "maximum_backlog_duration": _max_run(
            arrays["unresolved_tab_dai"][post] > 0
        ),
        "accounting_valid": accounting_valid,
        "reconciliation_failure_count": reconciliation_failures,
        "duplicate_attempt": duplicate_attempt,
        "duplicate_closure": duplicate_closure,
        "numerical_valid": bool(
            all(np.isfinite(values).all() for values in arrays.values())
            and all(vault.debt_dai >= 0 for vault in vaults)
            and all(vault.collateral_amount >= 0 for vault in vaults)
        ),
    }
    collateral_rows: list[dict[str, Any]] = []
    system_backlog = float(
        sum(family_arrays[family]["backlog"][post].sum() for family in FAMILY_ORDER)
    )
    system_bad_debt = float(
        sum(
            family_arrays[family]["realised_bad_debt"][post].sum()
            for family in FAMILY_ORDER
        )
    )
    for family in FAMILY_ORDER:
        exposure = initial_debt[family]
        values = family_arrays[family]
        liquidated = float(values["liquidated_debt"][post].sum())
        backlog = float(values["backlog"][post].sum())
        bad_debt = float(values["realised_bad_debt"][post].sum())
        collateral_rows.append(
            {
                "family": family,
                "initial_debt_exposure": exposure,
                "unsafe_vault_count": len(unsafe_ever[family]),
                "liquidation_arrivals": int(values["arrivals"][post].sum()),
                "selected_attempts": int(values["attempts"][post].sum()),
                "capacity_rejections": int(
                    values["capacity_rejections"][post].sum()
                ),
                "successful_closures": int(values["closures"][post].sum()),
                "liquidated_debt": liquidated,
                "backlog_area": backlog,
                "active_bad_debt": float(values["active_bad_debt"][-1]),
                "realised_bad_debt": bad_debt,
                "keeper_profit_proxy": float(
                    values["keeper_profit"][post].sum()
                ),
                "exposure_normalised_liquidated_debt": (
                    None if exposure == 0 else liquidated / exposure
                ),
                "exposure_normalised_backlog": (
                    None if exposure == 0 else backlog / exposure
                ),
                "exposure_normalised_bad_debt": (
                    None if exposure == 0 else bad_debt / exposure
                ),
                "contribution_to_system_backlog": (
                    None if system_backlog == 0 else backlog / system_backlog
                ),
                "contribution_to_system_bad_debt": (
                    None if system_bad_debt == 0 else bad_debt / system_bad_debt
                ),
                "displaced_candidates": int(
                    values["displaced_candidates"][post].sum()
                ),
            }
        )
    return {
        "arrays": arrays,
        "system_summary": system_summary,
        "collateral_rows": collateral_rows,
        "accounting": {
            "passed": accounting_valid,
            "debt_errors": debt_errors,
            "collateral_errors": collateral_errors,
            "reconciliation_failure_count": reconciliation_failures,
        },
    }


def _prepare_replication_streams(replication: int) -> dict[str, Any]:
    states = initialise_nested_portfolios(replication)
    profile = resolve_multicollateral_inputs("eth_only").profile
    market_pool = load_final_market_pool(
        profile.market_pool_path, profile.market_pool_sha256
    )
    block_length = int(profile.raw["market_process"]["block_length_hours"])
    starts = multicollateral_validation._valid_market_block_starts(
        market_pool, block_length
    )
    rng = np.random.default_rng(derive_seed(replication, "market_gas_blocks"))
    block_count = math.ceil(TOTAL_HOURS / block_length)
    chosen_starts = rng.choice(starts, size=block_count, replace=True)
    sampled = pd.concat(
        [
            market_pool.iloc[
                int(start) : int(start) + block_length
            ].copy()
            for start in chosen_starts
        ],
        ignore_index=True,
    ).iloc[:TOTAL_HOURS].copy()
    sampled.insert(0, "simulation_step", np.arange(TOTAL_HOURS, dtype=int))
    market_provenance = {
        "block_length_hours": block_length,
        "n_blocks": block_count,
        "sampled_start_indexes": [
            int(start) for start in chosen_starts
        ],
        "replacement_used": True,
        "final_truncated_block_length": int(
            TOTAL_HOURS - block_length * (block_count - 1)
        ),
        "available_block_start_count": len(starts),
        "pool_label": "all_calibration",
        "segment_bounded": True,
    }
    arrivals = _arrival_stream(replication=replication, horizon=TOTAL_HOURS)
    _, _, stage1 = load_stage1_owners()
    residual_rng = np.random.default_rng(
        derive_seed(replication, "stage1_residual_blocks")
    )
    residuals = sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(TOTAL_HOURS / 24),
        rng=residual_rng,
    )[:TOTAL_HOURS]
    components = {
        "initialisation_master_seed": derive_seed(
            replication, "initialisation_master"
        ),
        "state_identities": {
            name: state.identity for name, state in states.items()
        },
        "market_start_indexes": market_provenance["sampled_start_indexes"],
        "market_rows_checksum": _payload_sha256(
            sampled["pool_row_id"].astype(str).tolist()
        ),
        "arrival_checksum": arrivals["checksum"],
        "residual_checksum": hashlib.sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
        "keeper_gas_units_seed": derive_seed(
            replication, "keeper_gas_units"
        ),
    }
    return {
        "states": states,
        "sampled_market": sampled,
        "market_provenance": market_provenance,
        "arrivals": arrivals,
        "stage1": stage1,
        "residuals": residuals,
        "seed_ownership": seed_record(replication),
        "stream_components": components,
        "paired_stream_checksum": _payload_sha256(components),
    }


def simulate_replication(
    replication: int,
    programme_identity: str | None = None,
) -> dict[str, Any]:
    """Run all eight Experiment A cells for one CRN replication."""
    if (
        scientific_code_identity()
        != REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
    ):
        raise RuntimeError(
            "Experiment A execution is frozen. The current source contains "
            "a post-execution evidence-serialization repair and must not "
            "create or replace simulation checkpoints."
        )
    if programme_identity is None:
        from dai_sim.experiments.final.programme import load_programme

        programme_identity = load_programme().programme_identity
    streams = _prepare_replication_streams(replication)
    nested_audit = audit_nested_initialisations(streams["states"])
    collateral_payload, portfolio_payload, _ = _design_payloads()
    recovery_design = load_recovery_design()
    full_week = next(
        item
        for item in recovery_design.path_definitions
        if item.identifier == "full_week"
    )
    scaling = json.loads(SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8"))
    cell_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    path_audits: dict[str, Any] = {}
    gas_owner_checksums: set[str] = set()
    cells = {cell.identifier: cell for cell in build_cell_registry()}
    for shock in SHOCK_ORDER:
        price_paths, path_audit = build_price_paths(
            streams["sampled_market"], shock
        )
        path_audits[shock] = path_audit
        integrated = resolve_integrated_empirical_eth_profile()
        gas = component_gas_costs(
            sampled_market_gas_rows=streams["sampled_market"],
            simulated_eth_prices=price_paths["ETH"],
            config=replace(
                integrated.gas,
                seed=derive_seed(replication, "keeper_gas_units"),
            ),
        )
        if gas.gas_cost_usd is None or gas.sampled_rows is None:
            raise ValueError("Component gas process did not return a path.")
        gas_component_checksum = _payload_sha256(
            gas.sampled_rows[
                [
                    "gas_pool_row_id",
                    "gas_units",
                    "network_gas_price_gwei",
                ]
            ].to_dict(orient="records")
        )
        gas_owner_checksums.add(gas_component_checksum)
        for portfolio in PORTFOLIO_ORDER:
            identifier = f"{shock}__{portfolio}"
            liquidation = _simulate_cell_liquidations(
                initialisation=streams["states"][portfolio],
                price_paths=price_paths,
                gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
                arrivals=streams["arrivals"],
                portfolio_config=_portfolio_config(
                    portfolio, collateral_payload, portfolio_payload
                ),
            )
            market = _simulate_market_scenario(
                design=recovery_design,
                definition=full_week,
                eth_prices=price_paths["ETH"],
                liquidation=liquidation["arrays"],
                innovations=streams["residuals"],
                scenario_identifier="stage1_only",
                stage1_owners=streams["stage1"],
                peg_scale=float(
                    scaling["lagged_below_peg_gap"]["positive_q95"]
                ),
                eth_scale=float(
                    scaling["lagged_24h_eth_downside"]["positive_q95"]
                ),
                initial_vault_count=VAULT_COUNT,
            )
            system = {
                **liquidation["system_summary"],
                **{
                    key: market["summary"][key]
                    for key in (
                        "below_peg_burden",
                        "mean_absolute_peg_deviation",
                        "minimum_dai_price",
                        "restricted_mean_recovery_time",
                        "recovery_probability_720h",
                        "right_censored",
                    )
                },
                "cell_order": cells[identifier].order,
                "cell_identifier": identifier,
                "shock": shock,
                "portfolio": portfolio,
                "replication": replication,
                "capacity": CAPACITY,
                "hurdle": "direct_cost_only",
                "confidence": "stage1_only",
                "oracle_delay": 0,
                "paired_stream_checksum": streams[
                    "paired_stream_checksum"
                ],
                "state_checksum": streams["states"][portfolio].identity,
                "gas_component_draw_checksum": gas_component_checksum,
                "price_path_checksum": _payload_sha256(
                    path_audit["full_price_checksums"]
                ),
                "price_isolation_valid": path_audit[
                    "price_isolation_valid"
                ],
                "nested_initialisation_valid": nested_audit["passed"],
            }
            system["numerical_valid"] = bool(
                system["numerical_valid"]
                and market["summary"]["numerical_valid"]
            )
            cell_rows.append(system)
            for row in liquidation["collateral_rows"]:
                collateral_rows.append(
                    {
                        "cell_order": cells[identifier].order,
                        "cell_identifier": identifier,
                        "shock": shock,
                        "portfolio": portfolio,
                        "replication": replication,
                        "numerical_valid": system["numerical_valid"],
                        "accounting_valid": system["accounting_valid"],
                        "price_isolation_valid": system[
                            "price_isolation_valid"
                        ],
                        "nested_initialisation_valid": system[
                            "nested_initialisation_valid"
                        ],
                        **row,
                    }
                )
    if len(gas_owner_checksums) != 1:
        raise ValueError("Keeper gas-unit draws drifted across shocks.")
    result = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "replication": replication,
        "scientific_code_identity": (
            REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "profile_identity": PROFILE_IDENTITY,
        "seed_registry_sha256": seed_registry_checksum(),
        "seed_ownership": streams["seed_ownership"],
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "stream_components": streams["stream_components"],
        "nested_initialisation_audit": nested_audit,
        "path_audits": path_audits,
        "cell_rows": cell_rows,
        "collateral_rows": collateral_rows,
        "simulation_count": len(cell_rows),
    }
    result["result_checksum"] = _payload_sha256(
        {
            "programme_identity": result["programme_identity"],
            "experiment_identity": result["experiment_identity"],
            "replication": replication,
            "scientific_code_identity": result["scientific_code_identity"],
            "profile_identity": result["profile_identity"],
            "seed_registry_sha256": result["seed_registry_sha256"],
            "seed_ownership": result["seed_ownership"],
            "paired_stream_checksum": result["paired_stream_checksum"],
            "stream_components": result["stream_components"],
            "nested_initialisation_audit": result[
                "nested_initialisation_audit"
            ],
            "path_audits": result["path_audits"],
            "cell_rows": cell_rows,
            "collateral_rows": collateral_rows,
            "simulation_count": result["simulation_count"],
        }
    )
    return result


def scientific_code_identity() -> str:
    """Hash current Experiment A source, including evidence infrastructure."""
    paths = (
        REPOSITORY_ROOT / "src/dai_sim/experiments/final/programme.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/final/idiosyncratic_diversification.py",
        REPOSITORY_ROOT / "src/dai_sim/common/serialization.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/event_simulation.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/market.py",
        REPOSITORY_ROOT
        / "src/dai_sim/calibration/multicollateral_validation.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/configuration.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/gas.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/integrated_profile.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/liquidations.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/market.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/multicollateral.py",
        REPOSITORY_ROOT / "src/dai_sim/model/collateral.py",
        REPOSITORY_ROOT / "src/dai_sim/model/confidence.py",
        REPOSITORY_ROOT / "src/dai_sim/model/liquidation.py",
        REPOSITORY_ROOT / "src/dai_sim/model/market.py",
        REPOSITORY_ROOT / "src/dai_sim/model/vault.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/mechanism/eth_recovery.py",
        REPOSITORY_ROOT / "src/dai_sim/validation/multicollateral.py",
        REPOSITORY_ROOT
        / "workflows/experiments/final/idiosyncratic_diversification.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Missing Experiment A scientific owner: {path}.")
        digest.update(_relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def experiment_identity(programme_identity: str) -> str:
    """Return the historically registered result-blind identity."""
    identity = _payload_sha256(
        {
            "schema_version": 1,
            "parent_commit": STARTING_CODE_PARENT,
            "programme_identity": programme_identity,
            "scientific_code_identity": (
                REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
            ),
            "profile_identity": PROFILE_IDENTITY,
            "profile_sha256": PROFILE_SHA256,
            "registry_checksums": {
                "collateral": COLLATERAL_REGISTRY_SHA256,
                "portfolio": PORTFOLIO_REGISTRY_SHA256,
                "shock": SHOCK_REGISTRY_SHA256,
                "keeper": KEEPER_REGISTRY_SHA256,
                "confidence": CONFIDENCE_REGISTRY_SHA256,
            },
            "stage1": {
                "below_peg_response": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
                "above_peg_response": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
                "residual_sequence": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
                "residual_blocks": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
            },
            "cells": [asdict(cell) for cell in build_cell_registry()],
            "seed_registry_sha256": seed_registry_checksum(),
            "system_metrics": list(SYSTEM_METRICS),
            "system_diagnostics": list(SYSTEM_DIAGNOSTICS),
            "collateral_metrics": list(COLLATERAL_METRICS),
            "contrasts": {
                shock: [list(pair) for pair in pairs]
                for shock, pairs in CONTRASTS.items()
            },
            "horizon": {
                "pre_shock_hours": PRE_SHOCK_HOURS,
                "post_shock_hours": POST_SHOCK_HOURS,
                "total_hours": TOTAL_HOURS,
                "registered_kernel_onset_hour": REGISTERED_KERNEL_ONSET,
                "kernel_embedding_start_hour": KERNEL_EMBEDDING_START,
            },
            "final_validation_data_used": False,
        }
    )
    if identity != REGISTERED_EXPERIMENT_IDENTITY:
        raise ValueError("Registered Experiment A identity reconstruction differs.")
    return identity


def specification_payload(programme_identity: str) -> dict[str, Any]:
    """Build the immutable, result-blind Experiment A specification."""
    cells = build_cell_registry()
    seed_registry = [
        seed_record(replication) for replication in range(REPLICATIONS)
    ]
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "purpose": (
            "Estimate idiosyncratic-shock diversification effects without "
            "ranking or selecting a portfolio."
        ),
        "parent_commit": STARTING_CODE_PARENT,
        "programme_identity": programme_identity,
        "scientific_code_identity": (
            REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "experiment_identity": experiment_identity(programme_identity),
        "research_question": "RQ4",
        "hypothesis": "H3",
        "analytical_components": {
            "A1": "ETH-shock diversification",
            "A2": "WBTC exposure gradient",
            "A3": "shock localisation",
        },
        "profile": {
            "identifier": "empirical_integrated_multicollateral",
            "identity": PROFILE_IDENTITY,
            "sha256": PROFILE_SHA256,
            "vault_count": VAULT_COUNT,
            "total_debt_dai": TOTAL_DEBT_DAI,
            "target_system_collateral_ratio": TARGET_SYSTEM_COLLATERAL_RATIO,
        },
        "registry_checksums": {
            "collateral": COLLATERAL_REGISTRY_SHA256,
            "portfolio": PORTFOLIO_REGISTRY_SHA256,
            "shock": SHOCK_REGISTRY_SHA256,
            "keeper": KEEPER_REGISTRY_SHA256,
            "confidence": CONFIDENCE_REGISTRY_SHA256,
            "shock_evidence": SHOCK_EVIDENCE_SHA256,
        },
        "cell_order": [cell.identifier for cell in cells],
        "replications_per_cell": REPLICATIONS,
        "substantive_simulations": len(cells) * REPLICATIONS,
        "seed_ownership": {
            "registry_id": EXPERIMENT_NAMESPACE,
            "streams": list(SEED_STREAMS),
            "nested_family_draws": True,
            "common_random_numbers": True,
            "seed_registry_sha256": seed_registry_checksum(),
            "replication_registry": seed_registry,
        },
        "treatments": {
            "capacity": CAPACITY,
            "capacity_semantics": "one system-wide shared capacity",
            "hurdle": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "confidence": "stage1_only",
            "oracle_delay": 0,
            "recovery": "full_week",
        },
        "horizon": {
            "pre_shock_hours": PRE_SHOCK_HOURS,
            "post_shock_hours": POST_SHOCK_HOURS,
            "total_hours": TOTAL_HOURS,
            "registered_kernel_onset_hour": REGISTERED_KERNEL_ONSET,
            "registered_kernel_hours": REGISTERED_KERNEL_HOURS,
            "ordinary_warmup_before_kernel_hours": KERNEL_EMBEDDING_START,
            "experiment_shock_hour": PRE_SHOCK_HOURS,
            "translation_rule": (
                "prepend 24 ordinary hours, retain the registered 216-hour "
                "kernel byte-for-byte, then retain its terminal multiplier"
            ),
        },
        "recovery_definition": {
            "band": [0.995, 1.005],
            "consecutive_hours": 24,
            "restricted_mean_cap_hours": 720,
            "owner": "dai_sim.experiments.mechanism.eth_recovery",
        },
        "primary_outcomes": list(SYSTEM_METRICS),
        "capacity_diagnostics": list(SYSTEM_DIAGNOSTICS),
        "collateral_decomposition": list(COLLATERAL_METRICS),
        "contrasts": {
            shock: [f"{left} - {right}" for left, right in pairs]
            for shock, pairs in CONTRASTS.items()
        },
        "decision_rules": {
            "A1": {
                "beneficial_metrics": [
                    "realised_bad_debt_share",
                    "backlog_area_share",
                    "liquidated_debt_share",
                ],
                "beneficial_rule": (
                    "at least two paired 95% intervals below zero and no "
                    "clearly adverse realised-bad-debt interval"
                ),
                "supported": "at least two diversified portfolios satisfy",
                "partially_supported": "exactly one portfolio satisfies",
                "not_supported": "none satisfies",
            },
            "A2": {
                "raw_gradient_rule": (
                    "at least two informative, non-constant metrics among "
                    "liquidated debt, backlog and bad debt are "
                    "non-decreasing with initial WBTC exposure"
                ),
                "consistent": (
                    "clean ETH-only negative control and at least two "
                    "informative non-decreasing raw metrics"
                ),
                "mixed": (
                    "clean ETH-only negative control and exactly one "
                    "informative non-decreasing raw metric"
                ),
                "inconsistent": (
                    "clean ETH-only negative control and no informative "
                    "non-decreasing raw metric"
                ),
                "invalid": (
                    "experiment validity failure or non-zero direct ETH-only "
                    "WBTC loss"
                ),
                "normalised_rule": (
                    "interpret exposure-normalised outcomes separately and "
                    "require the ETH-only direct-loss negative control"
                ),
            },
            "A3": "all price-isolation, path-order and accounting audits pass",
            "h3_exhaustive_resolution": (
                "apply the named supported, partially-supported and "
                "exposure-effect-only cases first; otherwise classify a "
                "valid but contradictory or unsupported combination as "
                "H3_no_clear_idiosyncratic_diversification"
            ),
            "overall_h3_labels": [
                "H3_idiosyncratic_diversification_supported",
                "H3_idiosyncratic_diversification_partially_supported",
                "H3_idiosyncratic_exposure_effect_only",
                "H3_no_clear_idiosyncratic_diversification",
                "H3_idiosyncratic_experiment_invalid",
            ],
        },
        "peg_solvency_rule": {
            "peg_metrics": {
                "below_peg_burden": "lower_is_beneficial",
                "mean_absolute_peg_deviation": "lower_is_beneficial",
                "minimum_dai_price": "higher_is_beneficial",
                "restricted_mean_recovery_time": "lower_is_beneficial",
                "recovery_probability_720h": "higher_is_beneficial",
            },
            "portfolio_peg_classification": (
                "at least three of five paired 95% intervals in one "
                "direction"
            ),
            "comparison_basis": (
                "each diversified portfolio against eth_only under the "
                "ETH idiosyncratic shock"
            ),
            "divergence_rule": (
                "a solvency-beneficial portfolio is peg-adverse, or "
                "solvency and peg benefits occur only in disjoint portfolios"
            ),
        },
        "bad_debt_measurement_boundary": (
            "Use the canonical liquidation owner without correction. "
            "Realised bad debt is retained as registered, but a structurally "
            "zero result under full-close canonical repayment semantics is "
            "reported as a measurement limitation and is not retuned."
        ),
        "numerical_failure_limit_per_cell": 0.01,
        "no_aggregate_score": True,
        "no_portfolio_ranking": True,
        "no_shock_ranking": True,
        "no_retuning_after_results": True,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "runtime_adopted": False,
    }


def _registry_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(cell) for cell in build_cell_registry()])


def write_preregistration(programme_identity: str) -> dict[str, Any]:
    """Persist immutable Experiment A pre-registration before execution."""
    specification = specification_payload(programme_identity)
    registry = _registry_frame()
    paths = {
        "specification": EVIDENCE_DIR
        / "idiosyncratic_diversification_specification.json",
        "registry": EVIDENCE_DIR
        / "idiosyncratic_diversification_registry.csv",
    }
    specification_bytes = _pretty_json(specification)
    registry_bytes = _csv_bytes(registry)
    for path, payload in (
        (paths["specification"], specification_bytes),
        (paths["registry"], registry_bytes),
    ):
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"Existing pre-registration differs: {path}.")
        _atomic_bytes(path, payload)
    update_experiment_manifest(
        _manifest_records(
            paths.values(),
            "pre_registered_final_idiosyncratic_diversification_experiment",
        )
    )
    return {
        "experiment_identity": specification["experiment_identity"],
        "specification_sha256": sha256_file(paths["specification"]),
        "registry_sha256": sha256_file(paths["registry"]),
        "seed_registry_sha256": seed_registry_checksum(),
    }


def _checkpoint_path(output_dir: Path, replication: int) -> Path:
    return output_dir / "checkpoints" / f"replication_{replication:03d}.json"


def _valid_checkpoint(
    path: Path,
    replication: int,
    programme_identity: str | None = None,
) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = _payload_sha256(
            {
                "programme_identity": payload["programme_identity"],
                "experiment_identity": payload["experiment_identity"],
                "replication": replication,
                "scientific_code_identity": payload[
                    "scientific_code_identity"
                ],
                "profile_identity": payload["profile_identity"],
                "seed_registry_sha256": payload["seed_registry_sha256"],
                "seed_ownership": payload["seed_ownership"],
                "paired_stream_checksum": payload["paired_stream_checksum"],
                "stream_components": payload["stream_components"],
                "nested_initialisation_audit": payload[
                    "nested_initialisation_audit"
                ],
                "path_audits": payload["path_audits"],
                "cell_rows": payload["cell_rows"],
                "collateral_rows": payload["collateral_rows"],
                "simulation_count": payload["simulation_count"],
            }
        )
        from dai_sim.experiments.final.programme import load_programme

        expected_programme_identity = (
            programme_identity
            if programme_identity is not None
            else load_programme().programme_identity
        )
        cell_identifiers = [
            str(row.get("cell_identifier")) for row in payload["cell_rows"]
        ]
        collateral_keys = [
            (
                str(row.get("cell_identifier")),
                str(row.get("family")),
            )
            for row in payload["collateral_rows"]
        ]
        expected_collateral_keys = [
            (cell_identifier, family)
            for cell_identifier in CELL_ORDER
            for family in FAMILY_ORDER
        ]
        return bool(
            payload["experiment_id"] == EXPERIMENT_ID
            and payload["programme_identity"] == expected_programme_identity
            and payload["experiment_identity"]
            == experiment_identity(expected_programme_identity)
            and payload["replication"] == replication
            and payload["scientific_code_identity"]
            == REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
            and payload["profile_identity"] == PROFILE_IDENTITY
            and payload["seed_registry_sha256"]
            == seed_registry_checksum(128)
            and payload["simulation_count"] == 8
            and len(payload["cell_rows"]) == 8
            and len(payload["collateral_rows"]) == 24
            and cell_identifiers == list(CELL_ORDER)
            and collateral_keys == expected_collateral_keys
            and payload["nested_initialisation_audit"]["passed"]
            and tuple(payload["path_audits"]) == SHOCK_ORDER
            and payload["result_checksum"] == expected
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _output_dir(programme_identity: str) -> Path:
    return OUTPUT_ROOT / experiment_identity(programme_identity)


def audit_checkpoints(programme_identity: str) -> dict[str, Any]:
    output_dir = _output_dir(programme_identity)
    expected = {
        _checkpoint_path(output_dir, replication)
        for replication in range(REPLICATIONS)
    }
    observed = set((output_dir / "checkpoints").glob("replication_*.json"))
    observed_replications: list[int] = []
    for path in sorted(observed):
        try:
            observed_replications.append(
                int(json.loads(path.read_text(encoding="utf-8"))["replication"])
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    duplicate_checkpoints = len(observed_replications) - len(
        set(observed_replications)
    )
    valid = sum(
        _valid_checkpoint(
            _checkpoint_path(output_dir, replication),
            replication,
            programme_identity,
        )
        for replication in range(REPLICATIONS)
    )
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "expected_checkpoints": REPLICATIONS,
        "observed_checkpoints": len(observed),
        "valid_checkpoints": valid,
        "missing_checkpoints": len(expected - observed),
        "orphan_checkpoints": len(observed - expected),
        "duplicate_checkpoints": duplicate_checkpoints,
        "passed": (
            observed == expected
            and valid == REPLICATIONS
            and duplicate_checkpoints == 0
        ),
    }


def preflight(programme_identity: str) -> dict[str, Any]:
    """Validate all frozen owners, cells, streams, paths and storage."""
    for portfolio in PORTFOLIO_ORDER:
        resolved = resolve_multicollateral_inputs(portfolio, SHOCK_ORDER[0])
        if (
            resolved.profile.identifier
            != "empirical_integrated_multicollateral"
            or resolved.profile.checksum != PROFILE_SHA256
            or resolved.profile.runtime_adopted
        ):
            raise ValueError("Integrated multi-collateral profile changed.")
    cells = build_cell_registry()
    seed_records = [
        seed_record(replication) for replication in range(REPLICATIONS)
    ]
    seed_values = [
        int(record[f"{stream}_seed"])
        for record in seed_records
        for stream in SEED_STREAMS
    ]
    if [record["replication"] for record in seed_records] != list(
        range(REPLICATIONS)
    ):
        raise ValueError("Experiment A replication identities are incomplete.")
    if len(seed_values) != len(set(seed_values)):
        raise ValueError("Experiment A seed registry contains a collision.")
    kernels = {
        shock: registered_shock_kernels(shock) for shock in SHOCK_ORDER
    }
    free = shutil.disk_usage(REPOSITORY_ROOT).free
    if free < MINIMUM_FREE_BYTES:
        raise RuntimeError("Fewer than 10 GiB remain.")
    projected = REPLICATIONS * 200_000
    if projected > MAXIMUM_OUTPUT_BYTES:
        raise RuntimeError("Projected Experiment A output exceeds 500 MB.")
    return {
        "parent_commit": STARTING_CODE_PARENT,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "cell_count": len(cells),
        "replications_per_cell": REPLICATIONS,
        "simulation_count": len(cells) * REPLICATIONS,
        "replication_identity_count": len(seed_records),
        "seed_value_count": len(seed_values),
        "seed_collision_count": 0,
        "seed_registry_sha256": seed_registry_checksum(),
        "kernel_checksums": {
            shock: {
                family: hashlib.sha256(
                    np.asarray(values, dtype="<f8").tobytes()
                ).hexdigest()
                for family, values in families.items()
            }
            for shock, families in kernels.items()
        },
        "free_storage_bytes": free,
        "projected_new_output_bytes": projected,
        "minimum_free_storage_satisfied": True,
        "runtime_adopted": False,
    }


def run_smoke(replication: int = 0) -> dict[str, Any]:
    """Run one result-blind eight-cell audit without reporting outcomes."""
    result = simulate_replication(replication)
    cells = pd.DataFrame(result["cell_rows"]).sort_values("cell_order")
    if cells["cell_identifier"].tolist() != list(CELL_ORDER):
        raise ValueError("Smoke cell order differs.")
    if cells["paired_stream_checksum"].nunique() != 1:
        raise ValueError("Smoke process-stream ownership differs.")
    if not cells["price_isolation_valid"].all():
        raise ValueError("Smoke price isolation failed.")
    if not cells["accounting_valid"].all():
        raise ValueError("Smoke accounting failed.")
    if not cells["numerical_valid"].all():
        raise ValueError("Smoke numerical validation failed.")
    return {
        "replication": replication,
        "cell_count": len(cells),
        "paired_stream_checksum": cells["paired_stream_checksum"].iloc[0],
        "nested_initialisation_valid": result[
            "nested_initialisation_audit"
        ]["passed"],
        "cell_order_valid": True,
        "price_isolation_valid": True,
        "accounting_valid": True,
        "numerical_valid": True,
        "capacity": CAPACITY,
        "direct_cost_only": True,
        "stage1_only": True,
    }


def _worker_initialiser() -> None:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = "1"


def run_matrix(
    programme_identity: str,
    *,
    workers: int = 4,
    resume: bool = True,
    max_replications: int | None = None,
) -> dict[str, Any]:
    """Execute or resume atomic one-replication/eight-cell checkpoints."""
    if not 1 <= workers <= 8:
        raise ValueError("workers must lie in [1, 8].")
    specification = (
        EVIDENCE_DIR / "idiosyncratic_diversification_specification.json"
    )
    if not specification.is_file():
        raise ValueError("Substantive execution requires pre-registration.")
    registered = json.loads(specification.read_text(encoding="utf-8"))
    identity = experiment_identity(programme_identity)
    if registered["experiment_identity"] != identity:
        raise ValueError("Experiment A pre-registration identity differs.")
    count = REPLICATIONS if max_replications is None else int(max_replications)
    if not 1 <= count <= REPLICATIONS:
        raise ValueError("max_replications lies outside the registered design.")
    output_dir = _output_dir(programme_identity)
    tasks: list[int] = []
    reused = 0
    for replication in range(count):
        checkpoint = _checkpoint_path(output_dir, replication)
        if _valid_checkpoint(checkpoint, replication, programme_identity):
            if not resume:
                raise ValueError("Refusing to overwrite a valid checkpoint.")
            reused += 1
        elif checkpoint.exists():
            raise ValueError(f"Invalid checkpoint requires review: {checkpoint}.")
        else:
            tasks.append(replication)
    started = time.perf_counter()
    completed = 0
    if workers == 1:
        _worker_initialiser()
        for replication in tasks:
            result = simulate_replication(replication, programme_identity)
            _atomic_json(_checkpoint_path(output_dir, replication), result)
            completed += 1
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_worker_initialiser,
        ) as executor:
            futures = {
                executor.submit(
                    simulate_replication,
                    replication,
                    programme_identity,
                ): replication
                for replication in tasks
            }
            for future in as_completed(futures):
                replication = futures[future]
                result = future.result()
                _atomic_json(_checkpoint_path(output_dir, replication), result)
                completed += 1
    wall = time.perf_counter() - started
    output_size = sum(
        path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
    )
    if output_size > MAXIMUM_OUTPUT_BYTES:
        raise RuntimeError("Experiment A output exceeds 500 MB.")
    return {
        "experiment_identity": identity,
        "worker_count": workers,
        "completed_replications": completed,
        "reused_replications": reused,
        "resumed_replications": reused if resume else 0,
        "failed_replications": 0,
        "rerun_replications": 0,
        "checkpoint_count": completed + reused,
        "completed_simulations": (completed + reused) * 8,
        "wall_time_seconds": wall,
        "throughput_simulations_per_second": (
            0.0 if wall == 0.0 else completed * 8 / wall
        ),
        "output_size_bytes": output_size,
        "free_storage_bytes": shutil.disk_usage(REPOSITORY_ROOT).free,
        "complete": completed + reused == REPLICATIONS,
    }


def load_results(
    programme_identity: str,
    *,
    require_complete: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load all valid checkpoints in stable cell/replication order."""
    output_dir = _output_dir(programme_identity)
    cell_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    for replication in range(REPLICATIONS):
        path = _checkpoint_path(output_dir, replication)
        if not _valid_checkpoint(path, replication, programme_identity):
            if require_complete:
                raise ValueError(f"Missing valid checkpoint: {path}.")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        cell_rows.extend(payload["cell_rows"])
        collateral_rows.extend(payload["collateral_rows"])
    cells = pd.DataFrame(cell_rows)
    collateral = pd.DataFrame(collateral_rows)
    if require_complete and (
        len(cells) != REPLICATIONS * 8
        or len(collateral) != REPLICATIONS * 8 * len(FAMILY_ORDER)
    ):
        raise ValueError("Experiment A result dimensions differ.")
    if not cells.empty:
        for replication, group in cells.groupby("replication"):
            if (
                len(group) != 8
                or group["paired_stream_checksum"].nunique() != 1
            ):
                raise ValueError(
                    f"CRN ownership failed for replication {replication}."
                )
        cells = cells.sort_values(
            ["cell_order", "replication"], kind="mergesort"
        ).reset_index(drop=True)
        collateral = collateral.sort_values(
            ["cell_order", "family", "replication"], kind="mergesort"
        ).reset_index(drop=True)
    return cells, collateral


def _distribution(values: Iterable[float]) -> dict[str, float]:
    array = np.asarray(list(values), dtype=float)
    if len(array) == 0 or not np.isfinite(array).all():
        raise ValueError("Distribution requires finite observations.")
    mean = float(array.mean())
    se = (
        float(array.std(ddof=1) / math.sqrt(len(array)))
        if len(array) > 1
        else 0.0
    )
    return {
        "mean": mean,
        "standard_error": se,
        "ci95_lower": mean - 1.96 * se,
        "ci95_upper": mean + 1.96 * se,
        "median": float(np.median(array)),
        "p05": float(np.quantile(array, 0.05)),
        "p25": float(np.quantile(array, 0.25)),
        "p75": float(np.quantile(array, 0.75)),
        "p90": float(np.quantile(array, 0.90)),
        "p95": float(np.quantile(array, 0.95)),
        "minimum": float(array.min()),
        "maximum": float(array.max()),
        "positive_share": float(np.mean(array > 0)),
    }


def _valid_rows(frame: pd.DataFrame) -> pd.Series:
    valid = pd.Series(True, index=frame.index, dtype=bool)
    for column in (
        "numerical_valid",
        "accounting_valid",
        "price_isolation_valid",
        "nested_initialisation_valid",
    ):
        if column in frame:
            valid &= frame[column].astype(bool)
    return valid


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, group in frame.groupby(
        ["cell_order", "cell_identifier", "shock", "portfolio"],
        sort=False,
    ):
        valid_mask = _valid_rows(group)
        failures = int((~valid_mask).sum())
        valid_group = group.loc[valid_mask]
        if valid_group.empty:
            raise ValueError("A cell has no valid replications to summarise.")
        for metric in (*SYSTEM_METRICS, *SYSTEM_DIAGNOSTICS):
            rows.append(
                {
                    **dict(
                        zip(
                            (
                                "cell_order",
                                "cell_identifier",
                                "shock",
                                "portfolio",
                            ),
                            key,
                            strict=True,
                        )
                    ),
                    "metric": metric,
                    "valid_replication_count": int(len(valid_group)),
                    **_distribution(valid_group[metric]),
                    "censoring_count": (
                        int(valid_group["right_censored"].sum())
                        if metric == "restricted_mean_recovery_time"
                        else 0
                    ),
                    "numerical_failure_count": failures,
                }
            )
    return pd.DataFrame(rows)


def collateral_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = [
        "cell_order",
        "cell_identifier",
        "shock",
        "portfolio",
        "family",
    ]
    for key, group in frame.groupby(group_columns, sort=False):
        valid_group = group.loc[_valid_rows(group)]
        for metric in COLLATERAL_METRICS:
            values = pd.to_numeric(valid_group[metric], errors="coerce")
            applicable = values.notna()
            row = {
                **dict(zip(group_columns, key, strict=True)),
                "metric": metric,
                "applicable_replication_count": int(applicable.sum()),
                "not_applicable_replication_count": int(
                    len(valid_group) - applicable.sum()
                ),
                "invalid_replication_count": int(
                    len(group) - len(valid_group)
                ),
            }
            if applicable.any():
                row.update(_distribution(values[applicable]))
            else:
                row.update(
                    {
                        name: None
                        for name in (
                            "mean",
                            "standard_error",
                            "ci95_lower",
                            "ci95_upper",
                            "median",
                            "p05",
                            "p25",
                            "p75",
                            "p90",
                            "p95",
                            "minimum",
                            "maximum",
                            "positive_share",
                        )
                    }
                )
            rows.append(row)
    return pd.DataFrame(rows)


def paired_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for shock, pairs in CONTRASTS.items():
        selected = frame.loc[frame["shock"].eq(shock)]
        for left, right in pairs:
            left_frame = selected.loc[selected["portfolio"].eq(left)]
            right_frame = selected.loc[selected["portfolio"].eq(right)]
            paired = left_frame.merge(
                right_frame,
                on="replication",
                suffixes=("_left", "_right"),
                validate="one_to_one",
            )
            if len(paired) != REPLICATIONS:
                raise ValueError("Paired contrast lost replications.")
            paired_valid = pd.Series(True, index=paired.index, dtype=bool)
            for column in (
                "numerical_valid",
                "accounting_valid",
                "price_isolation_valid",
                "nested_initialisation_valid",
            ):
                left_column = f"{column}_left"
                right_column = f"{column}_right"
                if left_column in paired:
                    paired_valid &= paired[left_column].astype(bool)
                if right_column in paired:
                    paired_valid &= paired[right_column].astype(bool)
            paired = paired.loc[paired_valid]
            if paired.empty:
                raise ValueError("A contrast has no valid replication pairs.")
            for metric in SYSTEM_METRICS:
                differences = (
                    paired[f"{metric}_left"].to_numpy(dtype=float)
                    - paired[f"{metric}_right"].to_numpy(dtype=float)
                )
                row = {
                    "shock": shock,
                    "left_portfolio": left,
                    "right_portfolio": right,
                    "contrast": f"{left} - {right}",
                    "metric": metric,
                    "pair_count": len(paired),
                    **_distribution(differences),
                }
                if metric in BINARY_METRICS:
                    left_values = paired[f"{metric}_left"].astype(int)
                    right_values = paired[f"{metric}_right"].astype(int)
                    row["discordant_left_one_right_zero"] = int(
                        ((left_values == 1) & (right_values == 0)).sum()
                    )
                    row["discordant_left_zero_right_one"] = int(
                        ((left_values == 0) & (right_values == 1)).sum()
                    )
                else:
                    row["discordant_left_one_right_zero"] = None
                    row["discordant_left_zero_right_one"] = None
                rows.append(row)
    return pd.DataFrame(rows)


def _contrast(
    contrasts: pd.DataFrame,
    shock: str,
    left: str,
    right: str,
    metric: str,
) -> pd.Series:
    selected = contrasts.loc[
        contrasts["shock"].eq(shock)
        & contrasts["left_portfolio"].eq(left)
        & contrasts["right_portfolio"].eq(right)
        & contrasts["metric"].eq(metric)
    ]
    if len(selected) != 1:
        raise ValueError("Expected one registered paired contrast row.")
    return selected.iloc[0]


def classify_a1(contrasts: pd.DataFrame, *, valid: bool) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "invalid", {}
    outcomes: dict[str, Any] = {}
    qualifying = 0
    for portfolio in PORTFOLIO_ORDER[1:]:
        rows = {
            metric: _contrast(
                contrasts,
                "eth_idiosyncratic_severe",
                portfolio,
                "eth_only",
                metric,
            )
            for metric in (
                "realised_bad_debt_share",
                "backlog_area_share",
                "liquidated_debt_share",
            )
        }
        beneficial = sum(row["ci95_upper"] < 0 for row in rows.values())
        no_bad_debt_adverse = (
            rows["realised_bad_debt_share"]["ci95_lower"] <= 0
        )
        qualifies = beneficial >= 2 and no_bad_debt_adverse
        qualifying += int(qualifies)
        outcomes[portfolio] = {
            "beneficial_interval_count": beneficial,
            "no_clear_bad_debt_adverse_effect": bool(no_bad_debt_adverse),
            "beneficial_rule_satisfied": bool(qualifies),
        }
    classification = (
        "supported"
        if qualifying >= 2
        else "partially_supported" if qualifying == 1 else "not_supported"
    )
    return classification, outcomes


def classify_a2(
    cells: pd.DataFrame,
    collateral: pd.DataFrame,
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "exposure_gradient_invalid", {}
    selected = collateral.loc[
        collateral["shock"].eq("wbtc_idiosyncratic_severe")
        & collateral["family"].eq("WBTC")
    ]
    selected = selected.loc[_valid_rows(selected)]
    means = (
        selected.groupby("portfolio", sort=False)
        .mean(numeric_only=True)
        .loc[list(PORTFOLIO_ORDER)]
    )
    raw_metrics = ("liquidated_debt", "backlog_area", "realised_bad_debt")
    negative_control = bool(
        all(abs(float(means.loc["eth_only", metric])) <= 1e-9 for metric in raw_metrics)
        and (
            "initial_debt_exposure" not in means
            or abs(float(means.loc["eth_only", "initial_debt_exposure"]))
            <= 1e-9
        )
    )
    if "initial_debt_exposure" in means:
        ordered = list(
            means["initial_debt_exposure"]
            .sort_values(kind="mergesort")
            .index
        )
    else:
        ordered = [
            "eth_only",
            "stable_supported",
            "empirical_crypto",
            "balanced_crypto",
        ]
    consistent_count = 0
    informative_count = 0
    raw_metric_diagnostics: dict[str, Any] = {}
    for metric in raw_metrics:
        values = means.loc[ordered, metric].to_numpy(dtype=float)
        informative = bool(np.ptp(values) > 1e-8)
        consistent = bool(
            informative and np.all(np.diff(values) >= -1e-8)
        )
        informative_count += int(informative)
        consistent_count += int(consistent)
        raw_metric_diagnostics[metric] = {
            "informative_nonconstant": informative,
            "nondecreasing_with_exposure": consistent,
            "range": float(np.ptp(values)),
        }
    if not negative_control:
        classification = "exposure_gradient_invalid"
    elif consistent_count >= 2:
        classification = "exposure_gradient_consistent"
    elif consistent_count == 1:
        classification = "exposure_gradient_mixed"
    else:
        classification = "exposure_gradient_inconsistent"
    comparisons: dict[str, Any] = {}
    system_metrics = (
        "realised_bad_debt_share",
        "backlog_area_share",
        "liquidated_debt_share",
    )
    normalised_metrics = (
        "exposure_normalised_liquidated_debt",
        "exposure_normalised_backlog",
        "exposure_normalised_bad_debt",
    )
    valid_cells = cells.loc[_valid_rows(cells)] if not cells.empty else cells
    system_means = (
        valid_cells.loc[
            valid_cells["shock"].eq("wbtc_idiosyncratic_severe")
        ]
        .groupby("portfolio", sort=False)
        .mean(numeric_only=True)
        if not valid_cells.empty
        and {"shock", "portfolio"} <= set(valid_cells)
        else pd.DataFrame()
    )
    for comparator in ("empirical_crypto", "balanced_crypto"):
        comparisons[comparator] = {
            "system_mean_differences": {
                metric: (
                    float(
                        system_means.loc["stable_supported", metric]
                        - system_means.loc[comparator, metric]
                    )
                    if metric in system_means
                    else None
                )
                for metric in system_metrics
            },
            "exposure_normalised_mean_differences": {
                metric: (
                    float(
                        means.loc["stable_supported", metric]
                        - means.loc[comparator, metric]
                    )
                    if metric in means
                    else None
                )
                for metric in normalised_metrics
            },
        }
    return classification, {
        "eth_only_direct_wbtc_loss_zero": bool(negative_control),
        "wbtc_exposure_order": ordered,
        "raw_gradient_informative_metric_count": informative_count,
        "raw_gradient_consistent_metric_count": consistent_count,
        "raw_metric_diagnostics": raw_metric_diagnostics,
        "raw_metrics_checked": list(raw_metrics),
        "stable_supported_comparisons": comparisons,
        "system_metrics_retained": list(system_metrics),
        "exposure_normalised_metrics_retained": list(normalised_metrics),
    }


def classify_results(
    cells: pd.DataFrame,
    collateral: pd.DataFrame,
    contrasts: pd.DataFrame,
) -> dict[str, Any]:
    numerical_failures = (
        cells.assign(failed=~cells["numerical_valid"].astype(bool))
        .groupby("cell_identifier")["failed"]
        .mean()
    )
    crn_valid = True
    path_order_valid = True
    state_reuse_valid = True
    if {"replication", "paired_stream_checksum"} <= set(cells):
        crn_groups = cells.groupby("replication", sort=False)
        crn_valid = bool(
            crn_groups.size().eq(len(CELL_ORDER)).all()
            and crn_groups["paired_stream_checksum"].nunique().eq(1).all()
        )
    if {"replication", "shock", "price_path_checksum"} <= set(cells):
        path_order_valid = bool(
            cells.groupby(["replication", "shock"], sort=False)[
                "price_path_checksum"
            ]
            .nunique()
            .eq(1)
            .all()
        )
    if {"replication", "portfolio", "state_checksum"} <= set(cells):
        state_reuse_valid = bool(
            cells.groupby(["replication", "portfolio"], sort=False)[
                "state_checksum"
            ]
            .nunique()
            .eq(1)
            .all()
        )
    nested_valid = bool(
        cells.get(
            "nested_initialisation_valid",
            pd.Series(True, index=cells.index),
        )
        .astype(bool)
        .all()
    )
    valid = bool(
        (numerical_failures <= 0.01).all()
        and cells["accounting_valid"].all()
        and cells["price_isolation_valid"].all()
        and nested_valid
        and crn_valid
        and path_order_valid
        and state_reuse_valid
    )
    a1, a1_detail = classify_a1(contrasts, valid=valid)
    a2, a2_detail = classify_a2(cells, collateral, valid=valid)
    localisation_valid = bool(
        valid and a2 != "exposure_gradient_invalid"
    )
    a3 = (
        "shock_localisation_valid"
        if localisation_valid
        else "shock_localisation_invalid"
    )
    if not localisation_valid:
        h3 = "H3_idiosyncratic_experiment_invalid"
    elif a1 == "supported" and a2 == "exposure_gradient_consistent":
        h3 = "H3_idiosyncratic_diversification_supported"
    elif a1 == "partially_supported" or a2 == "exposure_gradient_mixed":
        h3 = "H3_idiosyncratic_diversification_partially_supported"
    elif a1 == "not_supported" and a2 == "exposure_gradient_consistent":
        h3 = "H3_idiosyncratic_exposure_effect_only"
    else:
        h3 = "H3_no_clear_idiosyncratic_diversification"
    solvency_portfolios = {
        portfolio
        for portfolio, detail in a1_detail.items()
        if detail["beneficial_rule_satisfied"]
    }
    peg_metrics = {
        "below_peg_burden": "lower",
        "mean_absolute_peg_deviation": "lower",
        "minimum_dai_price": "higher",
        "restricted_mean_recovery_time": "lower",
        "recovery_probability_720h": "higher",
    }
    peg_detail: dict[str, Any] = {}
    peg_beneficial_portfolios: set[str] = set()
    peg_adverse_portfolios: set[str] = set()
    for portfolio in PORTFOLIO_ORDER[1:]:
        beneficial_count = 0
        adverse_count = 0
        metric_results: dict[str, str] = {}
        for metric, direction in peg_metrics.items():
            row = _contrast(
                contrasts,
                "eth_idiosyncratic_severe",
                portfolio,
                "eth_only",
                metric,
            )
            if direction == "lower":
                beneficial = bool(row["ci95_upper"] < 0)
                adverse = bool(row["ci95_lower"] > 0)
            else:
                beneficial = bool(row["ci95_lower"] > 0)
                adverse = bool(row["ci95_upper"] < 0)
            beneficial_count += int(beneficial)
            adverse_count += int(adverse)
            metric_results[metric] = (
                "beneficial"
                if beneficial
                else "adverse" if adverse else "unchanged"
            )
        peg_beneficial = beneficial_count >= 3
        peg_adverse = adverse_count >= 3
        if peg_beneficial:
            peg_beneficial_portfolios.add(portfolio)
        if peg_adverse:
            peg_adverse_portfolios.add(portfolio)
        peg_detail[portfolio] = {
            "beneficial_metric_count": beneficial_count,
            "adverse_metric_count": adverse_count,
            "majority_beneficial": peg_beneficial,
            "majority_adverse": peg_adverse,
            "metric_results": metric_results,
        }
    adverse_solvency_portfolios = (
        solvency_portfolios & peg_adverse_portfolios
    )
    common_improvement_portfolios = (
        solvency_portfolios & peg_beneficial_portfolios
    )
    disjoint_improvement = bool(
        solvency_portfolios
        and peg_beneficial_portfolios
        and not common_improvement_portfolios
    )
    if not localisation_valid:
        relationship = "relationship_invalid"
    elif adverse_solvency_portfolios or disjoint_improvement:
        relationship = "solvency_and_peg_diverge"
    elif common_improvement_portfolios:
        relationship = "solvency_and_peg_improve"
    elif solvency_portfolios:
        relationship = "solvency_improves_peg_unchanged"
    elif peg_beneficial_portfolios:
        relationship = "peg_improves_solvency_unchanged"
    elif peg_adverse_portfolios:
        relationship = "solvency_and_peg_diverge"
    else:
        relationship = "neither_materially_changes"
    return {
        "A1": a1,
        "A1_detail": a1_detail,
        "A2": a2,
        "A2_detail": a2_detail,
        "A3": a3,
        "overall_h3_classification": h3,
        "peg_solvency_relationship": relationship,
        "peg_solvency_detail": {
            "solvency_beneficial_portfolios": sorted(solvency_portfolios),
            "peg_beneficial_portfolios": sorted(
                peg_beneficial_portfolios
            ),
            "peg_adverse_portfolios": sorted(peg_adverse_portfolios),
            "common_improvement_portfolios": sorted(
                common_improvement_portfolios
            ),
            "portfolio_results": peg_detail,
        },
        "maximum_cell_failure_share": float(numerical_failures.max()),
        "validity_audit": {
            "crn_valid": crn_valid,
            "nested_family_draws_valid": nested_valid,
            "price_path_order_invariant": path_order_valid,
            "portfolio_state_reused_across_shocks": state_reuse_valid,
            "accounting_failure_count": int(
                (~cells["accounting_valid"].astype(bool)).sum()
            ),
            "price_isolation_failure_count": int(
                (~cells["price_isolation_valid"].astype(bool)).sum()
            ),
            "numerical_failure_count": int(
                (~cells["numerical_valid"].astype(bool)).sum()
            ),
        },
        "experiment_valid": localisation_valid,
    }


def build_evidence_payloads(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    cells, collateral = load_results(programme_identity)
    cell_evidence = cell_summary(cells)
    collateral_evidence = collateral_summary(collateral)
    contrasts = paired_contrasts(cells)
    decision_core = classify_results(cells, collateral, contrasts)
    decision = {
        "schema_version": 1,
        "experiment_identity": experiment_identity(programme_identity),
        **decision_core,
        "main_limitations": [
            "STABLE is a counterfactual stable proxy, not empirical Maker USDC vaults.",
            "Oracle delay is a transparent zero-delay baseline pending a separate freeze.",
            "Idiosyncratic evidence does not establish correlated-stress resilience.",
            (
                "The canonical close-factor-one liquidation owner can record "
                "terminal debt as keeper-repaid, making realised bad debt "
                "structurally zero; no post-result correction or retuning "
                "was applied."
            ),
        ],
        "portfolio_ranked": False,
        "portfolio_selected": None,
        "shock_ranked": False,
        "shock_selected": None,
        "next_authorised_pass": (
            "B_correlated_stress"
            if decision_core["experiment_valid"]
            else None
        ),
        "runtime_adopted": False,
    }
    checkpoint = audit_checkpoints(programme_identity)
    output_dir = _output_dir(programme_identity)
    other_final_output_directories = sorted(
        _relative(path)
        for path in OUTPUT_ROOT.parent.iterdir()
        if path.is_dir() and path != OUTPUT_ROOT
    ) if OUTPUT_ROOT.parent.is_dir() else []
    reproducibility = {
        "schema_version": 1,
        "experiment_identity": experiment_identity(programme_identity),
        "programme_identity": programme_identity,
        "scientific_code_identity": (
            REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "post_execution_operational_code_identity": (
            scientific_code_identity()
        ),
        "post_execution_maintenance": {
            "classification": SERIALIZATION_REPAIR_CLASSIFICATION,
            "maintenance_parent": STARTING_CODE_PARENT,
            "simulation_calculations_changed": False,
            "aggregation_changed": False,
            "decision_rules_changed": False,
            "registered_identity_preserved": True,
            "normalisation_owner": "dai_sim.common.serialization",
        },
        "seed_registry_sha256": seed_registry_checksum(),
        "crn_audit": {
            "replication_count": REPLICATIONS,
            "paired_stream_failures": int(
                cells.groupby("replication")["paired_stream_checksum"]
                .nunique()
                .ne(1)
                .sum()
            ),
            "nested_family_draws": True,
        },
        "checkpoint_audit": checkpoint,
        "simulation_count": len(cells),
        "result_checksums": {
            "cell_rows_csv": hashlib.sha256(_csv_bytes(cells)).hexdigest(),
            "collateral_rows_csv": hashlib.sha256(
                _csv_bytes(collateral)
            ).hexdigest(),
        },
        "detailed_output_path": _relative(output_dir),
        "detailed_output_size_bytes": sum(
            path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
        ),
        "experiments_b_to_e_executed": bool(
            other_final_output_directories
        ),
        "other_final_output_directories": other_final_output_directories,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "runtime_adopted": False,
    }
    payloads = {
        "idiosyncratic_diversification_specification.json": (
            EVIDENCE_DIR
            / "idiosyncratic_diversification_specification.json"
        ).read_bytes(),
        "idiosyncratic_diversification_registry.csv": (
            EVIDENCE_DIR / "idiosyncratic_diversification_registry.csv"
        ).read_bytes(),
        "idiosyncratic_diversification_cell_summary.csv": _csv_bytes(
            cell_evidence
        ),
        "idiosyncratic_diversification_collateral_summary.csv": _csv_bytes(
            collateral_evidence
        ),
        "idiosyncratic_diversification_contrasts.csv": _csv_bytes(contrasts),
        "idiosyncratic_diversification_decision.json": _pretty_json(
            decision
        ),
        "idiosyncratic_diversification_reproducibility.json": _pretty_json(
            reproducibility
        ),
        "idiosyncratic_diversification_benchmark.json": _pretty_json(
            dict(benchmark)
        ),
    }
    if tuple(payloads) != COMPACT_FILENAMES:
        raise ValueError("Experiment A evidence filenames differ.")
    return payloads


def _manifest_records(
    paths: Iterable[Path],
    classification: str,
) -> list[dict[str, Any]]:
    return [
        {
            "classification": classification,
            "path": _relative(path),
            "runtime_adopted": False,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]


def update_experiment_manifest(
    owned_records: Sequence[Mapping[str, Any]],
) -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    owned_paths = {str(row["path"]) for row in owned_records}
    preserved = [
        row
        for row in payload["artefacts"]
        if str(row["path"]) not in owned_paths
    ]
    combined = [*preserved, *map(dict, owned_records)]
    paths = [str(row["path"]) for row in combined]
    if len(paths) != len(set(paths)):
        raise ValueError("Experiment manifest contains duplicate paths.")
    payload["artefacts"] = sorted(combined, key=lambda row: str(row["path"]))
    payload["artefact_count"] = len(payload["artefacts"])
    _atomic_json(MANIFEST_PATH, payload)


def write_evidence(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare two isolated reconstructions before promoting compact evidence."""
    required_benchmark_fields = {
        "measurement_timestamp_utc",
        "worker_count",
        "full_wall_time_seconds",
        "completed_simulations",
        "network_calls",
        "calibration_runs",
        "experiments_b_to_e_simulations",
        "held_out_validation_runs",
    }
    missing_benchmark_fields = required_benchmark_fields - set(benchmark)
    if missing_benchmark_fields:
        raise ValueError(
            "Experiment A benchmark metadata is incomplete: "
            f"{sorted(missing_benchmark_fields)}."
        )
    if (
        int(benchmark["completed_simulations"]) != 1024
        or int(benchmark["network_calls"]) != 0
        or int(benchmark["calibration_runs"]) != 0
        or int(benchmark["experiments_b_to_e_simulations"]) != 0
        or int(benchmark["held_out_validation_runs"]) != 0
    ):
        raise ValueError("Experiment A benchmark crosses a frozen boundary.")
    first = build_evidence_payloads(programme_identity, benchmark)
    second = build_evidence_payloads(programme_identity, benchmark)
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Non-deterministic Experiment A evidence: {name}.")
    comparison_checksums: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(
        prefix="experiment-a-evidence-first-"
    ) as first_directory_name, tempfile.TemporaryDirectory(
        prefix="experiment-a-evidence-second-"
    ) as second_directory_name:
        comparison_directories = (
            Path(first_directory_name),
            Path(second_directory_name),
        )
        for directory, payloads in zip(
            comparison_directories, (first, second), strict=True
        ):
            for name, payload in payloads.items():
                _atomic_bytes(directory / name, payload)
            if {
                path.name for path in directory.iterdir() if path.is_file()
            } != set(COMPACT_FILENAMES):
                raise ValueError("Isolated evidence reconstruction is incomplete.")
        for name in DETERMINISTIC_FILENAMES:
            first_bytes = (comparison_directories[0] / name).read_bytes()
            second_bytes = (comparison_directories[1] / name).read_bytes()
            if first_bytes != second_bytes:
                raise ValueError(
                    f"Isolated evidence reconstruction differs: {name}."
                )
            comparison_checksums.append(
                {
                    "filename": name,
                    "sha256": hashlib.sha256(first_bytes).hexdigest(),
                }
            )
    pre_execution_names = set(COMPACT_FILENAMES[:2])
    for name, payload in first.items():
        path = EVIDENCE_DIR / name
        if name in pre_execution_names and path.is_file():
            if path.read_bytes() != payload:
                raise ValueError(
                    f"Pre-execution evidence would change: {name}."
                )
            continue
        _atomic_bytes(path, payload)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    update_experiment_manifest(
        _manifest_records(
            paths,
            "pre_registered_final_idiosyncratic_diversification_experiment",
        )
    )
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "artefact_count": len(paths),
        "artefact_checksums": {
            path.name: sha256_file(path) for path in paths
        },
        "deterministic_reconstruction": True,
        "isolated_comparison_directories": 2,
        "isolated_comparison_checksums": comparison_checksums,
        "pre_execution_artefacts_rewritten": False,
    }


def validate_evidence(programme_identity: str) -> dict[str, Any]:
    missing = [
        name for name in COMPACT_FILENAMES if not (EVIDENCE_DIR / name).is_file()
    ]
    if missing:
        raise ValueError(f"Missing Experiment A evidence: {missing}.")
    specification = json.loads(
        (
            EVIDENCE_DIR / "idiosyncratic_diversification_specification.json"
        ).read_text(encoding="utf-8")
    )
    decision = json.loads(
        (
            EVIDENCE_DIR / "idiosyncratic_diversification_decision.json"
        ).read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (
            EVIDENCE_DIR / "idiosyncratic_diversification_reproducibility.json"
        ).read_text(encoding="utf-8")
    )
    registry = pd.read_csv(
        EVIDENCE_DIR / "idiosyncratic_diversification_registry.csv"
    )
    cell_summary_frame = pd.read_csv(
        EVIDENCE_DIR / "idiosyncratic_diversification_cell_summary.csv"
    )
    collateral_summary_frame = pd.read_csv(
        EVIDENCE_DIR
        / "idiosyncratic_diversification_collateral_summary.csv"
    )
    contrast_frame = pd.read_csv(
        EVIDENCE_DIR / "idiosyncratic_diversification_contrasts.csv"
    )
    schemas_valid = bool(
        registry["identifier"].tolist() == list(CELL_ORDER)
        and len(registry) == 8
        and len(cell_summary_frame)
        == len(CELL_ORDER)
        * (len(SYSTEM_METRICS) + len(SYSTEM_DIAGNOSTICS))
        and {"cell_identifier", "metric", "mean", "ci95_lower", "ci95_upper"}
        <= set(cell_summary_frame)
        and len(collateral_summary_frame)
        == len(CELL_ORDER) * len(FAMILY_ORDER) * len(COLLATERAL_METRICS)
        and {"cell_identifier", "family", "metric", "mean"}
        <= set(collateral_summary_frame)
        and len(contrast_frame)
        == sum(len(pairs) for pairs in CONTRASTS.values())
        * len(SYSTEM_METRICS)
        and {
            "shock",
            "left_portfolio",
            "right_portfolio",
            "metric",
            "pair_count",
            "mean",
            "standard_error",
            "ci95_lower",
            "ci95_upper",
        }
        <= set(contrast_frame)
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    owned = [
        row
        for row in manifest["artefacts"]
        if str(row["path"]).startswith(
            "data/provenance/experiments/final/idiosyncratic_diversification/"
        )
    ]
    expected_paths = {
        _relative(EVIDENCE_DIR / name): EVIDENCE_DIR / name
        for name in COMPACT_FILENAMES
    }
    owned_by_path = {str(row["path"]): row for row in owned}
    manifest_valid = bool(
        set(owned_by_path) == set(expected_paths)
        and all(
            owned_by_path[relative_path]["sha256"] == sha256_file(path)
            and owned_by_path[relative_path]["size_bytes"]
            == path.stat().st_size
            and owned_by_path[relative_path]["classification"]
            == "pre_registered_final_idiosyncratic_diversification_experiment"
            and not owned_by_path[relative_path]["runtime_adopted"]
            for relative_path, path in expected_paths.items()
        )
    )
    evidence_valid = bool(
        specification["experiment_identity"]
        == experiment_identity(programme_identity)
        and specification["substantive_simulations"] == 1024
        and decision["A1"]
        in {"supported", "partially_supported", "not_supported", "invalid"}
        and decision["A2"]
        in {
            "exposure_gradient_consistent",
            "exposure_gradient_mixed",
            "exposure_gradient_inconsistent",
            "exposure_gradient_invalid",
        }
        and decision["A3"]
        in {"shock_localisation_valid", "shock_localisation_invalid"}
        and decision["overall_h3_classification"]
        in set(specification["decision_rules"]["overall_h3_labels"])
        and decision["peg_solvency_relationship"]
        in {
            "solvency_and_peg_improve",
            "solvency_improves_peg_unchanged",
            "peg_improves_solvency_unchanged",
            "solvency_and_peg_diverge",
            "neither_materially_changes",
            "relationship_invalid",
        }
        and not decision["portfolio_ranked"]
        and decision["portfolio_selected"] is None
        and not decision["shock_ranked"]
        and decision["shock_selected"] is None
        and not decision["runtime_adopted"]
        and reproducibility["checkpoint_audit"]["passed"]
        and reproducibility["simulation_count"] == 1024
        and reproducibility["scientific_code_identity"]
        == REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        and reproducibility["post_execution_operational_code_identity"]
        == scientific_code_identity()
        and reproducibility["post_execution_maintenance"]["classification"]
        == SERIALIZATION_REPAIR_CLASSIFICATION
        and not reproducibility["post_execution_maintenance"][
            "simulation_calculations_changed"
        ]
        and not reproducibility["post_execution_maintenance"][
            "aggregation_changed"
        ]
        and not reproducibility["post_execution_maintenance"][
            "decision_rules_changed"
        ]
        and reproducibility["post_execution_maintenance"][
            "registered_identity_preserved"
        ]
        and not reproducibility["experiments_b_to_e_executed"]
        and not reproducibility["other_final_output_directories"]
        and not reproducibility["final_validation_data_used"]
        and not reproducibility["usdc_svb_used"]
        and not reproducibility["runtime_adopted"]
        and schemas_valid
        and manifest_valid
    )
    if not evidence_valid:
        raise ValueError("Experiment A compact evidence validation failed.")
    return {
        "passed": True,
        "experiment_valid": bool(decision["experiment_valid"]),
        "experiment_identity": specification["experiment_identity"],
        "decision": decision,
        "artefact_count": len(owned),
        "artefact_checksums": {
            path.name: sha256_file(path)
            for path in (EVIDENCE_DIR / name for name in COMPACT_FILENAMES)
        },
    }
