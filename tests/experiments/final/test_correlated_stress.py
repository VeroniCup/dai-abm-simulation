"""Focused tests for the final correlated-stress experiment."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from dai_sim.experiments.final import correlated_stress as experiment


@pytest.fixture(autouse=True)
def _clear_experiment_identity_cache() -> Any:
    """Keep identity tests independent while the source uses an LRU cache."""
    clear = getattr(experiment.experiment_identity, "cache_clear", None)
    if clear is not None:
        clear()
    yield
    clear = getattr(experiment.experiment_identity, "cache_clear", None)
    if clear is not None:
        clear()


def _cell_frame(replications: int = 3) -> pd.DataFrame:
    """Build a complete, valid eight-cell frame with paired variation."""
    rows: list[dict[str, Any]] = []
    for cell in experiment.build_cell_registry():
        shock_index = experiment.SHOCK_ORDER.index(cell.shock)
        portfolio_index = experiment.PORTFOLIO_ORDER.index(cell.portfolio)
        for replication in range(replications):
            row: dict[str, Any] = {
                "cell_order": cell.order,
                "cell_identifier": cell.identifier,
                "shock": cell.shock,
                "portfolio": cell.portfolio,
                "replication": replication,
                "numerical_valid": True,
                "accounting_valid": True,
                "joint_treatment_path_valid": True,
                "price_isolation_valid": True,
                "nested_initialisation_valid": True,
                "paired_stream_checksum": f"paired-{replication}",
                "gas_unit_draw_checksum": f"gas-units-{replication}",
                "gas_component_checksum": (
                    f"gas-component-{shock_index}-{replication}"
                ),
                "gas_environment_checksum": (
                    f"gas-environment-{shock_index}-{replication}"
                ),
                "gas_owner": (
                    "selected_empirical_24h_block"
                    if cell.shock == experiment.SHOCK_ORDER[0]
                    else "ordinary_common_market_blocks"
                ),
                "state_checksum": (
                    f"state-{cell.portfolio}-{replication}"
                ),
                "price_path_checksum": (
                    f"path-{cell.shock}-{replication}"
                ),
                "right_censored": bool(replication % 2),
                "finite_collateral_prices_valid": True,
                "finite_dai_price_valid": True,
                "nonnegative_backlog_valid": True,
                "nonnegative_bad_debt_valid": True,
                "nonnegative_vault_balances_valid": True,
                "unique_vault_identifiers": True,
                "shared_capacity_valid": True,
                "complete_metadata_valid": True,
            }
            for metric_index, metric in enumerate(
                experiment.SYSTEM_METRICS
            ):
                if metric in experiment.BINARY_METRICS:
                    row[metric] = int((replication + cell.order) % 2)
                    continue
                multiplier = experiment.METRIC_DIRECTIONS[metric]
                empirical_advantage = 2.0
                high_advantage = 0.5
                advantage = (
                    empirical_advantage
                    if cell.shock == experiment.SHOCK_ORDER[0]
                    else high_advantage
                )
                baseline = 10.0 + metric_index + replication * 0.1
                row[metric] = baseline
                if portfolio_index:
                    row[metric] += advantage / multiplier
            for diagnostic_index, metric in enumerate(
                experiment.SYSTEM_DIAGNOSTICS
            ):
                row[metric] = float(
                    cell.order + replication + diagnostic_index
                )
            rows.append(row)
    return pd.DataFrame(rows)


def _collateral_frame(replications: int = 3) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for cell in experiment.build_cell_registry():
        for family_index, family in enumerate(experiment.FAMILY_ORDER):
            for replication in range(replications):
                row: dict[str, Any] = {
                    "cell_order": cell.order,
                    "cell_identifier": cell.identifier,
                    "shock": cell.shock,
                    "portfolio": cell.portfolio,
                    "family": family,
                    "replication": replication,
                    "numerical_valid": True,
                    "accounting_valid": True,
                    "joint_treatment_path_valid": True,
                    "price_isolation_valid": True,
                    "nested_initialisation_valid": True,
                }
                for metric_index, metric in enumerate(
                    experiment.COLLATERAL_METRICS
                ):
                    row[metric] = float(
                        1
                        + cell.order
                        + family_index
                        + replication
                        + metric_index
                    )
                rows.append(row)
    return pd.DataFrame(rows)


def _decision_contrasts() -> pd.DataFrame:
    """Return neutral rows sufficient for every B decision function."""
    rows: list[dict[str, Any]] = []
    for portfolio in experiment.DIVERSIFIED_PORTFOLIOS:
        for metric in experiment.SYSTEM_METRICS:
            for shock in experiment.SHOCK_ORDER:
                rows.append(
                    {
                        "contrast_type": "direction_normalised_advantage",
                        "shock": shock,
                        "portfolio": portfolio,
                        "metric": metric,
                        "mean": 0.0,
                        "ci95_lower": -0.1,
                        "ci95_upper": 0.1,
                    }
                )
            rows.append(
                {
                    "contrast_type": (
                        "correlation_deterioration_interaction"
                    ),
                    "shock": "empirical_minus_high_correlation",
                    "portfolio": portfolio,
                    "metric": metric,
                    "mean": 0.0,
                    "ci95_lower": -0.1,
                    "ci95_upper": 0.1,
                }
            )
    return pd.DataFrame(rows)


def _set_contrast(
    frame: pd.DataFrame,
    *,
    contrast_type: str,
    portfolio: str,
    metric: str,
    mean: float,
    shock: str | None = None,
) -> None:
    mask = (
        frame["contrast_type"].eq(contrast_type)
        & frame["portfolio"].eq(portfolio)
        & frame["metric"].eq(metric)
    )
    if shock is not None:
        mask &= frame["shock"].eq(shock)
    assert int(mask.sum()) == 1
    frame.loc[mask, "mean"] = mean
    frame.loc[mask, "ci95_lower"] = (
        mean - abs(mean) * 0.1 if mean else -0.1
    )
    frame.loc[mask, "ci95_upper"] = (
        mean + abs(mean) * 0.1 if mean else 0.1
    )


def _operational(
    metrics: tuple[str, ...] = experiment.SYSTEM_METRICS,
) -> dict[str, str]:
    return {metric: "operational" for metric in metrics}


def _b3_frames(
    *,
    conditions: int,
    capacity_operational: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct B3 inputs with the requested conditions per portfolio."""
    cells: list[dict[str, Any]] = []
    collateral: list[dict[str, Any]] = []
    for shock in experiment.SHOCK_ORDER:
        for portfolio in experiment.DIVERSIFIED_PORTFOLIOS:
            for replication in range(2):
                cells.append(
                    {
                        "shock": shock,
                        "portfolio": portfolio,
                        "replication": replication,
                        "binding_hours": int(capacity_operational),
                        "share_hours_eth_wbtc_simultaneously_unsafe": (
                            0.2
                            + (
                                0.2
                                if conditions >= 4
                                and shock == experiment.SHOCK_ORDER[1]
                                else 0.0
                            )
                        ),
                    }
                )
            for family in experiment.FAMILY_ORDER:
                collateral.append(
                    {
                        "shock": shock,
                        "portfolio": portfolio,
                        "family": family,
                        "unsafe_vault_count": (
                            1.0
                            if conditions >= 1
                            and family in {"ETH", "WBTC"}
                            else 0.0
                        ),
                        "liquidated_debt": 0.0,
                        "backlog_area": (
                            1.0
                            if conditions >= 2
                            and family in {"ETH", "WBTC"}
                            else 0.0
                        ),
                        "displaced_candidates": (
                            1.0
                            if conditions >= 3 and family == "ETH"
                            else 0.0
                        ),
                    }
                )
    return pd.DataFrame(cells), pd.DataFrame(collateral)


