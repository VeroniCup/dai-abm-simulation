"""Focused tests for the final idiosyncratic-diversification experiment."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from dai_sim.common.serialization import to_json_compatible
from dai_sim.experiments.final import idiosyncratic_diversification as experiment


def _sample_rows(
    family: str,
    values: list[str],
    *,
    ilk: str | None,
) -> list[dict[str, Any]]:
    return [
        {
            "family": family,
            "exact_ilk": ilk,
            "source_row_id": value,
            "family_stream_position": position,
        }
        for position, value in enumerate(values)
    ]


def _nested_state(
    portfolio: str,
    *,
    eth: list[str],
    wbtc: list[str],
    stable: list[str],
) -> experiment.NestedInitialisation:
    sampled = pd.DataFrame(
        [
            *_sample_rows("ETH", eth, ilk="ETH-A"),
            *_sample_rows("WBTC", wbtc, ilk="WBTC-A"),
            *_sample_rows("STABLE", stable, ilk=None),
        ],
        columns=(
            "family",
            "exact_ilk",
            "source_row_id",
            "family_stream_position",
        ),
    )
    return experiment.NestedInitialisation(
        portfolio=portfolio,
        replication=0,
        accepted_attempt=0,
        vaults=(),
        sampled=sampled,
        identity=f"identity-{portfolio}",
        stream_identity=f"stream-{portfolio}",
        final_system_collateral_ratio=experiment.TARGET_SYSTEM_COLLATERAL_RATIO,
        minimum_liquidation_distance=0.1,
    )


def _nested_states() -> dict[str, experiment.NestedInitialisation]:
    return {
        "eth_only": _nested_state(
            "eth_only",
            eth=["eth-0", "eth-1", "eth-2", "eth-3"],
            wbtc=[],
            stable=[],
        ),
        "empirical_crypto": _nested_state(
            "empirical_crypto",
            eth=["eth-0", "eth-1", "eth-2"],
            wbtc=["wbtc-0", "wbtc-1"],
            stable=[],
        ),
        "balanced_crypto": _nested_state(
            "balanced_crypto",
            eth=["eth-0", "eth-1"],
            wbtc=["wbtc-0", "wbtc-1", "wbtc-2"],
            stable=[],
        ),
        "stable_supported": _nested_state(
            "stable_supported",
            eth=["eth-0", "eth-1"],
            wbtc=["wbtc-0"],
            stable=["stable-0"],
        ),
    }


def _registered_kernel(multiplier: float = 0.6) -> np.ndarray:
    kernel = np.ones(experiment.REGISTERED_KERNEL_HOURS, dtype="<f8")
    kernel[experiment.REGISTERED_KERNEL_ONSET :] = np.linspace(
        multiplier,
        1.0,
        experiment.REGISTERED_KERNEL_HOURS
        - experiment.REGISTERED_KERNEL_ONSET,
    )
    return kernel


def _checkpoint_payload(replication: int) -> dict[str, Any]:
    cell_rows = [
        {
            "cell_order": order,
            "cell_identifier": cell_identifier,
            "value": float(order),
        }
        for order, cell_identifier in enumerate(
            experiment.CELL_ORDER, start=1
        )
    ]
    collateral_rows = [
        {
            "cell_order": order,
            "cell_identifier": cell_identifier,
            "family": family,
        }
        for order, cell_identifier in enumerate(
            experiment.CELL_ORDER, start=1
        )
        for family in experiment.FAMILY_ORDER
    ]
    from dai_sim.experiments.final.programme import load_programme

    programme_identity = load_programme().programme_identity
    payload = {
        "schema_version": 1,
        "experiment_id": experiment.EXPERIMENT_ID,
        "programme_identity": programme_identity,
        "experiment_identity": experiment.experiment_identity(
            programme_identity
        ),
        "replication": replication,
        "scientific_code_identity": (
            experiment.REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "profile_identity": experiment.PROFILE_IDENTITY,
        "seed_registry_sha256": experiment.seed_registry_checksum(128),
        "seed_ownership": {"replication": replication},
        "nested_initialisation_audit": {"passed": True},
        "path_audits": {
            shock: {"price_isolation_valid": True}
            for shock in experiment.SHOCK_ORDER
        },
        "paired_stream_checksum": f"paired-{replication}",
        "stream_components": {"shared": True},
        "cell_rows": cell_rows,
        "collateral_rows": collateral_rows,
        "simulation_count": 8,
    }
    payload["result_checksum"] = experiment._payload_sha256(
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
            "cell_rows": cell_rows,
            "collateral_rows": collateral_rows,
            "simulation_count": payload["simulation_count"],
        }
    )
    return payload


def _cell_frame(replications: int = 2) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for shock in experiment.SHOCK_ORDER:
        for portfolio_index, portfolio in enumerate(experiment.PORTFOLIO_ORDER):
            for replication in range(replications):
                row: dict[str, Any] = {
                    "shock": shock,
                    "portfolio": portfolio,
                    "replication": replication,
                }
                for metric in experiment.SYSTEM_METRICS:
                    if metric in experiment.BINARY_METRICS:
                        row[metric] = int(portfolio_index > 0)
                    else:
                        row[metric] = float(portfolio_index) + replication / 10
                rows.append(row)
    return pd.DataFrame(rows)


def _decision_contrasts(
    qualifying: set[str],
    *,
    peg_improves: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for portfolio in experiment.PORTFOLIO_ORDER[1:]:
        for metric in (
            "realised_bad_debt_share",
            "backlog_area_share",
            "liquidated_debt_share",
        ):
            beneficial = portfolio in qualifying and metric != (
                "liquidated_debt_share"
            )
            rows.append(
                {
                    "shock": "eth_idiosyncratic_severe",
                    "left_portfolio": portfolio,
                    "right_portfolio": "eth_only",
                    "metric": metric,
                    "ci95_lower": -0.2,
                    "ci95_upper": -0.1 if beneficial else 0.1,
                }
            )
        for metric in (
            "below_peg_burden",
            "mean_absolute_peg_deviation",
            "restricted_mean_recovery_time",
        ):
            rows.append(
                {
                    "shock": "eth_idiosyncratic_severe",
                    "left_portfolio": portfolio,
                    "right_portfolio": "eth_only",
                    "metric": metric,
                    "ci95_lower": -0.2,
                    "ci95_upper": -0.1 if peg_improves else 0.1,
                }
            )
        for metric in ("minimum_dai_price", "recovery_probability_720h"):
            rows.append(
                {
                    "shock": "eth_idiosyncratic_severe",
                    "left_portfolio": portfolio,
                    "right_portfolio": "eth_only",
                    "metric": metric,
                    "ci95_lower": 0.1 if peg_improves else -0.1,
                    "ci95_upper": 0.2,
                }
            )
    return pd.DataFrame(rows)


def _wbtc_collateral_frame(
    *,
    valid_negative_control: bool = True,
    gradient_kind: str = "consistent",
    constant_bad_debt: bool = False,
) -> pd.DataFrame:
    gradient = {
        "eth_only": 0.0,
        "stable_supported": 1.0,
        "empirical_crypto": 2.0,
        "balanced_crypto": 3.0,
    }
    non_monotone = {
        "eth_only": 0.0,
        "stable_supported": 3.0,
        "empirical_crypto": 1.0,
        "balanced_crypto": 2.0,
    }
    if gradient_kind == "consistent":
        metric_values = {
            "liquidated_debt": gradient,
            "backlog_area": {
                portfolio: value * 2 for portfolio, value in gradient.items()
            },
            "realised_bad_debt": (
                {portfolio: 0.0 for portfolio in experiment.PORTFOLIO_ORDER}
                if constant_bad_debt
                else gradient
            ),
        }
    elif gradient_kind == "mixed":
        metric_values = {
            "liquidated_debt": gradient,
            "backlog_area": non_monotone,
            "realised_bad_debt": {
                portfolio: 0.0 for portfolio in experiment.PORTFOLIO_ORDER
            },
        }
    elif gradient_kind == "inconsistent":
        metric_values = {
            "liquidated_debt": non_monotone,
            "backlog_area": {
                portfolio: value * 2
                for portfolio, value in non_monotone.items()
            },
            "realised_bad_debt": {
                portfolio: 0.0 for portfolio in experiment.PORTFOLIO_ORDER
            },
        }
    else:
        raise ValueError(f"Unknown synthetic gradient kind: {gradient_kind}.")
    rows = []
    for portfolio in experiment.PORTFOLIO_ORDER:
        for replication in range(2):
            rows.append(
                {
                    "shock": "wbtc_idiosyncratic_severe",
                    "family": "WBTC",
                    "portfolio": portfolio,
                    "replication": replication,
                    "initial_debt_exposure": gradient[portfolio],
                    "liquidated_debt": metric_values["liquidated_debt"][
                        portfolio
                    ],
                    "backlog_area": metric_values["backlog_area"][portfolio],
                    "realised_bad_debt": (
                        0.1
                        if portfolio == "eth_only" and not valid_negative_control
                        else metric_values["realised_bad_debt"][portfolio]
                    ),
                }
            )
    return pd.DataFrame(rows)


def _valid_decision_cells() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cell_identifier": identifier,
                "numerical_valid": True,
                "accounting_valid": True,
                "price_isolation_valid": True,
            }
            for identifier in experiment.CELL_ORDER
        ]
    )


def _decision_contrasts_with_peg_votes(
    qualifying: set[str],
    votes: dict[str, tuple[int, int]],
) -> pd.DataFrame:
    """Set exact beneficial/adverse vote counts across the five peg metrics."""
    frame = _decision_contrasts(qualifying, peg_improves=False)
    peg_metrics = (
        ("below_peg_burden", "lower"),
        ("mean_absolute_peg_deviation", "lower"),
        ("minimum_dai_price", "higher"),
        ("restricted_mean_recovery_time", "lower"),
        ("recovery_probability_720h", "higher"),
    )
    for portfolio in experiment.PORTFOLIO_ORDER[1:]:
        beneficial_count, adverse_count = votes.get(portfolio, (0, 0))
        if beneficial_count + adverse_count > len(peg_metrics):
            raise ValueError("Synthetic peg votes exceed five metrics.")
        for position, (metric, direction) in enumerate(peg_metrics):
            if position < beneficial_count:
                state = "beneficial"
            elif position < beneficial_count + adverse_count:
                state = "adverse"
            else:
                state = "unchanged"
            if direction == "lower":
                interval = {
                    "beneficial": (-0.2, -0.1),
                    "adverse": (0.1, 0.2),
                    "unchanged": (-0.1, 0.1),
                }[state]
            else:
                interval = {
                    "beneficial": (0.1, 0.2),
                    "adverse": (-0.2, -0.1),
                    "unchanged": (-0.1, 0.1),
                }[state]
            selected = (
                frame["shock"].eq("eth_idiosyncratic_severe")
                & frame["left_portfolio"].eq(portfolio)
                & frame["right_portfolio"].eq("eth_only")
                & frame["metric"].eq(metric)
            )
            assert int(selected.sum()) == 1
            frame.loc[selected, "ci95_lower"] = interval[0]
            frame.loc[selected, "ci95_upper"] = interval[1]
    return frame


def test_cell_registry_is_exactly_the_registered_eight_cell_order() -> None:
    cells = experiment.build_cell_registry()
    assert len(cells) == 8
    assert tuple(cell.identifier for cell in cells) == experiment.CELL_ORDER
    assert tuple(cell.order for cell in cells) == tuple(range(1, 9))
    assert tuple((cell.shock, cell.portfolio) for cell in cells) == tuple(
        (shock, portfolio)
        for shock in experiment.SHOCK_ORDER
        for portfolio in experiment.PORTFOLIO_ORDER
    )
    assert len({cell.row_checksum for cell in cells}) == 8
    assert all(cell.capacity == 26 for cell in cells)
    assert all(cell.hurdle == "direct_cost_only" for cell in cells)
    assert all(cell.confidence == "stage1_only" for cell in cells)
    assert all(cell.oracle_delay == 0 for cell in cells)


def test_seed_registry_is_deterministic_stream_specific_and_treatment_blind() -> None:
    first = experiment.seed_record(7)
    assert first == experiment.seed_record(7)
    assert first != experiment.seed_record(8)
    seeds = [first[f"{stream}_seed"] for stream in experiment.SEED_STREAMS]
    assert len(seeds) == len(set(seeds))
    assert experiment.seed_registry_checksum(3) == (
        experiment.seed_registry_checksum(3)
    )
    assert experiment.seed_registry_checksum(3) != (
        experiment.seed_registry_checksum(2)
    )
    assert experiment.derive_seed(7, "vault_ETH", "ETH-A") != (
        experiment.derive_seed(7, "vault_ETH", "ETH-B")
    )
    with pytest.raises(ValueError, match="Unknown Experiment A seed stream"):
        experiment.derive_seed(7, "treatment")
    with pytest.raises(ValueError, match="non-negative integer"):
        experiment.derive_seed(-1, "vault_ETH")


def test_nested_initialisation_audit_accepts_prefixes_and_rejects_drift() -> None:
    states = _nested_states()
    assert experiment.audit_nested_initialisations(states)["passed"] is True

    drifted = dict(states)
    drifted["balanced_crypto"] = _nested_state(
        "balanced_crypto",
        eth=["eth-0", "eth-1"],
        wbtc=["wbtc-other", "wbtc-1", "wbtc-2"],
        stable=[],
    )
    with pytest.raises(ValueError, match="Nested family draws failed"):
        experiment.audit_nested_initialisations(drifted)


def test_nested_initialiser_reuses_one_draw_set_for_every_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = _nested_states()
    empirical = {"shared": object()}
    stable = [object()]
    normalisations: list[tuple[str, int, int, int]] = []
    audit_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        experiment,
        "_design_payloads",
        lambda: ({"collateral": True}, {"portfolio": True}, pd.DataFrame()),
    )
    monkeypatch.setattr(
        experiment,
        "_draw_nested_family_streams",
        lambda **_: (empirical, stable),
    )

    def normalise(**kwargs: Any) -> experiment.NestedInitialisation:
        normalisations.append(
            (
                kwargs["portfolio"],
                id(kwargs["empirical"]),
                id(kwargs["stable"]),
                kwargs["attempt"],
            )
        )
        return states[kwargs["portfolio"]]

    def audit(
        observed: dict[str, experiment.NestedInitialisation],
    ) -> dict[str, Any]:
        audit_calls.append(tuple(observed))
        return {"passed": True}

    monkeypatch.setattr(experiment, "_normalise_nested_portfolio", normalise)
    monkeypatch.setattr(experiment, "audit_nested_initialisations", audit)

    observed = experiment.initialise_nested_portfolios(11)
    assert tuple(observed) == experiment.PORTFOLIO_ORDER
    assert tuple(item[0] for item in normalisations) == experiment.PORTFOLIO_ORDER
    assert {item[1] for item in normalisations} == {id(empirical)}
    assert {item[2] for item in normalisations} == {id(stable)}
    assert {item[3] for item in normalisations} == {0}
    assert audit_calls == [experiment.PORTFOLIO_ORDER]


def test_registered_kernel_embedding_preserves_warmup_and_hour_48_shock() -> None:
    kernel = _registered_kernel()
    embedded = experiment.embed_registered_kernel(kernel)
    assert embedded.shape == (experiment.TOTAL_HOURS,)
    assert np.array_equal(
        embedded[: experiment.PRE_SHOCK_HOURS],
        np.ones(experiment.PRE_SHOCK_HOURS),
    )
    assert embedded[experiment.PRE_SHOCK_HOURS] == pytest.approx(0.6)
    assert embedded[
        experiment.KERNEL_EMBEDDING_START :
        experiment.KERNEL_EMBEDDING_START + experiment.REGISTERED_KERNEL_HOURS
    ].tobytes() == kernel.tobytes()
    assert np.all(embedded[-24:] == kernel[-1])
    with pytest.raises(ValueError, match="must contain 216 hours"):
        experiment.embed_registered_kernel(kernel[:-1])


@pytest.mark.parametrize(
    ("shock", "kernel_family", "path_family"),
    (
        ("eth_idiosyncratic_severe", "ETH", "ETH"),
        ("wbtc_idiosyncratic_severe", "WBTC", "BTC"),
    ),
)
def test_price_paths_apply_only_the_registered_shocked_family(
    monkeypatch: pytest.MonkeyPatch,
    shock: str,
    kernel_family: str,
    path_family: str,
) -> None:
    collateral = {
        "ETH": {"initial_price_usd": 100.0},
        "WBTC": {"initial_price_usd": 200.0},
        "STABLE": {"initial_price_usd": 1.0},
    }
    ordinary = {
        "ETH": np.full(experiment.TOTAL_HOURS, 100.0),
        "BTC": np.full(experiment.TOTAL_HOURS, 200.0),
    }
    kernels = {
        family: (
            _registered_kernel()
            if family == kernel_family
            else np.ones(experiment.REGISTERED_KERNEL_HOURS)
        )
        for family in experiment.FAMILY_ORDER
    }
    monkeypatch.setattr(
        experiment,
        "_design_payloads",
        lambda: (collateral, {}, pd.DataFrame()),
    )
    monkeypatch.setattr(
        experiment.multicollateral_validation,
        "_family_payload",
        lambda payload, family: payload[family],
    )
    monkeypatch.setattr(
        experiment,
        "prices_from_log_returns",
        lambda _frame, *, initial_prices: deepcopy(ordinary),
    )
    monkeypatch.setattr(
        experiment,
        "_stable_prices",
        lambda _frame, _initial: np.ones(experiment.TOTAL_HOURS),
    )
    monkeypatch.setattr(
        experiment,
        "registered_shock_kernels",
        lambda _shock: kernels,
    )

    paths, audit = experiment.build_price_paths(pd.DataFrame(), shock)
    assert audit["price_isolation_valid"] is True
    assert paths[path_family][experiment.PRE_SHOCK_HOURS] == pytest.approx(
        ordinary[path_family][experiment.PRE_SHOCK_HOURS] * 0.6
    )
    unaffected = {"ETH", "BTC", "STABLE"} - {path_family}
    assert all(
        np.array_equal(
            paths[family],
            (
                ordinary[family]
                if family in ordinary
                else np.ones(experiment.TOTAL_HOURS)
            ),
        )
        for family in unaffected
    )


def test_price_path_builder_rejects_cross_collateral_kernel_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collateral = {
        "ETH": {"initial_price_usd": 100.0},
        "WBTC": {"initial_price_usd": 200.0},
        "STABLE": {"initial_price_usd": 1.0},
    }
    monkeypatch.setattr(
        experiment,
        "_design_payloads",
        lambda: (collateral, {}, pd.DataFrame()),
    )
    monkeypatch.setattr(
        experiment.multicollateral_validation,
        "_family_payload",
        lambda payload, family: payload[family],
    )
    monkeypatch.setattr(
        experiment,
        "prices_from_log_returns",
        lambda _frame, *, initial_prices: {
            "ETH": np.ones(experiment.TOTAL_HOURS),
            "BTC": np.ones(experiment.TOTAL_HOURS),
        },
    )
    monkeypatch.setattr(
        experiment,
        "_stable_prices",
        lambda _frame, _initial: np.ones(experiment.TOTAL_HOURS),
    )
    monkeypatch.setattr(
        experiment,
        "registered_shock_kernels",
        lambda _shock: {
            "ETH": _registered_kernel(),
            "WBTC": _registered_kernel(0.9),
            "STABLE": np.ones(experiment.REGISTERED_KERNEL_HOURS),
        },
    )
    with pytest.raises(ValueError, match="leaked across collateral prices"):
        experiment.build_price_paths(
            pd.DataFrame(), "eth_idiosyncratic_severe"
        )


def test_simulate_replication_fans_one_crn_package_across_all_eight_cells(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    states = _nested_states()
    monkeypatch.setattr(
        experiment,
        "scientific_code_identity",
        lambda: experiment.REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY,
    )
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
    streams = {
        "states": states,
        "sampled_market": pd.DataFrame({"pool_row_id": [0]}),
        "arrivals": {"uniforms": np.zeros(1), "positive_counts": np.zeros(1)},
        "stage1": {},
        "residuals": np.zeros(1),
        "seed_ownership": experiment.seed_record(0),
        "stream_components": {"shared": True},
        "paired_stream_checksum": "paired-stream",
    }
    monkeypatch.setattr(
        experiment, "_prepare_replication_streams", lambda _replication: streams
    )
    monkeypatch.setattr(
        experiment,
        "_design_payloads",
        lambda: ({"collateral": True}, {"portfolio": True}, pd.DataFrame()),
    )
    monkeypatch.setattr(
        experiment,
        "load_recovery_design",
        lambda: SimpleNamespace(
            path_definitions=(SimpleNamespace(identifier="full_week"),)
        ),
    )
    monkeypatch.setattr(experiment, "SPARSE_SCALING_EVIDENCE", scaling_path)
    monkeypatch.setattr(
        experiment,
        "build_price_paths",
        lambda _market, shock: (
            {
                family: np.ones(1)
                for family in ("ETH", "BTC", "STABLE")
            },
            {
                "shock": shock,
                "full_price_checksums": {
                    "ETH": "eth",
                    "WBTC": "wbtc",
                    "STABLE": "stable",
                },
                "price_isolation_valid": True,
            },
        ),
    )
    monkeypatch.setattr(
        experiment,
        "resolve_integrated_empirical_eth_profile",
        lambda: SimpleNamespace(gas=object()),
    )
    monkeypatch.setattr(experiment, "replace", lambda value, **_: value)
    monkeypatch.setattr(
        experiment,
        "component_gas_costs",
        lambda **_: SimpleNamespace(
            gas_cost_usd=np.ones(1),
            sampled_rows=pd.DataFrame(
                {
                    "gas_pool_row_id": ["gas-01"],
                    "gas_units": [100_000],
                    "network_gas_price_gwei": [20.0],
                }
            ),
        ),
    )
    monkeypatch.setattr(
        experiment, "_portfolio_config", lambda *_args, **_kwargs: object()
    )

    def liquidation(**_: Any) -> dict[str, Any]:
        return {
            "arrays": {"synthetic": np.zeros(1)},
            "system_summary": {
                "realised_bad_debt_share": 0.0,
                "positive_realised_bad_debt": 0,
                "active_bad_debt_share": 0.0,
                "unresolved_tab_share": 0.0,
                "backlog_area_share": 0.0,
                "liquidated_debt_share": 0.0,
                "debt_weighted_liquidated_vault_share": 0.0,
                "successful_closure_count": 0,
                "capacity_rejected_opportunities": 0,
                "accounting_valid": True,
                "numerical_valid": True,
            },
            "collateral_rows": [
                {"family": family} for family in experiment.FAMILY_ORDER
            ],
        }

    monkeypatch.setattr(experiment, "_simulate_cell_liquidations", liquidation)
    monkeypatch.setattr(
        experiment,
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

    result = experiment.simulate_replication(0)
    assert result["simulation_count"] == 8
    assert [row["cell_identifier"] for row in result["cell_rows"]] == list(
        experiment.CELL_ORDER
    )
    assert {
        row["paired_stream_checksum"] for row in result["cell_rows"]
    } == {"paired-stream"}
    assert len(result["collateral_rows"]) == 24
    assert result["nested_initialisation_audit"]["passed"] is True


def test_checkpoint_checksum_and_dimensions_are_required(tmp_path: Path) -> None:
    path = tmp_path / "replication_000.json"
    payload = _checkpoint_payload(0)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0) is True

    tampered = deepcopy(payload)
    tampered["cell_rows"][0]["value"] = 999.0
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 0) is False

    path.write_text(json.dumps(payload), encoding="utf-8")
    assert experiment._valid_checkpoint(path, 1) is False


def test_checkpoint_audit_reports_missing_and_orphan_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    for replication in (0, 1):
        (checkpoint_dir / f"replication_{replication:03d}.json").write_text(
            json.dumps(_checkpoint_payload(replication)),
            encoding="utf-8",
        )
    (checkpoint_dir / "replication_999.json").write_text(
        json.dumps(_checkpoint_payload(999)),
        encoding="utf-8",
    )
    from dai_sim.experiments.final.programme import load_programme

    programme_identity = load_programme().programme_identity
    experiment_id = experiment.experiment_identity(programme_identity)
    monkeypatch.setattr(experiment, "REPLICATIONS", 3)
    monkeypatch.setattr(experiment, "_output_dir", lambda _identity: tmp_path)
    monkeypatch.setattr(
        experiment,
        "experiment_identity",
        lambda _programme_identity: experiment_id,
    )

    incomplete = experiment.audit_checkpoints(programme_identity)
    assert incomplete == {
        "experiment_identity": experiment_id,
        "expected_checkpoints": 3,
        "observed_checkpoints": 3,
        "valid_checkpoints": 2,
        "missing_checkpoints": 1,
        "orphan_checkpoints": 1,
        "duplicate_checkpoints": 0,
        "passed": False,
    }

    (checkpoint_dir / "replication_999.json").unlink()
    (checkpoint_dir / "replication_002.json").write_text(
        json.dumps(_checkpoint_payload(2)),
        encoding="utf-8",
    )
    assert experiment.audit_checkpoints(programme_identity)["passed"] is True


def test_paired_contrasts_use_replication_pairs_and_binary_discordance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment, "REPLICATIONS", 2)
    contrasts = experiment.paired_contrasts(_cell_frame())
    expected_rows = sum(
        len(pairs) for pairs in experiment.CONTRASTS.values()
    ) * len(experiment.SYSTEM_METRICS)
    assert len(contrasts) == expected_rows

    continuous = contrasts.loc[
        contrasts["shock"].eq("eth_idiosyncratic_severe")
        & contrasts["left_portfolio"].eq("empirical_crypto")
        & contrasts["right_portfolio"].eq("eth_only")
        & contrasts["metric"].eq("backlog_area_share")
    ].iloc[0]
    assert continuous["pair_count"] == 2
    assert continuous["mean"] == pytest.approx(1.0)

    binary = contrasts.loc[
        contrasts["shock"].eq("eth_idiosyncratic_severe")
        & contrasts["left_portfolio"].eq("empirical_crypto")
        & contrasts["right_portfolio"].eq("eth_only")
        & contrasts["metric"].eq("positive_realised_bad_debt")
    ].iloc[0]
    assert binary["discordant_left_one_right_zero"] == 2
    assert binary["discordant_left_zero_right_one"] == 0


@pytest.mark.parametrize(
    ("qualifying", "expected"),
    (
        (
            {"empirical_crypto", "balanced_crypto", "stable_supported"},
            "supported",
        ),
        ({"empirical_crypto"}, "partially_supported"),
        (set(), "not_supported"),
    ),
)
def test_a1_decision_hierarchy(
    qualifying: set[str],
    expected: str,
) -> None:
    classification, detail = experiment.classify_a1(
        _decision_contrasts(qualifying),
        valid=True,
    )
    assert classification == expected
    assert len(detail) == 3
    assert experiment.classify_a1(
        _decision_contrasts(qualifying),
        valid=False,
    ) == ("invalid", {})


@pytest.mark.parametrize(
    (
        "gradient_kind",
        "expected_classification",
        "expected_informative",
        "expected_consistent",
    ),
    (
        ("consistent", "exposure_gradient_consistent", 3, 3),
        ("mixed", "exposure_gradient_mixed", 2, 1),
        ("inconsistent", "exposure_gradient_inconsistent", 2, 0),
    ),
)
def test_a2_covers_every_valid_exposure_gradient_branch(
    gradient_kind: str,
    expected_classification: str,
    expected_informative: int,
    expected_consistent: int,
) -> None:
    classification, detail = experiment.classify_a2(
        pd.DataFrame(),
        _wbtc_collateral_frame(gradient_kind=gradient_kind),
        valid=True,
    )
    assert classification == expected_classification
    assert detail["eth_only_direct_wbtc_loss_zero"] is True
    assert detail["raw_gradient_informative_metric_count"] == (
        expected_informative
    )
    assert detail["raw_gradient_consistent_metric_count"] == (
        expected_consistent
    )


def test_a2_invalid_branches_require_valid_input_and_clean_negative_control() -> None:
    assert experiment.classify_a2(
        pd.DataFrame(),
        _wbtc_collateral_frame(),
        valid=False,
    ) == ("exposure_gradient_invalid", {})

    invalid, invalid_detail = experiment.classify_a2(
        pd.DataFrame(),
        _wbtc_collateral_frame(valid_negative_control=False),
        valid=True,
    )
    assert invalid == "exposure_gradient_invalid"
    assert invalid_detail["eth_only_direct_wbtc_loss_zero"] is False


def test_constant_zero_bad_debt_is_not_an_informative_exposure_gradient() -> None:
    classification, detail = experiment.classify_a2(
        pd.DataFrame(),
        _wbtc_collateral_frame(constant_bad_debt=True),
        valid=True,
    )
    assert classification == "exposure_gradient_consistent"
    assert detail["raw_gradient_informative_metric_count"] == 2
    assert detail["raw_gradient_consistent_metric_count"] == 2
    assert detail["raw_metric_diagnostics"]["realised_bad_debt"] == {
        "informative_nonconstant": False,
        "nondecreasing_with_exposure": False,
        "range": 0.0,
    }


def test_a2_invalidates_a3_and_the_overall_h3_result() -> None:
    result = experiment.classify_results(
        _valid_decision_cells(),
        _wbtc_collateral_frame(valid_negative_control=False),
        _decision_contrasts_with_peg_votes(
            {"empirical_crypto", "balanced_crypto"},
            {"empirical_crypto": (3, 0)},
        ),
    )
    assert result["A1"] == "supported"
    assert result["A2"] == "exposure_gradient_invalid"
    assert result["A3"] == "shock_localisation_invalid"
    assert result["experiment_valid"] is False
    assert result["overall_h3_classification"] == (
        "H3_idiosyncratic_experiment_invalid"
    )
    assert result["peg_solvency_relationship"] == "relationship_invalid"


@pytest.mark.parametrize(
    (
        "qualifying",
        "gradient_kind",
        "valid_negative_control",
        "expected_h3",
    ),
    (
        (
            {"empirical_crypto", "balanced_crypto"},
            "consistent",
            True,
            "H3_idiosyncratic_diversification_supported",
        ),
        (
            set(),
            "mixed",
            True,
            "H3_idiosyncratic_diversification_partially_supported",
        ),
        (
            set(),
            "consistent",
            True,
            "H3_idiosyncratic_exposure_effect_only",
        ),
        (
            set(),
            "inconsistent",
            True,
            "H3_no_clear_idiosyncratic_diversification",
        ),
        (
            set(),
            "consistent",
            False,
            "H3_idiosyncratic_experiment_invalid",
        ),
    ),
)
def test_overall_h3_classification_hierarchy_is_exhaustive(
    qualifying: set[str],
    gradient_kind: str,
    valid_negative_control: bool,
    expected_h3: str,
) -> None:
    result = experiment.classify_results(
        _valid_decision_cells(),
        _wbtc_collateral_frame(
            gradient_kind=gradient_kind,
            valid_negative_control=valid_negative_control,
        ),
        _decision_contrasts_with_peg_votes(qualifying, {}),
    )
    assert result["overall_h3_classification"] == expected_h3


@pytest.mark.parametrize(
    (
        "qualifying",
        "peg_votes",
        "valid_negative_control",
        "expected_relationship",
    ),
    (
        (
            {"empirical_crypto"},
            {"empirical_crypto": (3, 0)},
            True,
            "solvency_and_peg_improve",
        ),
        (
            {"empirical_crypto"},
            {"empirical_crypto": (2, 0)},
            True,
            "solvency_improves_peg_unchanged",
        ),
        (
            set(),
            {"empirical_crypto": (3, 0)},
            True,
            "peg_improves_solvency_unchanged",
        ),
        (
            {"empirical_crypto"},
            {"empirical_crypto": (0, 3)},
            True,
            "solvency_and_peg_diverge",
        ),
        (
            set(),
            {"empirical_crypto": (2, 2)},
            True,
            "neither_materially_changes",
        ),
        (
            set(),
            {"empirical_crypto": (3, 0)},
            False,
            "relationship_invalid",
        ),
    ),
)
def test_all_six_peg_solvency_relationship_labels_use_five_metric_majority(
    qualifying: set[str],
    peg_votes: dict[str, tuple[int, int]],
    valid_negative_control: bool,
    expected_relationship: str,
) -> None:
    contrasts = _decision_contrasts_with_peg_votes(qualifying, peg_votes)
    result = experiment.classify_results(
        _valid_decision_cells(),
        _wbtc_collateral_frame(
            valid_negative_control=valid_negative_control
        ),
        contrasts,
    )
    assert result["peg_solvency_relationship"] == expected_relationship
    beneficial, adverse = peg_votes.get("empirical_crypto", (0, 0))
    portfolio_result = result["peg_solvency_detail"]["portfolio_results"][
        "empirical_crypto"
    ]
    assert portfolio_result["beneficial_metric_count"] == beneficial
    assert portfolio_result["adverse_metric_count"] == adverse
    assert portfolio_result["majority_beneficial"] is (beneficial >= 3)
    assert portfolio_result["majority_adverse"] is (adverse >= 3)


def test_overall_decision_covers_supported_and_invalid_branches() -> None:
    cells = _valid_decision_cells()
    contrasts = _decision_contrasts(
        {"empirical_crypto", "balanced_crypto", "stable_supported"}
    )
    supported = experiment.classify_results(
        cells,
        _wbtc_collateral_frame(),
        contrasts,
    )
    assert supported["experiment_valid"] is True
    assert supported["A1"] == "supported"
    assert supported["A2"] == "exposure_gradient_consistent"
    assert supported["A3"] == "shock_localisation_valid"
    assert supported["overall_h3_classification"] == (
        "H3_idiosyncratic_diversification_supported"
    )
    assert supported["peg_solvency_relationship"] == (
        "solvency_and_peg_improve"
    )

    invalid_cells = cells.copy()
    invalid_cells.loc[0, "numerical_valid"] = False
    invalid = experiment.classify_results(
        invalid_cells,
        _wbtc_collateral_frame(),
        contrasts,
    )
    assert invalid["experiment_valid"] is False
    assert invalid["A1"] == "invalid"
    assert invalid["A2"] == "exposure_gradient_invalid"
    assert invalid["A3"] == "shock_localisation_invalid"
    assert invalid["overall_h3_classification"] == (
        "H3_idiosyncratic_experiment_invalid"
    )


def test_json_boundary_normalises_numpy_scalars_and_arrays_recursively() -> None:
    original = {
        "integer": np.int64(2),
        "floating": np.float64(1.25),
        "boolean": np.bool_(True),
        "array": np.array([np.int64(3), np.int64(4)]),
        "nested": ({"value": np.float64(2.5)}, [np.bool_(False)]),
        "native": {"text": "unchanged", "none": None, "integer": 7},
    }
    normalised = to_json_compatible(original)
    assert normalised == {
        "integer": 2,
        "floating": 1.25,
        "boolean": True,
        "array": [3, 4],
        "nested": [{"value": 2.5}, [False]],
        "native": {"text": "unchanged", "none": None, "integer": 7},
    }
    assert type(normalised["integer"]) is int
    assert type(normalised["floating"]) is float
    assert type(normalised["boolean"]) is bool


def test_json_boundary_preserves_deterministic_key_order_and_rejects_objects() -> None:
    left = {"z": np.int64(1), "a": {"b": np.bool_(True)}}
    right = {"a": {"b": np.bool_(True)}, "z": np.int64(1)}
    assert json.dumps(
        to_json_compatible(left), sort_keys=True, separators=(",", ":")
    ) == json.dumps(
        to_json_compatible(right), sort_keys=True, separators=(",", ":")
    )
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps(to_json_compatible(object()))


def test_exact_failing_a1_payload_changes_representation_not_value() -> None:
    payload = {
        "A1_detail": {
            "empirical_crypto": {
                "beneficial_interval_count": np.int64(0)
            },
            "balanced_crypto": {
                "beneficial_interval_count": np.int64(2)
            },
            "stable_supported": {
                "beneficial_interval_count": np.int64(2)
            },
        }
    }
    normalised = to_json_compatible(payload)
    assert [
        normalised["A1_detail"][portfolio]["beneficial_interval_count"]
        for portfolio in (
            "empirical_crypto",
            "balanced_crypto",
            "stable_supported",
        )
    ] == [0, 2, 2]
    assert all(
        type(
            normalised["A1_detail"][portfolio][
                "beneficial_interval_count"
            ]
        )
        is int
        for portfolio in normalised["A1_detail"]
    )


def test_json_normalisation_does_not_change_csv_evidence() -> None:
    frame = pd.DataFrame(
        {"cell": ["a", "b"], "value": [np.float64(1.25), np.float64(2.5)]}
    )
    before = experiment._csv_bytes(frame)
    to_json_compatible(frame.to_dict(orient="records"))
    assert experiment._csv_bytes(frame) == before


def test_post_execution_repair_preserves_identity_and_blocks_simulation() -> None:
    from dai_sim.experiments.final.programme import load_programme

    assert experiment.experiment_identity(
        load_programme().programme_identity
    ) == experiment.REGISTERED_EXPERIMENT_IDENTITY
    assert experiment.scientific_code_identity() != (
        experiment.REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
    )
    with pytest.raises(RuntimeError, match="execution is frozen"):
        experiment.simulate_replication(0)


def test_public_evidence_writer_normalises_a1_and_compares_isolated_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from dai_sim.experiments.final.programme import load_programme

    programme_identity = load_programme().programme_identity
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    specification_bytes = b'{\"registered\": true}\\n'
    registry_bytes = b"identifier\\nregistered\\n"
    (evidence_dir / experiment.COMPACT_FILENAMES[0]).write_bytes(
        specification_bytes
    )
    (evidence_dir / experiment.COMPACT_FILENAMES[1]).write_bytes(
        registry_bytes
    )
    cells = pd.DataFrame(
        {"replication": [0], "paired_stream_checksum": ["paired"]}
    )
    collateral = pd.DataFrame({"family": ["ETH"]})
    summary = pd.DataFrame({"metric": ["example"], "mean": [1.0]})
    contrasts = pd.DataFrame({"metric": ["example"], "mean": [0.0]})
    decision = {
        "A1": "supported",
        "A1_detail": {
            "empirical_crypto": {"beneficial_interval_count": np.int64(0)},
            "balanced_crypto": {"beneficial_interval_count": np.int64(2)},
            "stable_supported": {"beneficial_interval_count": np.int64(2)},
        },
        "A2": "exposure_gradient_consistent",
        "A3": "shock_localisation_valid",
        "overall_h3_classification": (
            "H3_idiosyncratic_diversification_supported"
        ),
        "peg_solvency_relationship": "solvency_improves_peg_unchanged",
        "experiment_valid": True,
    }
    monkeypatch.setattr(experiment, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(
        experiment, "_output_dir", lambda _identity: tmp_path / "outputs"
    )
    monkeypatch.setattr(
        experiment, "OUTPUT_ROOT", tmp_path / "outputs" / "experiment"
    )
    monkeypatch.setattr(
        experiment, "_relative", lambda path: Path(path).name
    )
    monkeypatch.setattr(
        experiment, "load_results", lambda _identity: (cells, collateral)
    )
    monkeypatch.setattr(experiment, "cell_summary", lambda _frame: summary)
    monkeypatch.setattr(
        experiment, "collateral_summary", lambda _frame: summary
    )
    monkeypatch.setattr(
        experiment, "paired_contrasts", lambda _frame: contrasts
    )
    monkeypatch.setattr(
        experiment,
        "classify_results",
        lambda *_frames: decision,
    )
    monkeypatch.setattr(
        experiment,
        "audit_checkpoints",
        lambda _identity: {"passed": True},
    )
    monkeypatch.setattr(
        experiment, "update_experiment_manifest", lambda _records: None
    )
    benchmark = {
        "measurement_timestamp_utc": "2026-07-31T00:00:00+00:00",
        "worker_count": 4,
        "full_wall_time_seconds": 1.0,
        "completed_simulations": 1024,
        "network_calls": 0,
        "calibration_runs": 0,
        "experiments_b_to_e_simulations": 0,
        "held_out_validation_runs": 0,
    }
    written = experiment.write_evidence(programme_identity, benchmark)
    persisted = json.loads(
        (
            evidence_dir / "idiosyncratic_diversification_decision.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["A1_detail"]["balanced_crypto"][
        "beneficial_interval_count"
    ] == 2
    assert written["isolated_comparison_directories"] == 2
    assert written["pre_execution_artefacts_rewritten"] is False
    assert len(written["isolated_comparison_checksums"]) == len(
        experiment.DETERMINISTIC_FILENAMES
    )
    assert (
        evidence_dir / experiment.COMPACT_FILENAMES[0]
    ).read_bytes() == specification_bytes
    assert (
        evidence_dir / experiment.COMPACT_FILENAMES[1]
    ).read_bytes() == registry_bytes
