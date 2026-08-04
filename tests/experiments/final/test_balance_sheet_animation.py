"""Focused reporting-only tests for the Experiment A balance-sheet animation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dai_sim.experiments.final import idiosyncratic_diversification as experiment
from dai_sim.experiments.mechanism import eth_recovery as market_owner
from workflows.experiments.final import build_balance_sheet_animation_frames as frames
from workflows.experiments.final import render_balance_sheet_animation as renderer
from workflows.experiments.final import render_oracle_delay_animation as oracle_renderer
from workflows.experiments.final import replay_balance_sheet_hourly as replay


def _raw_system() -> pd.DataFrame:
    rows = []
    for replication in range(2):
        for treatment in replay.AUTHORIZED_PORTFOLIOS:
            for hour in range(3):
                rows.append(
                    {
                        "replication": replication,
                        "hour": hour,
                        "shock": replay.AUTHORIZED_SHOCK,
                        "treatment": treatment,
                        "eth_price_index": [100.0, 88.0, 90.0][hour],
                        "wbtc_price_index": [100.0, 100.5, 100.2][hour],
                        "stable_price_index": [100.0, 100.0, 100.0][hour],
                        "unresolved_debt_share": (
                            0.01 * replication
                            if treatment == "eth_only" and hour == 1
                            else 0.0
                        ),
                        "cumulative_liquidated_debt_share": (
                            0.01 * replication * max(hour - 1, 0)
                            if treatment == "eth_only"
                            else 0.0
                        ),
                        "dai_price": 1.0 - 0.0001 * hour,
                    }
                )
    return pd.DataFrame(rows)


def _vault() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "hour": hour,
                "replication": 4,
                "treatment": treatment,
                "vault_id": vault_id,
                "collateral_family": family,
                "vault_debt": debt,
                "collateral_ratio": ratio,
                "liquidation_ratio": 1.5,
                "liquidation_margin": ratio / 1.5 - 1.0,
                "canonical_vault_state": state,
            }
            for treatment in replay.AUTHORIZED_PORTFOLIOS
            for hour in range(3)
            for vault_id, family, debt, ratio, state in (
                (0, "ETH", 10.0, 1.8, "safe"),
                (1, "STABLE", 5.0, 1.4, "liquidatable_unresolved"),
            )
        ]
    )


def test_replay_scope_is_exactly_the_two_registered_severe_shock_cells() -> None:
    assert replay.AUTHORIZED_SHOCK == "eth_idiosyncratic_severe"
    assert replay.AUTHORIZED_PORTFOLIOS == ("eth_only", "stable_supported")
    assert replay.AUTHORIZED_CELLS == (
        "eth_idiosyncratic_severe__eth_only",
        "eth_idiosyncratic_severe__stable_supported",
    )


def test_representative_replication_is_selected_from_frozen_scalars() -> None:
    selection = replay.select_representative_replication()

    assert selection["source"] == "frozen scalar checkpoints only"
    assert selection["candidate_count"] == 128
    assert selection["selected_replication"] == 4
    assert selection["sample_median"] == pytest.approx(0.0010407193702979697)
    assert selection["selected_contrast"] == pytest.approx(0.0010665932839555449)
    assert selection["tie_rule"] == "smallest replication identifier"


def test_passive_dai_capture_preserves_arguments_and_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Result:
        clipped_next_price = 0.9984

    def fake(*args: object, **kwargs: object) -> Result:
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(market_owner, "coefficient_normalised_market_response", fake)
    with replay._passive_dai_capture() as captured:
        result = market_owner.coefficient_normalised_market_response(7, same=True)

    assert result.clipped_next_price == 0.9984
    assert calls == [((7,), {"same": True})]
    assert captured == [0.9984]
    assert market_owner.coefficient_normalised_market_response is fake


def test_scalar_reconciliation_requires_exact_equality() -> None:
    assert replay._scalar_mismatches({"value": 1.0}, {"value": 1.0}) == []
    mismatch = replay._scalar_mismatches({"value": 1.0}, {"value": 1.001})

    assert mismatch[0]["field"] == "value"
    assert mismatch[0]["absolute_difference"] == pytest.approx(0.001)


def test_raw_system_gate_enforces_pairing_and_monotone_cumulative_debt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment, "REPLICATIONS", 2)
    monkeypatch.setattr(experiment, "TOTAL_HOURS", 3)
    raw = _raw_system()
    frames._validate_raw_system(raw)

    mismatched = raw.copy()
    mask = mismatched["treatment"].eq("stable_supported") & mismatched["hour"].eq(1)
    mismatched.loc[mask, "eth_price_index"] += 0.1
    with pytest.raises(ValueError, match="different eth_price_index paths"):
        frames._validate_raw_system(mismatched)

    decreasing = raw.copy()
    mask = decreasing["treatment"].eq("eth_only") & decreasing["replication"].eq(1)
    decreasing.loc[mask, "cumulative_liquidated_debt_share"] = [0.0, 0.02, 0.01]
    with pytest.raises(ValueError, match="negative or decreasing"):
        frames._validate_raw_system(decreasing)


def test_post_shock_cumulative_liquidation_uses_hour_before_shock_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment, "PRE_SHOCK_HOURS", 1)
    raw = _raw_system()
    raw["cumulative_liquidated_debt_share"] += 0.02

    normalised = frames._post_shock_cumulative_liquidation(raw)

    assert (
        normalised.loc[normalised["hour"].eq(0), "cumulative_liquidated_debt_share"]
        .eq(0.0)
        .all()
    )
    expected = raw.loc[raw["hour"].eq(2), "cumulative_liquidated_debt_share"] - 0.02
    actual = normalised.loc[
        normalised["hour"].eq(2), "cumulative_liquidated_debt_share"
    ]
    assert np.array_equal(actual.to_numpy(), expected.to_numpy())


def test_vault_margin_and_jitter_are_canonical_and_stable() -> None:
    prepared = frames._prepare_vault(_vault(), selected_replication=4)

    expected = prepared["collateral_ratio"] / prepared["liquidation_ratio"] - 1.0
    assert np.allclose(prepared["liquidation_margin"], expected, rtol=0.0, atol=0.0)
    assert prepared.groupby("vault_id")["x_jitter"].nunique().eq(1).all()
    assert frames.deterministic_vault_jitter(17) == frames.deterministic_vault_jitter(
        17
    )

    invalid = _vault()
    invalid.loc[0, "liquidation_margin"] += 1e-6
    with pytest.raises(ValueError, match="CR / LR - 1"):
        frames._prepare_vault(invalid, selected_replication=4)


def test_representative_vault_accounting_reconciles_debt_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment, "TOTAL_HOURS", 3)
    monkeypatch.setattr(experiment, "VAULT_COUNT", 2)
    vault = pd.DataFrame(
        [
            {"hour": 0, "canonical_vault_state": "safe", "vault_debt": 10.0},
            {"hour": 0, "canonical_vault_state": "safe", "vault_debt": 5.0},
            {"hour": 1, "canonical_vault_state": "safe", "vault_debt": 10.0},
            {
                "hour": 1,
                "canonical_vault_state": "liquidatable_unresolved",
                "vault_debt": 5.0,
            },
            {"hour": 2, "canonical_vault_state": "safe", "vault_debt": 10.0},
        ]
    )
    arrays = {
        "unresolved_tab_dai": np.array([0.0, 5.0, 0.0]),
        "successful_closures": np.array([0, 0, 1]),
    }

    result = replay._validate_vault_accounting(vault, arrays)

    assert result["passed"] is True
    assert result["maximum_unresolved_debt_absolute_difference"] == 0.0
    assert result["active_count_comparison"] == "exact"


def test_renderer_uses_fixed_covering_axes_and_preserves_shock_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment, "REPLICATIONS", 2)
    monkeypatch.setattr(experiment, "TOTAL_HOURS", 3)
    monkeypatch.setattr(experiment, "PRE_SHOCK_HOURS", 1)
    system = frames._aggregate_system(_raw_system())
    vault = frames._prepare_vault(_vault(), selected_replication=4)
    hours = renderer.validate_frame_tables(
        system, vault, {"representative_replication": 4}
    )
    limits = renderer.compute_axis_limits(system, vault)
    settings = renderer.RenderSettings(
        fps=2,
        opening_hold_seconds=1.0,
        final_hold_seconds=1.0,
        progression_frames=5,
    )
    sequence = renderer.build_frame_sequence(hours, system, settings)

    assert limits.price_index[0] <= system["eth_price_index"].min()
    assert limits.price_index[1] >= system["wbtc_price_index"].max()
    assert limits.vault_margin[0] <= vault["liquidation_margin"].min()
    assert limits.vault_margin[1] >= vault["liquidation_margin"].max()
    assert sequence[:2] == [0, 0]
    assert sequence[-2:] == [2, 2]
    assert 1 in sequence
    assert np.all(np.diff(sequence) >= 0)

    figure, update = renderer._build_figure(
        system,
        vault,
        hours,
        limits,
        settings,
        representative_replication=4,
    )
    update(len(hours) - 1)
    assert all(text.get_bbox_patch() is None for text in figure.texts)
    assert all(
        "Stable collateral reduces" not in text.get_text() for text in figure.texts
    )
    renderer.plt.close(figure)


def test_final_render_contract_is_twenty_seconds_and_four_hundred_frames() -> None:
    settings = renderer.RenderSettings()

    assert renderer.PEG_BAND == oracle_renderer.PEG_BAND
    assert settings.fps == 20
    assert settings.width == 1920
    assert settings.height == 1080
    assert settings.bitrate_kbps == 6500
    assert (
        round(settings.opening_hold_seconds * settings.fps)
        + settings.progression_frames
        + round(settings.final_hold_seconds * settings.fps)
        == 400
    )