def _group_state(
    frame: pd.DataFrame,
    metrics: tuple[str, ...],
    state: str,
) -> None:
    candidates = [
        (portfolio, metric)
        for portfolio in experiment.DIVERSIFIED_PORTFOLIOS
        for metric in metrics
    ]
    if state in {"deteriorates", "mixed"}:
        for portfolio, metric in candidates[:2]:
            threshold = experiment.MATERIALITY_THRESHOLDS[metric]
            _set_contrast(
                frame,
                contrast_type="correlation_deterioration_interaction",
                portfolio=portfolio,
                metric=metric,
                mean=max(1.0, threshold * 2.0),
            )
    if state in {"improves", "mixed"}:
        for portfolio, metric in candidates[2:4]:
            threshold = experiment.MATERIALITY_THRESHOLDS[metric]
            _set_contrast(
                frame,
                contrast_type="correlation_deterioration_interaction",
                portfolio=portfolio,
                metric=metric,
                mean=-max(1.0, threshold * 2.0),
            )


def _checkpoint_payload(
    replication: int,
    *,
    programme_identity: str = "programme",
    experiment_identity: str = "experiment",
    scientific_identity: str = "scientific",
    seed_identity: str = "seeds",
) -> dict[str, Any]:
    components = {
        "initialisation_accepted_attempt": 1,
        "initialisation_family_seeds": {
            family: index + 10
            for index, family in enumerate(experiment.FAMILY_ORDER)
        },
    }
    paired_checksum = experiment._payload_sha256(components)
    cells = [
        {
            "cell_identifier": identifier,
            "replication": replication,
            "portfolio": identifier.rsplit("__", 1)[1],
            "shock": identifier.rsplit("__", 1)[0],
            "paired_stream_checksum": paired_checksum,
            "gas_unit_draw_checksum": f"gas-{replication}",
            "gas_component_checksum": (
                f"component-{identifier.rsplit('__', 1)[0]}-{replication}"
            ),
            "gas_environment_checksum": (
                f"environment-{identifier.rsplit('__', 1)[0]}-{replication}"
            ),
            "gas_owner": (
                "selected_empirical_24h_block"
                if identifier.startswith("joint_crypto_empirical_stress__")
                else "ordinary_common_market_blocks"
            ),
            "state_checksum": (
                f"state-{identifier.rsplit('__', 1)[1]}-{replication}"
            ),
            "price_path_checksum": (
                f"path-{identifier.rsplit('__', 1)[0]}-{replication}"
            ),
            "numerical_valid": True,
            "accounting_valid": True,
            "joint_treatment_path_valid": True,
            "price_isolation_valid": True,
            "nested_initialisation_valid": True,
            "finite_collateral_prices_valid": True,
            "finite_dai_price_valid": True,
            "nonnegative_backlog_valid": True,
            "nonnegative_bad_debt_valid": True,
            "nonnegative_vault_balances_valid": True,
            "unique_vault_identifiers": True,
            "shared_capacity_valid": True,
            "complete_metadata_valid": True,
        }
        for identifier in experiment.CELL_ORDER
    ]
    collateral = [
        {
            "cell_identifier": identifier,
            "family": family,
            "replication": replication,
        }
        for identifier in experiment.CELL_ORDER
        for family in experiment.FAMILY_ORDER
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": experiment.EXPERIMENT_ID,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity,
        "replication": replication,
        "scientific_code_identity": scientific_identity,
        "profile_identity": experiment.PROFILE_IDENTITY,
        "seed_registry_sha256": seed_identity,
        "seed_ownership": experiment.seed_record(replication),
        "actual_initialisation_seed_ownership": {
            "accepted_attempt": 1,
            "family_seeds": components["initialisation_family_seeds"],
            "checksum": experiment._payload_sha256(
                {
                    "accepted_attempt": 1,
                    "family_seeds": components[
                        "initialisation_family_seeds"
                    ],
                }
            ),
        },
        "paired_stream_checksum": paired_checksum,
        "stream_components": components,
        "nested_initialisation_audit": {"passed": True},
        "path_audits": {
            shock: {
                "joint_treatment_path_valid": True,
                "registered_joint_treatment_definition_valid": True,
                "resolved_path_diagnostics": True,
                "final_validation_data_used": False,
            }
            for shock in experiment.SHOCK_ORDER
        },
        "gas_unit_draw_checksum": f"gas-{replication}",
        "gas_component_checksums": {
            shock: f"component-{shock}-{replication}"
            for shock in experiment.SHOCK_ORDER
        },
        "cell_rows": cells,
        "collateral_rows": collateral,
        "simulation_count": len(experiment.CELL_ORDER),
    }
    payload["result_checksum"] = experiment._result_checksum(payload)
    return payload


def test_registry_matches_the_frozen_master_programme() -> None:
    cells = experiment.build_cell_registry()
    assert tuple(cell.identifier for cell in cells) == experiment.CELL_ORDER
    assert tuple(cell.master_row_checksum for cell in cells) == (
        experiment.EXPECTED_MASTER_CELL_CHECKSUMS
    )
    assert {cell.capacity for cell in cells} == {26}
    assert {cell.hurdle for cell in cells} == {"direct_cost_only"}
    assert {cell.confidence for cell in cells} == {"stage1_only"}
    assert {cell.oracle_delay for cell in cells} == {0}
    assert {cell.replication_count for cell in cells} == {128}


def test_seed_registry_is_deterministic_disjoint_and_treatment_blind() -> None:
    records = [experiment.seed_record(index) for index in range(4)]
    assert records == [experiment.seed_record(index) for index in range(4)]
    assert [row["replication"] for row in records] == list(range(4))
    assert [
        row["initialisation_replication_key"] for row in records
    ] == [1_000_000 + index for index in range(4)]
    values = [
        value
        for row in records
        for value in (
            row["initialisation_master_seed"],
            *(
                row[f"{stream}_seed"]
                for stream in experiment.SEED_STREAMS
                if stream != "initialisation_master"
            ),
        )
    ]
    assert len(values) == len(set(values))
    assert all(
        "accepted_attempt" in row["initialisation_family_seed_rule"]
        for row in records
    )
    assert experiment.seed_registry_checksum(4) == (
        experiment.seed_registry_checksum(4)
    )


def test_seed_and_initialisation_keys_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="Unknown Experiment B seed"):
        experiment.derive_seed(0, "shock_specific_seed")
    with pytest.raises(ValueError, match="non-negative"):
        experiment.derive_seed(-1, "market_gas_blocks")
    with pytest.raises(ValueError, match=r"outside \[0, 127\]"):
        experiment.initialisation_replication_key(128)


def test_registered_joint_shock_kernels_are_exact_and_stable_is_ordinary() -> None:
    registry = experiment._registered_shock_frame()
    for shock in experiment.SHOCK_ORDER:
        kernels = experiment.registered_shock_kernels(shock)
        assert tuple(kernels) == experiment.FAMILY_ORDER
        for family, kernel in kernels.items():
            assert kernel.shape == (experiment.REGISTERED_KERNEL_HOURS,)
            row = registry.loc[
                registry["shock_identifier"].eq(shock)
                & registry["family"].eq(family)
            ].iloc[0]
            assert experiment.hashlib.sha256(
                np.asarray(kernel, dtype="<f8").tobytes()
            ).hexdigest() == row["path_checksum"]
        assert np.array_equal(
            kernels["STABLE"],
            np.ones(experiment.REGISTERED_KERNEL_HOURS, dtype="<f8"),
        )


