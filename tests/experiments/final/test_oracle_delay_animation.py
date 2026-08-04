"""Focused reporting-only tests for the Experiment E animation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workflows.experiments.final.build_oracle_delay_animation_frames import (
    ExperimentContract,
    MissingHourlyEvidenceError,
    load_hourly_evidence,
    prepare_frames,
    reconcile_registered_summaries,
)
from workflows.experiments.final.render_oracle_delay_animation import (
    RenderSettings,
    _presentation_replacement_path,
    build_frame_sequence,
    compute_axis_limits,
    validate_frame_table,
)
from workflows.experiments.final import render_oracle_delay_animation as renderer
from workflows.experiments.final.replay_oracle_delay_hourly import (
    AUTHORIZED_CELLS,
    _passive_dai_capture,
    _scalar_mismatches,
)
from dai_sim.experiments.final import oracle_delay as experiment
from dai_sim.experiments.mechanism import eth_recovery as market_owner


CONTRACT = ExperimentContract(
    replications=2,
    total_hours=5,
    pre_shock_hours=1,
    total_debt_dai=100.0,
)


def _detail() -> pd.DataFrame:
    rows = []
    market_by_replication = {
        0: [0.0, 20.0, 40.0, 10.0, 0.0],
        1: [0.0, 30.0, 50.0, 20.0, 0.0],
    }
    for replication in range(CONTRACT.replications):
        market = market_by_replication[replication]
        for delay in CONTRACT.delays:
            oracle = market if delay == 0 else [0.0] * delay + market[:-delay]
            for hour, (market_debt, oracle_debt) in enumerate(
                zip(market, oracle, strict=True)
            ):
                rows.append(
                    {
                        "replication": replication,
                        "hour": hour,
                        "delay_hours": delay,
                        "market_unsafe_debt": market_debt,
                        "oracle_unsafe_debt": oracle_debt,
                        "false_safe_debt": max(market_debt - oracle_debt, 0.0),
                        "dai_price": 1.0 - 0.0002 * hour - 0.00001 * delay,
                    }
                )
    return pd.DataFrame(rows)


def _summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    post = detail.loc[detail["hour"].ge(CONTRACT.pre_shock_hours)]
    for delay in CONTRACT.delays:
        treatment = post.loc[post["delay_hours"].eq(delay)]
        grouped = treatment.groupby("replication")
        values = {
            "false_safe_debt_hours": grouped["false_safe_debt"].sum().mean(),
            "peak_false_safe_debt": grouped["false_safe_debt"].max().mean(),
            "minimum_dai_price": grouped["dai_price"].min().mean(),
            "mean_absolute_peg_deviation": (
                treatment.assign(deviation=(treatment["dai_price"] - 1.0).abs())
                .groupby("replication")["deviation"]
                .mean()
                .mean()
            ),
        }
        for metric, mean in values.items():
            rows.append(
                {
                    "portfolio": "empirical_crypto",
                    "shock": "joint_crypto_high_correlation",
                    "oracle_delay_steps": delay,
                    "metric": metric,
                    "mean": mean,
                }
            )
    return pd.DataFrame(rows)


def test_frame_preparation_uses_all_replications_and_preserves_share_hours() -> None:
    frames, timestep = prepare_frames(_detail(), CONTRACT)

    assert timestep == 1.0
    assert len(frames) == CONTRACT.total_hours * len(CONTRACT.delays)
    assert (
        frames.groupby("delay_hours")["hour"].nunique().eq(CONTRACT.total_hours).all()
    )
    delay_one = frames.loc[frames["delay_hours"].eq(1)].sort_values("hour")
    assert delay_one["cumulative_absolute_mismatch"].is_monotonic_increasing
    assert delay_one.iloc[-1]["cumulative_absolute_mismatch"] == pytest.approx(0.90)
    zero = frames.loc[frames["delay_hours"].eq(0)]
    assert zero["cumulative_absolute_mismatch"].eq(0.0).all()
    assert zero["false_safe_debt"].eq(0.0).all()


def test_hourly_metrics_reconcile_with_registered_summary_definitions() -> None:
    detail = _detail()
    result = reconcile_registered_summaries(
        detail,
        _summary(detail),
        CONTRACT,
        timestep_hours=1.0,
    )

    assert result["passed"] is True
    assert len(result["checks"]) == 12
    assert all(check["passed"] for check in result["checks"])


def test_incompatible_replication_time_grid_is_rejected() -> None:
    detail = _detail()
    detail = detail.drop(detail.index[-1])

    with pytest.raises(ValueError, match="has 4 hours"):
        prepare_frames(detail, CONTRACT)


def test_zero_delay_false_safety_is_rejected() -> None:
    detail = _detail()
    mask = detail["delay_hours"].eq(0) & detail["hour"].eq(2)
    detail.loc[mask, "false_safe_debt"] = 1.0

    with pytest.raises(ValueError, match="structural zero"):
        prepare_frames(detail, CONTRACT)


def test_compact_scalar_checkpoints_fail_instead_of_inventing_paths(
    tmp_path: Path,
) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    payload = {
        "replication": 0,
        "cell_rows": [
            {
                "portfolio": "empirical_crypto",
                "shock": "joint_crypto_high_correlation",
                "oracle_delay_hours": 0,
                "peak_false_safe_debt": 0.0,
            }
        ],
    }
    (checkpoint_dir / "replication_000.json").write_text(json.dumps(payload))

    with pytest.raises(MissingHourlyEvidenceError, match="scalar cell summaries only"):
        load_hourly_evidence(tmp_path)


def test_embedded_hourly_checkpoint_arrays_are_supported(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    payload = {
        "replication": 0,
        "cell_rows": [
            {
                "portfolio": "empirical_crypto",
                "shock": "joint_crypto_high_correlation",
                "oracle_delay_hours": 1,
                "arrays": {
                    "market_unsafe_debt": [0.0, 10.0],
                    "oracle_unsafe_debt": [0.0, 0.0],
                    "false_safe_debt": [0.0, 10.0],
                    "dai_price": [1.0, 0.999],
                },
            }
        ],
    }
    checkpoint = checkpoint_dir / "replication_000.json"
    checkpoint.write_text(json.dumps(payload))

    detail, sources = load_hourly_evidence(tmp_path)

    assert len(detail) == 2
    assert sources == [checkpoint.resolve()]
    assert detail.iloc[-1]["false_safe_debt"] == 10.0


def test_fixed_axis_limits_cover_every_frame_and_sequence_keeps_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames, _ = prepare_frames(_detail(), CONTRACT)
    hours = validate_frame_table(frames)
    limits = compute_axis_limits(frames)
    monkeypatch.setattr(renderer, "REGISTERED_SHOCK_HOUR", 1)
    settings = RenderSettings(
        fps=10,
        opening_hold_seconds=0.2,
        final_hold_seconds=0.3,
        progression_frames=8,
    )
    sequence = build_frame_sequence(hours, frames, settings)

    assert limits.risk_share[1] >= frames["market_unsafe_debt_share"].max()
    assert limits.risk_share[1] >= frames["oracle_unsafe_debt_share"].max()
    assert limits.false_safe_debt[1] >= frames["false_safe_debt"].max()
    assert limits.mismatch[1] >= frames["cumulative_absolute_mismatch"].max()
    assert limits.dai_price[0] <= frames["dai_price"].min()
    assert limits.dai_price[1] >= frames["dai_price"].max()
    assert sequence[:2] == [0, 0]
    assert sequence[-3:] == [len(hours) - 1] * 3
    assert 1 in sequence
    mechanism_hour = int(frames.groupby("hour")["false_safe_debt"].max().idxmax())
    assert mechanism_hour in sequence
    assert np.all(np.diff(sequence) >= 0)

    figure, update = renderer._build_figure(frames, hours, limits, settings)
    update(len(hours) - 1)
    assert all(text.get_bbox_patch() is None for text in figure.texts)
    assert all("H2" not in text.get_text() for text in figure.texts)
    renderer.plt.close(figure)


def test_presentation_replacement_path_is_not_dot_hidden() -> None:
    path = Path("animation.mp4")

    replacement = _presentation_replacement_path(path)

    assert replacement.name == "animation.presentation-replacement.mp4"
    assert not replacement.name.startswith(".")


def test_replay_scope_contains_only_three_registered_empirical_cells() -> None:
    assert AUTHORIZED_CELLS == experiment.CELL_ORDER[:3]
    assert all("empirical_crypto" in cell for cell in AUTHORIZED_CELLS)
    assert not any("stable_supported" in cell for cell in AUTHORIZED_CELLS)


def test_passive_dai_capture_records_return_without_changing_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Result:
        clipped_next_price = 0.9987

    def fake(*args: object, **kwargs: object) -> Result:
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(market_owner, "coefficient_normalised_market_response", fake)
    with _passive_dai_capture() as captured:
        result = market_owner.coefficient_normalised_market_response(1, marker="same")

    assert result.clipped_next_price == 0.9987
    assert captured == [0.9987]
    assert calls == [((1,), {"marker": "same"})]
    assert market_owner.coefficient_normalised_market_response is fake


def test_scalar_reconciliation_is_exact_and_reports_numeric_difference() -> None:
    assert _scalar_mismatches({"a": 1.0}, {"a": 1.0}) == []
    mismatch = _scalar_mismatches({"a": 1.0}, {"a": 1.0001})
    assert mismatch[0]["field"] == "a"
    assert mismatch[0]["absolute_difference"] == pytest.approx(0.0001)