def test_treatment_paths_preserve_frozen_gas_ownership() -> None:
    pool = experiment._market_pool()
    profile = experiment.resolve_multicollateral_inputs("eth_only").profile
    block_length = int(
        profile.raw["market_process"]["block_length_hours"]
    )
    starts = experiment.multicollateral_validation._valid_market_block_starts(
        pool, block_length
    )
    sampled = pd.concat(
        [
            pool.iloc[
                int(starts[index % len(starts)]) : (
                    int(starts[index % len(starts)]) + block_length
                )
            ].copy()
            for index in range(
                int(np.ceil(experiment.TOTAL_HOURS / block_length))
            )
        ],
        ignore_index=True,
    ).iloc[: experiment.TOTAL_HOURS].copy()
    sampled.insert(
        0,
        "simulation_step",
        np.arange(experiment.TOTAL_HOURS, dtype=int),
    )
    source = experiment._empirical_source_block()
    empirical_paths, empirical_gas, empirical_audit = (
        experiment.build_treatment_paths(
            sampled, "joint_crypto_empirical_stress"
        )
    )
    high_paths, high_gas, high_audit = experiment.build_treatment_paths(
        sampled, "joint_crypto_high_correlation"
    )
    start = experiment.EMPIRICAL_GAS_EMBED_START
    stop = start + experiment.EMPIRICAL_BLOCK_HOURS
    pd.testing.assert_frame_equal(
        empirical_gas.iloc[start:stop][
            list(experiment.EMPIRICAL_GAS_COLUMNS)
        ].reset_index(drop=True),
        source[list(experiment.EMPIRICAL_GAS_COLUMNS)].reset_index(
            drop=True
        ),
        check_dtype=False,
    )
    pd.testing.assert_frame_equal(high_gas, sampled)
    pd.testing.assert_frame_equal(
        empirical_gas.drop(empirical_gas.index[start:stop]).reset_index(
            drop=True
        ),
        sampled.drop(sampled.index[start:stop]).reset_index(drop=True),
    )
    assert empirical_audit["gas_owner"] == "selected_empirical_24h_block"
    assert high_audit["gas_owner"] == "ordinary_common_market_blocks"
    assert empirical_audit["stable_ordinary_multiplier_valid"] is True
    assert high_audit["stable_ordinary_multiplier_valid"] is True
    assert set(empirical_paths) == {"ETH", "BTC", "STABLE"}
    assert set(high_paths) == {"ETH", "BTC", "STABLE"}
    empirical_multipliers = experiment._embedded_multipliers(
        "joint_crypto_empirical_stress"
    )
    high_multipliers = experiment._embedded_multipliers(
        "joint_crypto_high_correlation"
    )
    for runtime_family, registry_family in (
        ("ETH", "ETH"),
        ("BTC", "WBTC"),
        ("STABLE", "STABLE"),
    ):
        np.testing.assert_allclose(
            empirical_paths[runtime_family]
            / empirical_multipliers[registry_family],
            high_paths[runtime_family] / high_multipliers[registry_family],
            rtol=5e-16,
            atol=0.0,
        )
    assert (
        experiment.empirical_source_block_checksum()
        == experiment.EMPIRICAL_SOURCE_BLOCK_SHA256
    )
    assert empirical_audit[
        "registered_joint_treatment_definition_valid"
    ] is True
    assert high_audit[
        "registered_joint_treatment_definition_valid"
    ] is True
    assert empirical_audit["resolved_path_diagnostics"] is True
    assert high_audit["resolved_path_diagnostics"] is True
    reverse = {
        shock: experiment.build_treatment_paths(sampled, shock)[2][
            "path_checksum"
        ]
        for shock in reversed(experiment.SHOCK_ORDER)
    }
    assert reverse == {
        experiment.SHOCK_ORDER[0]: empirical_audit["path_checksum"],
        experiment.SHOCK_ORDER[1]: high_audit["path_checksum"],
    }
    held_out = sampled.copy()
    held_out.loc[held_out.index[0], "is_calibration"] = False
    _, _, held_out_audit = experiment.build_treatment_paths(
        held_out, "joint_crypto_high_correlation"
    )
    assert held_out_audit["final_validation_data_used"] is True


def test_simulation_fans_one_crn_package_over_all_eight_cells(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    states = {
        portfolio: SimpleNamespace(identity=f"state-{portfolio}")
        for portfolio in experiment.PORTFOLIO_ORDER
    }
    streams = {
        "states": states,
        "sampled_market": pd.DataFrame({"pool_row_id": ["row"]}),
        "arrivals": {"uniforms": np.zeros(1), "positive_counts": np.zeros(1)},
        "stage1": {},
        "residuals": np.zeros(1),
        "seed_ownership": {"replication": 0},
        "actual_initialisation_seed_ownership": {
            "accepted_attempt": 0,
            "family_seeds": {},
            "checksum": "initialisation",
        },
        "stream_components": {"common": True},
        "paired_stream_checksum": "paired",
    }
    scaling_path = tmp_path / "scaling.json"
    scaling_path.write_text(
        json.dumps(
            {
                "lagged_below_peg_gap": {"positive_q95": 1.0},
                "lagged_24h_eth_downside": {"positive_q95": 1.0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        experiment, "_prepare_replication_streams", lambda _rep: streams
    )
    monkeypatch.setattr(
        experiment.experiment_a,
        "audit_nested_initialisations",
        lambda _states: {"passed": True},
    )
    monkeypatch.setattr(
        experiment.experiment_a,
        "_design_payloads",
        lambda: ({}, {}, pd.DataFrame()),
    )
    monkeypatch.setattr(
        experiment.experiment_a,
        "load_recovery_design",
        lambda: SimpleNamespace(
            path_definitions=(SimpleNamespace(identifier="full_week"),)
        ),
    )
    monkeypatch.setattr(
        experiment.experiment_a, "SPARSE_SCALING_EVIDENCE", scaling_path
    )

    def paths(
        _market: pd.DataFrame, shock: str
    ) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, Any]]:
        shock_index = experiment.SHOCK_ORDER.index(shock)
        return (
            {
                "ETH": np.ones(1),
                "BTC": np.ones(1),
                "STABLE": np.ones(1),
            },
            pd.DataFrame({"gas": [10.0 + shock_index]}),
            {
                "price_isolation_valid": True,
                "stable_ordinary_multiplier_valid": True,
                "full_price_checksums": {
                    "ETH": f"eth-{shock_index}",
                    "WBTC": f"wbtc-{shock_index}",
                    "STABLE": "stable",
                },
                "gas_environment_checksum": f"environment-{shock_index}",
                "gas_owner": f"owner-{shock_index}",
                "registered_joint_treatment_definition_valid": True,
                "resolved_path_diagnostics": True,
                "final_validation_data_used": False,
            },
        )

    monkeypatch.setattr(experiment, "build_treatment_paths", paths)
    monkeypatch.setattr(
        experiment,
        "resolve_integrated_empirical_eth_profile",
        lambda: SimpleNamespace(gas=object()),
    )
    monkeypatch.setattr(experiment, "replace", lambda value, **_: value)

    def gas_costs(**kwargs: Any) -> SimpleNamespace:
        gas_price = float(
            kwargs["sampled_market_gas_rows"]["gas"].iloc[0]
        )
        return SimpleNamespace(
            gas_cost_usd=np.ones(1),
            sampled_rows=pd.DataFrame(
                {
                    "gas_pool_row_id": ["gas-row"],
                    "gas_units": [100_000],
                    "network_gas_price_gwei": [gas_price],
                    "runtime_eth_price_usd": [1.0],
                    "component_transaction_gas_cost_usd": [gas_price],
                }
            ),
        )

    monkeypatch.setattr(experiment, "component_gas_costs", gas_costs)
    monkeypatch.setattr(
        experiment.experiment_a, "_portfolio_config", lambda *_: object()
    )
    monkeypatch.setattr(
        experiment,
        "_simulate_cell_liquidations",
        lambda **_: {
            "arrays": {"example": np.zeros(1)},
                "system_summary": {
                    "accounting_valid": True,
                    "numerical_valid": True,
                    "nonnegative_backlog_valid": True,
                    "nonnegative_bad_debt_valid": True,
                    "nonnegative_vault_balances_valid": True,
                    "unique_vault_identifiers": True,
                    "shared_capacity_valid": True,
                },
            "collateral_rows": [
                {"family": family}
                for family in experiment.FAMILY_ORDER
            ],
        },
    )
    monkeypatch.setattr(
        experiment.experiment_a,
        "_simulate_market_scenario",
        lambda **_: {
            "summary": {
                "below_peg_burden": 0.0,
                "mean_absolute_peg_deviation": 0.0,
                "minimum_dai_price": 1.0,
                "restricted_mean_recovery_time": 0.0,
                "recovery_probability_720h": 1,
                "right_censored": False,
                "numerical_valid": True,
            }
        },
    )
    monkeypatch.setattr(
        experiment, "experiment_identity", lambda _identity: "experiment"
    )
    monkeypatch.setattr(
        experiment, "simulation_core_identity", lambda: "simulation-core"
    )
    monkeypatch.setattr(
        experiment,
        "REGISTERED_SIMULATION_CORE_IDENTITY",
        "simulation-core",
    )
    monkeypatch.setattr(
        experiment, "seed_registry_checksum", lambda: "seeds"
    )
    result = experiment.simulate_replication(
        0, experiment.MASTER_PROGRAMME_IDENTITY
    )
    cells = pd.DataFrame(result["cell_rows"])
    assert result["simulation_count"] == 8
    assert len(result["collateral_rows"]) == 24
    assert cells["paired_stream_checksum"].nunique() == 1
    assert cells["gas_unit_draw_checksum"].nunique() == 1
    assert cells.groupby("shock")["gas_component_checksum"].first().nunique() == 2
    assert (
        cells.groupby("portfolio")["state_checksum"].nunique().eq(1).all()
    )


def test_evidence_ordering_maintenance_preserves_guarded_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment.simulation_core_identity.cache_clear()
    assert (
        experiment.simulation_core_identity()
        == experiment.REGISTERED_SIMULATION_CORE_IDENTITY
    )
    monkeypatch.setattr(
        experiment, "simulation_core_identity", lambda: "changed-core"
    )
    monkeypatch.setattr(
        experiment,
        "REGISTERED_SIMULATION_CORE_IDENTITY",
        "registered-core",
    )
    with pytest.raises(RuntimeError, match="simulation-core identity differs"):
        experiment.simulate_replication(
            0, experiment.MASTER_PROGRAMME_IDENTITY
        )


def test_compact_liquidation_accounting_and_simultaneous_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeVault:
        def __init__(self, vault_id: int, collateral_type: str) -> None:
            self.vault_id = vault_id
            self.collateral_type = collateral_type
            self.debt_dai = 10.0
            self.collateral_amount = 10.0
            self.is_active = True

        def is_liquidatable(self, prices: dict[str, float]) -> bool:
            return prices[self.collateral_type] < 1.0

        def bad_debt(self, _prices: dict[str, float]) -> float:
            return 0.0

    initialisation = SimpleNamespace(
        vaults=(
            FakeVault(0, "ETH"),
            FakeVault(1, "BTC"),
            FakeVault(2, "STABLE"),
        )
    )
    monkeypatch.setattr(experiment, "TOTAL_HOURS", 3)
    monkeypatch.setattr(experiment, "PRE_SHOCK_HOURS", 1)
    monkeypatch.setattr(experiment, "POST_SHOCK_HOURS", 2)
    monkeypatch.setattr(experiment, "TOTAL_DEBT_DAI", 30.0)
    monkeypatch.setattr(
        experiment,
        "resolve_integrated_empirical_eth_profile",
        lambda: SimpleNamespace(
            bundle=SimpleNamespace(
                base_bundle=SimpleNamespace(liquidation_config=object())
            )
        ),
    )
    monkeypatch.setattr(experiment, "replace", lambda value, **_: value)

    def rank(candidates: list[FakeVault], **_: Any) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "vault_id": vault.vault_id,
                    "collateral_type": vault.collateral_type,
                }
                for vault in candidates
            ],
            columns=("vault_id", "collateral_type"),
        )

    monkeypatch.setattr(experiment, "rank_liquidation_candidates", rank)
    result = experiment._simulate_cell_liquidations(
        initialisation=initialisation,
        price_paths={
            "ETH": np.array([2.0, 0.5, 0.5]),
            "BTC": np.array([2.0, 0.5, 2.0]),
            "STABLE": np.array([2.0, 2.0, 2.0]),
        },
        gas_costs=np.zeros(3),
        arrivals={
            "uniforms": np.ones(3),
            "positive_counts": np.zeros(3, dtype=int),
            "hurdle_probability": 0.0,
        },
        portfolio_config=SimpleNamespace(),
    )
    summary = result["system_summary"]
    assert result["accounting"]["passed"] is True
    assert summary["hours_one_unsafe_family"] == 1
    assert summary["hours_at_least_two_unsafe_families"] == 1
    assert summary["hours_all_applicable_volatile_families_unsafe"] == 1
    assert summary["hours_eth_wbtc_simultaneously_unsafe"] == 1
    assert summary["share_hours_eth_wbtc_simultaneously_unsafe"] == 0.5
    assert summary["maximum_simultaneous_active_backlog_families"] == 2
    collateral = {
        row["family"]: row for row in result["collateral_rows"]
    }
    assert collateral["ETH"]["simultaneous_unsafe_hours"] == 1
    assert collateral["WBTC"]["simultaneous_unsafe_hours"] == 1
    assert collateral["STABLE"]["simultaneous_unsafe_hours"] == 0
    assert collateral["ETH"]["maximum_backlog"] == 10.0


def test_demand_decision_preserves_inventory_and_capacity_accounting() -> None:
    inactive = experiment._demand_decision(
        step=0,
        inventory=5,
        uniform=0.9,
        positive_count=100,
        hurdle_probability=0.1,
    )
    active = experiment._demand_decision(
        step=1,
        inventory=40,
        uniform=0.0,
        positive_count=50,
        hurdle_probability=1.0,
    )
    assert inactive.attempt_budget == 0
    assert inactive.demand_inactive_unresolved == 5
    assert active.bounded_demand == 40
    assert active.attempt_budget == experiment.CAPACITY
    assert active.demand_truncated_by_inventory == 10
    assert active.demand_truncated_by_capacity == 14
    assert experiment._max_run([False, True, True, False, True]) == 2


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("missing", "not_operational"),
        ("empty", "invalid"),
        ("constant", "degenerate"),
        ("non_finite", "invalid"),
        ("varying", "operational"),
    ),
)
def test_metric_operationality_branches(mode: str, expected: str) -> None:
    metric = "backlog_area_share"
    if mode == "missing":
        frame = pd.DataFrame({"cell_identifier": ["cell"]})
    elif mode == "empty":
        frame = pd.DataFrame(columns=("cell_identifier", metric))
    elif mode == "constant":
        frame = pd.DataFrame(
            {"cell_identifier": ["a", "a", "b", "b"], metric: [1.0] * 4}
        )
    elif mode == "non_finite":
        frame = pd.DataFrame(
            {"cell_identifier": ["a", "a"], metric: [1.0, np.nan]}
        )
    else:
        frame = pd.DataFrame(
            {
                "cell_identifier": ["a", "a", "b", "b"],
                metric: [1.0, 2.0, 3.0, 4.0],
            }
        )
    assert experiment.classify_metric_operationality(frame, metric) == expected


def test_cell_and_collateral_summaries_have_registered_dimensions() -> None:
    cells = experiment.cell_summary(_cell_frame())
    collateral = experiment.collateral_summary(_collateral_frame())
    assert len(cells) == len(experiment.CELL_ORDER) * (
        len(experiment.SYSTEM_METRICS)
        + len(experiment.SYSTEM_DIAGNOSTICS)
    )
    assert len(collateral) == (
        len(experiment.CELL_ORDER)
        * len(experiment.FAMILY_ORDER)
        * len(experiment.COLLATERAL_METRICS)
    )
    assert set(cells["operationality"]) <= {
        "operational",
        "degenerate",
        "diagnostic",
    }


def test_contrast_schema_signs_and_uncertainty_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _cell_frame()
    monkeypatch.setattr(experiment, "REPLICATIONS", 3)
    contrasts = experiment.paired_contrasts(frame)
    assert len(contrasts) == 294
    assert contrasts["contrast_type"].value_counts().to_dict() == {
        "raw_portfolio_contrast": 168,
        "direction_normalised_advantage": 84,
        "correlation_deterioration_interaction": 42,
    }
    advantage = experiment._contrast_row(
        contrasts,
        contrast_type="direction_normalised_advantage",
        shock="joint_crypto_empirical_stress",
        portfolio="empirical_crypto",
        metric="backlog_area_share",
    )
    deterioration = experiment._contrast_row(
        contrasts,
        contrast_type="correlation_deterioration_interaction",
        portfolio="empirical_crypto",
        metric="backlog_area_share",
    )
    assert advantage["direction_multiplier"] == -1
    assert advantage["mean"] == pytest.approx(2.0)
    assert deterioration["mean"] == pytest.approx(1.5)
    assert deterioration["pair_count"] == 3
    assert {
        "standard_error",
        "ci95_lower",
        "ci95_upper",
        "median",
        "p05",
        "p25",
        "p75",
        "p90",
        "p95",
    } <= set(contrasts)
    binary = contrasts.loc[
        contrasts["metric"].eq("positive_realised_bad_debt")
    ]
    assert binary["discordant_left_one_right_zero"].notna().any()
    assert binary["discordant_left_zero_right_one"].notna().any()
    binary_advantage = experiment._contrast_row(
        contrasts,
        contrast_type="direction_normalised_advantage",
        shock="joint_crypto_empirical_stress",
        portfolio="empirical_crypto",
        metric="positive_realised_bad_debt",
    )
    assert binary_advantage["paired_probability_difference"] == pytest.approx(
        1.0 / 3.0
    )
    assert binary_advantage["discordant_left_one_right_zero"] == 1
    assert binary_advantage["discordant_left_zero_right_one"] == 2
    binary_interaction = experiment._contrast_row(
        contrasts,
        contrast_type="correlation_deterioration_interaction",
        portfolio="empirical_crypto",
        metric="positive_realised_bad_debt",
    )
    assert binary_interaction["paired_probability_difference"] == 0.0
    assert pd.isna(binary_interaction["discordant_left_one_right_zero"])
    assert (
        binary_interaction[
            "empirical_discordant_left_one_right_zero"
        ]
        == 1
    )


@pytest.mark.parametrize(
    ("valid", "operational_count", "qualifying", "expected"),
    (
        (False, 4, 3, "invalid"),
        (True, 1, 3, "not_operational"),
        (True, 4, 2, "supported"),
        (True, 4, 1, "partially_supported"),
        (True, 4, 0, "not_supported"),
    ),
)
def test_b1_classification_branches(
    valid: bool,
    operational_count: int,
    qualifying: int,
    expected: str,
) -> None:
    contrasts = _decision_contrasts()
    operationality = {
        metric: (
            "operational"
            if index < operational_count
            else "degenerate"
        )
        for index, metric in enumerate(
            experiment.PRIMARY_SOLVENCY_METRICS
        )
    }
    metrics = list(experiment.PRIMARY_SOLVENCY_METRICS)[:2]
    for portfolio in experiment.DIVERSIFIED_PORTFOLIOS[:qualifying]:
        for metric in metrics:
            _set_contrast(
                contrasts,
                contrast_type="direction_normalised_advantage",
                shock="joint_crypto_empirical_stress",
                portfolio=portfolio,
                metric=metric,
                mean=1.0,
            )
    result, _ = experiment.classify_b1(
        contrasts, operationality, valid=valid
    )
    assert result == expected


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("invalid", "invalid"),
        ("not_operational", "not_operational"),
        ("reversal", "correlation_reversal_present"),
        ("present", "correlation_deterioration_present"),
        ("partial", "correlation_deterioration_partial"),
        ("absent", "correlation_deterioration_not_present"),
    ),
)
def test_b2_classification_branches(mode: str, expected: str) -> None:
    contrasts = _decision_contrasts()
    operationality = _operational(
        experiment.PRIMARY_SOLVENCY_METRICS
    )
    valid = mode != "invalid"
    if mode == "not_operational":
        operationality = {
            metric: "degenerate"
            for metric in experiment.PRIMARY_SOLVENCY_METRICS
        }
    metrics = experiment.PRIMARY_SOLVENCY_METRICS[:2]
    if mode == "reversal":
        for portfolio in experiment.DIVERSIFIED_PORTFOLIOS[:2]:
            for metric in metrics:
                _set_contrast(
                    contrasts,
                    contrast_type="direction_normalised_advantage",
                    shock="joint_crypto_high_correlation",
                    portfolio=portfolio,
                    metric=metric,
                    mean=-1.0,
                )
    if mode in {"present", "partial"}:
        count = 2 if mode == "present" else 1
        for portfolio in experiment.DIVERSIFIED_PORTFOLIOS[:count]:
            for metric in metrics:
                _set_contrast(
                    contrasts,
                    contrast_type=(
                        "correlation_deterioration_interaction"
                    ),
                    portfolio=portfolio,
                    metric=metric,
                    mean=1.0,
                )
    result, _ = experiment.classify_b2(
        contrasts, operationality, valid=valid
    )
    assert result == expected


@pytest.mark.parametrize(
    ("valid", "capacity", "conditions", "expected"),
    (
        (False, True, 4, "transmission_invalid"),
        (True, False, 0, "transmission_not_operational"),
        (True, True, 4, "transmission_intensifies"),
        (True, True, 2, "transmission_mixed"),
        (True, True, 1, "transmission_not_present"),
    ),
)
def test_b3_classification_branches(
    valid: bool,
    capacity: bool,
    conditions: int,
    expected: str,
) -> None:
    cells, collateral = _b3_frames(
        conditions=conditions,
        capacity_operational=capacity,
    )
    result, _ = experiment.classify_b3(
        cells, collateral, valid=valid
    )
    assert result == expected


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("not_operational", "not_operational"),
        ("reversed", "reversed"),
        ("weakens", "weakens_but_remains"),
        ("persists", "persists"),
        ("neutralised", "neutralised"),
        ("mixed", "mixed"),
    ),
)
def test_persistence_classification_branches(
    mode: str, expected: str
) -> None:
    contrasts = _decision_contrasts()
    operationality = _operational(
        experiment.PRIMARY_SOLVENCY_METRICS
    )
    if mode == "not_operational":
        operationality = {
            metric: "degenerate"
            for metric in experiment.PRIMARY_SOLVENCY_METRICS
        }
    metrics = experiment.PRIMARY_SOLVENCY_METRICS[:2]
    for portfolio in experiment.DIVERSIFIED_PORTFOLIOS:
        if mode in {"reversed", "weakens", "persists", "mixed"}:
            count = 1 if mode == "mixed" else 2
            sign = -1.0 if mode == "reversed" else 1.0
            for metric in metrics[:count]:
                _set_contrast(
                    contrasts,
                    contrast_type="direction_normalised_advantage",
                    shock="joint_crypto_high_correlation",
                    portfolio=portfolio,
                    metric=metric,
                    mean=sign,
                )
        if mode == "weakens":
            for metric in metrics:
                _set_contrast(
                    contrasts,
                    contrast_type=(
                        "correlation_deterioration_interaction"
                    ),
                    portfolio=portfolio,
                    metric=metric,
                    mean=1.0,
                )
    result = experiment.classify_persistence(
        contrasts, operationality
    )
    assert {
        row["classification"] for row in result.values()
    } == {expected}


@pytest.mark.parametrize(
    ("valid", "solvency", "peg", "expected"),
    (
        (
            False,
            "unchanged",
            "unchanged",
            "relationship_invalid",
        ),
        (
            True,
            "deteriorates",
            "deteriorates",
            "solvency_and_peg_deteriorate_with_correlation",
        ),
        (
            True,
            "deteriorates",
            "unchanged",
            "solvency_deteriorates_peg_unchanged",
        ),
        (
            True,
            "unchanged",
            "deteriorates",
            "peg_deteriorates_solvency_unchanged",
        ),
        (
            True,
            "deteriorates",
            "improves",
            "solvency_and_peg_diverge",
        ),
        (
            True,
            "unchanged",
            "unchanged",
            "neither_materially_changes",
        ),
        (
            True,
            "mixed",
            "unchanged",
            "relationship_mixed",
        ),
    ),
)
def test_peg_solvency_classification_branches(
    valid: bool,
    solvency: str,
    peg: str,
    expected: str,
) -> None:
    contrasts = _decision_contrasts()
    _group_state(
        contrasts, experiment.PRIMARY_SOLVENCY_METRICS, solvency
    )
    _group_state(contrasts, experiment.PEG_METRICS, peg)
    result, _ = experiment.classify_peg_solvency(
        contrasts, _operational(), valid=valid
    )
    assert result == expected


@pytest.mark.parametrize(
    (
        "valid",
        "b1",
        "b2",
        "b3",
        "persistent_count",
        "expected",
    ),
    (
        (
            False,
            "invalid",
            "invalid",
            "transmission_invalid",
            0,
            "H3_correlated_stress_experiment_invalid",
        ),
        (
            True,
            "not_supported",
            "correlation_reversal_present",
            "transmission_mixed",
            0,
            "H3_correlation_reverses_diversification",
        ),
        (
            True,
            "supported",
            "correlation_deterioration_present",
            "transmission_intensifies",
            0,
            "H3_correlation_deterioration_supported",
        ),
        (
            True,
            "not_supported",
            "correlation_deterioration_partial",
            "transmission_not_present",
            0,
            "H3_correlation_deterioration_partially_supported",
        ),
        (
            True,
            "supported",
            "correlation_deterioration_not_present",
            "transmission_not_present",
            2,
            "H3_diversification_robust_to_high_correlation",
        ),
        (
            True,
            "not_supported",
            "correlation_deterioration_not_present",
            "transmission_not_present",
            0,
            "H3_no_clear_correlated_stress_effect",
        ),
    ),
)
def test_overall_h3_classification_branches(
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
    b1: str,
    b2: str,
    b3: str,
    persistent_count: int,
    expected: str,
) -> None:
    monkeypatch.setattr(
        experiment,
        "_validity_audit",
        lambda _cells, **_kwargs: {"experiment_valid": valid},
    )
    monkeypatch.setattr(
        experiment,
        "metric_operationality",
        lambda _cells: _operational(),
    )
    monkeypatch.setattr(
        experiment,
        "classify_b1",
        lambda *_args, **_kwargs: (b1, {}),
    )
    b2_detail = {
        "portfolios_with_at_least_one_deteriorating_metric": 0
    }
    monkeypatch.setattr(
        experiment,
        "classify_b2",
        lambda *_args, **_kwargs: (b2, b2_detail),
    )
    monkeypatch.setattr(
        experiment,
        "classify_b3",
        lambda *_args, **_kwargs: (b3, {}),
    )
    persistence = {
        portfolio: {
            "classification": (
                "persists"
                if index < persistent_count
                else "neutralised"
            )
        }
        for index, portfolio in enumerate(
            experiment.DIVERSIFIED_PORTFOLIOS
        )
    }
    monkeypatch.setattr(
        experiment,
        "classify_persistence",
        lambda *_args, **_kwargs: persistence,
    )
    monkeypatch.setattr(
        experiment,
        "classify_peg_solvency",
        lambda *_args, **_kwargs: (
            "neither_materially_changes",
            {},
        ),
    )
    result = experiment.classify_results(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    )
    assert result["overall_h3_classification"] == expected


def test_validity_audit_detects_crn_drift() -> None:
    cells = _cell_frame(2)
    assert experiment._validity_audit(cells)["experiment_valid"] is True
    drifted = cells.copy()
    mask = drifted["replication"].eq(0)
    drifted.loc[mask, "paired_stream_checksum"] = [
        f"drift-{index}" for index in range(int(mask.sum()))
    ]
    audit = experiment._validity_audit(drifted)
    assert audit["experiment_valid"] is False
    assert audit["crn_failure_count"] == 1


def test_preregistration_identity_is_result_blind_and_immutable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        experiment, "scientific_code_identity", lambda: "scientific"
    )
    monkeypatch.setattr(
        experiment,
        "experiment_identity",
        lambda _programme_identity: "registered-experiment",
    )
    monkeypatch.setattr(
        experiment,
        "_registered_path_identities",
        lambda: {"shock": {"checksum": "path"}},
    )
    monkeypatch.setattr(
        experiment,
        "_experiment_a_checkpoint_snapshot",
        lambda: {
            "checkpoint_count": 128,
            "content_map_sha256": "content",
            "mtime_map_sha256": "mtime",
            "total_bytes": 1,
        },
    )
    monkeypatch.setattr(
        experiment, "empirical_source_block_checksum", lambda: "gas"
    )
    monkeypatch.setattr(experiment, "EVIDENCE_DIR", tmp_path)
    specification = experiment.specification_payload(
        experiment.MASTER_PROGRAMME_IDENTITY
    )
    assert specification["substantive_simulations"] == 1024
    assert specification["final_validation_data_used"] is False
    assert specification["runtime_adopted"] is False
    assert specification["portfolio_selected"] is None
    assert specification["shock_selected"] is None
    assert not {
        "decision",
        "results",
        "observed_outcomes",
        "estimated_effects",
    } & set(specification)
    first = experiment.write_preregistration(
        experiment.MASTER_PROGRAMME_IDENTITY
    )
    second = experiment.write_preregistration(
        experiment.MASTER_PROGRAMME_IDENTITY
    )
    assert first == second
    path = tmp_path / experiment.COMPACT_FILENAMES[0]
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="would change"):
        experiment.write_preregistration(
            experiment.MASTER_PROGRAMME_IDENTITY
        )


def test_experiment_identity_binds_registered_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment.experiment_identity.cache_clear()
    assert (
        experiment.experiment_identity(experiment.MASTER_PROGRAMME_IDENTITY)
        == experiment.REGISTERED_EXPERIMENT_IDENTITY
    )
    monkeypatch.setattr(
        experiment,
        "_registered_path_identities",
        lambda: {"path": "changed"},
    )
    experiment.experiment_identity.cache_clear()
    with pytest.raises(
        ValueError, match="Registered Experiment B identity reconstruction"
    ):
        experiment.experiment_identity(experiment.MASTER_PROGRAMME_IDENTITY)


def test_checkpoint_validation_requires_identity_order_and_checksum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        experiment, "experiment_identity", lambda _identity: "experiment"
    )
    monkeypatch.setattr(
        experiment, "scientific_code_identity", lambda: "scientific"
    )
    monkeypatch.setattr(
        experiment,
        "REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY",
        "scientific",
    )
    monkeypatch.setattr(
        experiment, "seed_registry_checksum", lambda: "seeds"
    )
    path = tmp_path / "replication_000.json"
    payload = _checkpoint_payload(0)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0, "programme") is True
    tampered = deepcopy(payload)
    tampered["cell_rows"][0]["cell_identifier"] = "wrong"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0, "programme") is False
    tampered = deepcopy(payload)
    tampered["path_audits"][experiment.SHOCK_ORDER[0]][
        "joint_treatment_path_valid"
    ] = False
    tampered["result_checksum"] = experiment._result_checksum(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0, "programme") is False
    tampered = deepcopy(payload)
    tampered["seed_ownership"]["market_gas_blocks_seed"] += 1
    tampered["result_checksum"] = experiment._result_checksum(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0, "programme") is False
    tampered = deepcopy(payload)
    tampered["gas_component_checksums"][
        experiment.SHOCK_ORDER[0]
    ] = "wrong"
    tampered["result_checksum"] = experiment._result_checksum(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0, "programme") is False


def _configure_matrix_test(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / experiment.COMPACT_FILENAMES[0]).write_text(
        json.dumps({"experiment_identity": "experiment"}),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    monkeypatch.setattr(experiment, "EVIDENCE_DIR", evidence)
    monkeypatch.setattr(experiment, "REPLICATIONS", 1)
    monkeypatch.setattr(
        experiment, "experiment_identity", lambda _identity: "experiment"
    )
    monkeypatch.setattr(
        experiment, "_output_dir", lambda _identity: output
    )
    monkeypatch.setattr(experiment, "_worker_initialiser", lambda: None)
    monkeypatch.setattr(
        experiment, "_assert_preregistration_matches", lambda _identity: None
    )
    return output


def test_run_matrix_reuses_valid_checkpoint_without_simulation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = _configure_matrix_test(monkeypatch, tmp_path)
    checkpoint = experiment._checkpoint_path(output, 0)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        experiment, "_valid_checkpoint", lambda *_args: True
    )
    monkeypatch.setattr(
        experiment,
        "simulate_replication",
        lambda *_args: pytest.fail("A reused checkpoint was rerun."),
    )
    result = experiment.run_matrix(
        "programme", workers=1, resume=True
    )
    assert result["reused_replications"] == 1
    assert result["completed_replications"] == 0
    assert result["rerun_replications"] == 0
    assert result["complete"] is True


def test_run_matrix_refuses_invalid_or_non_resume_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = _configure_matrix_test(monkeypatch, tmp_path)
    checkpoint = experiment._checkpoint_path(output, 0)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        experiment, "_valid_checkpoint", lambda *_args: False
    )
    with pytest.raises(ValueError, match="Invalid checkpoint"):
        experiment.run_matrix("programme", workers=1, resume=True)
    monkeypatch.setattr(
        experiment, "_valid_checkpoint", lambda *_args: True
    )
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        experiment.run_matrix("programme", workers=1, resume=False)


def test_run_matrix_writes_one_synthetic_missing_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = _configure_matrix_test(monkeypatch, tmp_path)
    monkeypatch.setattr(
        experiment,
        "_valid_checkpoint",
        lambda path, *_args: Path(path).is_file(),
    )
    monkeypatch.setattr(
        experiment,
        "simulate_replication",
        lambda replication, _identity: {"replication": replication},
    )
    result = experiment.run_matrix(
        "programme", workers=1, resume=True
    )
    assert result["completed_replications"] == 1
    assert result["reused_replications"] == 0
    assert result["completed_simulations"] == len(experiment.CELL_ORDER)
    assert experiment._checkpoint_path(output, 0).is_file()


def test_evidence_writer_is_deterministic_and_enforces_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(experiment, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(
        experiment, "experiment_identity", lambda _identity: "experiment"
    )
    payloads = {
        name: f"{name}\n".encode() for name in experiment.COMPACT_FILENAMES
    }
    for name in experiment.COMPACT_FILENAMES[:2]:
        (tmp_path / name).write_bytes(payloads[name])
    monkeypatch.setattr(
        experiment,
        "build_evidence_payloads",
        lambda *_args: dict(payloads),
    )
    monkeypatch.setattr(
        experiment, "update_experiment_manifest", lambda _records: None
    )
    monkeypatch.setattr(
        experiment, "_relative", lambda path: Path(path).name
    )
    monkeypatch.setattr(
        experiment,
        "checkpoint_content_snapshot",
        lambda _identity: {
            "checkpoint_count": 128,
            "content_map_sha256": "checkpoints",
            "total_bytes": 1,
        },
    )
    benchmark = {
        "schema_version": 1,
        "measurement_timestamp_utc": "2026-07-31T00:00:00+00:00",
        "execution_command": (
            "PYTHONPATH=src python "
            "workflows/experiments/final/correlated_stress.py "
            "all --workers 1"
        ),
        "worker_count": 1,
        "smoke_wall_time_seconds": 0.1,
        "full_wall_time_seconds": 1.0,
        "throughput_simulations_per_second": 1024.0,
        "completed_replications": 128,
        "reused_replications": 0,
        "resumed_replications": 0,
        "failed_replications": 0,
        "rerun_replications": 0,
        "completed_simulations": 1024,
        "checkpoint_count": 128,
        "output_size_bytes": 1,
        "free_storage_bytes": experiment.MINIMUM_FREE_BYTES,
        "network_calls": 0,
        "calibration_runs": 0,
        "experiment_a_simulations": 0,
        "experiments_c_to_e_simulations": 0,
        "held_out_validation_runs": 0,
    }
    result = experiment.write_evidence("programme", benchmark)
    assert result["artefact_count"] == 8
    assert result["deterministic_reconstruction"] is True
    assert len(result["isolated_comparison_checksums"]) == len(
        experiment.DETERMINISTIC_FILENAMES
    )
    invalid = dict(benchmark, experiments_c_to_e_simulations=1)
    with pytest.raises(ValueError, match="frozen boundary"):
        experiment.write_evidence("programme", invalid)


def test_reproducibility_refresh_rejects_scientific_changes() -> None:
    common = {
        "experiment_identity": "frozen",
        "result_checksums": {"cell_rows_csv": "unchanged"},
    }
    previous = {
        **common,
        "post_execution_operational_code_identity": "before",
        "post_execution_maintenance": {
            "classification": (
                experiment.EVIDENCE_ORDERING_REPAIR_CLASSIFICATION
            ),
        },
    }
    replacement = {
        **common,
        "simulation_core_identity": (
            experiment.REGISTERED_SIMULATION_CORE_IDENTITY
        ),
        "registered_simulation_core_identity": (
            experiment.REGISTERED_SIMULATION_CORE_IDENTITY
        ),
        "post_execution_operational_code_identity": "after",
        "post_execution_maintenance": {
            "classification": (
                experiment.EVIDENCE_ORDERING_REPAIR_CLASSIFICATION
            ),
            "simulation_calculations_changed": False,
            "checkpoint_content_changed": False,
            "summary_values_changed": False,
            "decision_rules_changed": False,
            "registered_identity_preserved": True,
            "deterministic_replay_preserved": True,
        },
    }
    def encode(value: dict[str, Any]) -> bytes:
        return json.dumps(value, sort_keys=True).encode("utf-8")

    assert experiment._is_reproducibility_maintenance_only(
        encode(previous), encode(replacement)
    )
    changed = deepcopy(replacement)
    changed["result_checksums"]["cell_rows_csv"] = "changed"
    assert not experiment._is_reproducibility_maintenance_only(
        encode(previous), encode(changed)
    )


def test_experiment_a_regression_audit_round_trips_canonical_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = experiment._experiment_a_checkpoint_snapshot()
    result = experiment.experiment_a_regression_audit(snapshot)
    assert result["unchanged"] is True
    assert result["simulations_executed"] == 0
    assert result["checkpoint_snapshot"] == snapshot
    changed = dict(snapshot)
    changed["content_map_sha256"] = "changed"
    with pytest.raises(
        ValueError, match="checkpoint snapshot changed"
    ):
        experiment.experiment_a_regression_audit(changed)
    monkeypatch.setattr(
        experiment,
        "_experiment_a_checkpoint_snapshot",
        lambda: {
            "checkpoint_count": 0,
            "content_map_sha256": "ignored-checkpoints-absent",
            "total_bytes": 0,
        },
    )
    clean_clone = experiment.experiment_a_regression_audit(snapshot)
    assert clean_clone["checkpoint_snapshot"] == snapshot
    monkeypatch.setattr(
        experiment,
        "_experiment_a_checkpoint_snapshot",
        lambda: {
            "checkpoint_count": 1,
            "content_map_sha256": "partial",
            "total_bytes": 1,
        },
    )
    with pytest.raises(ValueError, match="checkpoint set is partial"):
        experiment.experiment_a_regression_audit(snapshot)


def test_unregistered_valid_h3_state_is_not_silently_relabelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        experiment,
        "_validity_audit",
        lambda _cells, **_kwargs: {"experiment_valid": True},
    )
    monkeypatch.setattr(
        experiment,
        "metric_operationality",
        lambda _cells: _operational(),
    )
    monkeypatch.setattr(
        experiment,
        "classify_b1",
        lambda *_args, **_kwargs: ("not_supported", {}),
    )
    monkeypatch.setattr(
        experiment,
        "classify_b2",
        lambda *_args, **_kwargs: (
            "correlation_deterioration_present",
            {"portfolios_with_at_least_one_deteriorating_metric": 0},
        ),
    )
    monkeypatch.setattr(
        experiment,
        "classify_b3",
        lambda *_args, **_kwargs: ("transmission_not_present", {}),
    )
    monkeypatch.setattr(
        experiment,
        "classify_persistence",
        lambda *_args, **_kwargs: {
            portfolio: {"classification": "neutralised"}
            for portfolio in experiment.DIVERSIFIED_PORTFOLIOS
        },
    )
    with pytest.raises(ValueError, match="outside the registered hierarchy"):
        experiment.classify_results(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )


def test_run_matrix_persists_failure_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = _configure_matrix_test(monkeypatch, tmp_path)
    calls: list[int] = []

    def fail(replication: int, _identity: str) -> dict[str, Any]:
        calls.append(replication)
        raise RuntimeError("synthetic worker failure")

    monkeypatch.setattr(
        experiment, "_valid_checkpoint", lambda *_args: False
    )
    monkeypatch.setattr(experiment, "simulate_replication", fail)
    with pytest.raises(RuntimeError, match="synthetic worker failure"):
        experiment.run_matrix("programme", workers=1, resume=True)
    assert calls == [0]
    failures = list((output / "failure_records").glob("*.json"))
    assert len(failures) == 1
    payload = json.loads(failures[0].read_text(encoding="utf-8"))
    assert payload["replication"] == 0
    assert payload["automatic_retry_attempted"] is False


def test_compact_frame_validator_requires_exact_cartesian_schemas() -> None:
    raw_cells = _cell_frame(experiment.REPLICATIONS)
    raw_collateral = _collateral_frame(experiment.REPLICATIONS).sort_values(
        ["cell_order", "family", "replication"],
        kind="mergesort",
    )
    cell_summary = experiment.cell_summary(raw_cells)
    collateral_summary = experiment.collateral_summary(raw_collateral)
    contrasts = experiment.paired_contrasts(raw_cells)
    dimensions = experiment._validate_summary_and_contrast_frames(
        experiment._registry_frame(),
        cell_summary,
        collateral_summary,
        contrasts,
    )
    assert dimensions == {
        "registry_rows": 8,
        "cell_summary_rows": 208,
        "collateral_summary_rows": 456,
        "raw_contrast_rows": 168,
        "advantage_rows": 84,
        "interaction_rows": 42,
        "contrast_rows": 294,
    }
    malformed = cell_summary.drop(columns=["p95"])
    with pytest.raises(ValueError, match="columns differ"):
        experiment._validate_summary_and_contrast_frames(
            experiment._registry_frame(),
            malformed,
            collateral_summary,
            contrasts,
        )


def test_workflow_git_boundary_rejects_wrong_parent_or_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = runpy.run_path(
        str(
            experiment.REPOSITORY_ROOT
            / "workflows/experiments/final/correlated_stress.py"
        )
    )
    boundary = workflow["_git_boundary"]
    responses = {
        ("rev-parse", "HEAD"): experiment.EXPERIMENT_B_PARENT_COMMIT + "\n",
        ("branch", "--show-current"): "feature/multi-collateral\n",
        (
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ): "origin/feature/multi-collateral\n",
        ("diff", "--cached", "--name-only"): "",
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ): "?? src/dai_sim/experiments/final/correlated_stress.py\n",
    }

    def fake_git(*arguments: str) -> SimpleNamespace:
        return SimpleNamespace(stdout=responses[arguments])

    monkeypatch.setitem(boundary.__globals__, "_git", fake_git)
    assert boundary()["index_empty"] is True
    responses[("rev-parse", "HEAD")] = "clean-descendant\n"
    responses[
        ("status", "--porcelain=v1", "--untracked-files=all")
    ] = ""
    monkeypatch.setitem(
        boundary.__globals__,
        "_is_descendant_of_parent",
        lambda _head: True,
    )
    assert boundary()["mode"] == "clean_descendant_replay"
    monkeypatch.setitem(
        boundary.__globals__,
        "_is_descendant_of_parent",
        lambda _head: False,
    )
    with pytest.raises(ValueError, match="Git boundary differs"):
        boundary()
    responses[("rev-parse", "HEAD")] = (
        experiment.EXPERIMENT_B_PARENT_COMMIT + "\n"
    )
    responses[
        ("status", "--porcelain=v1", "--untracked-files=all")
    ] = "?? src/dai_sim/experiments/final/correlated_stress.py\n"
    responses[("branch", "--show-current")] = "wrong-branch\n"
    with pytest.raises(ValueError, match="Git boundary differs"):
        boundary()
    responses[("branch", "--show-current")] = "feature/multi-collateral\n"
    responses[("diff", "--cached", "--name-only")] = "staged.py\n"
    with pytest.raises(ValueError, match="Git boundary differs"):
        boundary()
