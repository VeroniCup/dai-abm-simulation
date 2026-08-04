"""Render the dissertation balance-sheet diversification animation."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FFMpegWriter, FuncAnimation  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from dai_sim.experiments.final import (  # noqa: E402
    idiosyncratic_diversification as experiment,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file  # noqa: E402
from workflows.experiments.final.animation_presentation_style import (  # noqa: E402
    LINE_STANDARD,
    LINE_STRONG,
    PEG_BAND,
    add_peg_reference,
    add_shock_event,
    add_time_cursor,
    add_title_block,
    configure_matplotlib,
    presentation_replacement_path,
    style_axis,
    style_legend,
)
from workflows.experiments.final.build_balance_sheet_animation_frames import (  # noqa: E402
    DEFAULT_METADATA_PATH,
    DEFAULT_SYSTEM_PATH,
    DEFAULT_VAULT_PATH,
    FAMILY_X,
    OUTPUT_DIR,
)
from workflows.experiments.final.replay_balance_sheet_hourly import (  # noqa: E402
    AUTHORIZED_PORTFOLIOS,
    AUTHORIZED_SHOCK,
)


DEFAULT_VIDEO_PATH = OUTPUT_DIR / "balance_sheet_diversification.mp4"
DEFAULT_PREVIEW_PATH = OUTPUT_DIR / "balance_sheet_diversification_preview.mp4"
DEFAULT_STATIC_PATH = OUTPUT_DIR / "balance_sheet_diversification_static.png"
DEFAULT_MANIFEST_PATH = OUTPUT_DIR / "balance_sheet_animation_manifest.json"
PRESENTATION_STYLE_PATH = Path(__file__).with_name("animation_presentation_style.py")
TREATMENT_LABELS = {
    "eth_only": "ETH-only",
    "stable_supported": "Stable-supported",
}
TREATMENT_COLORS = {"eth_only": "#0072B2", "stable_supported": "#009E73"}
FAMILY_LABELS = ("ETH", "WBTC", "STABLE")
PRICE_COLORS = {"ETH": "#C23B4A", "WBTC": "#6C7A89", "STABLE": "#7B61A8"}
UNRESOLVED_COLOR = "#D55E00"


@dataclass(frozen=True)
class RenderSettings:
    fps: int = 20
    width: int = 1920
    height: int = 1080
    dpi: int = 100
    bitrate_kbps: int = 6500
    opening_hold_seconds: float = 1.0
    final_hold_seconds: float = 2.0
    progression_frames: int = 340
    codec: str = "h264"
    blit: bool = False


@dataclass(frozen=True)
class AxisLimits:
    price_index: tuple[float, float]
    vault_margin: tuple[float, float]
    unresolved_debt: tuple[float, float]
    cumulative_liquidated_debt: tuple[float, float]
    dai_price: tuple[float, float]


def validate_frame_tables(
    system: pd.DataFrame, vault: pd.DataFrame, metadata: Mapping[str, Any]
) -> np.ndarray:
    required_system = {
        "hour",
        "treatment",
        "eth_price_index",
        "wbtc_price_index",
        "stable_price_index",
        "unresolved_debt_share_mean",
        "unresolved_debt_share_p025",
        "unresolved_debt_share_p975",
        "cumulative_liquidated_debt_share_mean",
        "cumulative_liquidated_debt_share_p025",
        "cumulative_liquidated_debt_share_p975",
        "dai_price_mean",
        "dai_price_p025",
        "dai_price_p975",
        "replication_count",
    }
    required_vault = {
        "hour",
        "replication",
        "treatment",
        "vault_id",
        "collateral_family",
        "vault_debt",
        "liquidation_margin",
        "canonical_vault_state",
        "scatter_x",
        "point_area",
    }
    if missing := sorted(required_system - set(system)):
        raise ValueError(f"System frame table is missing columns: {missing}")
    if missing := sorted(required_vault - set(vault)):
        raise ValueError(f"Vault frame table is missing columns: {missing}")
    if set(system["treatment"].unique()) != set(AUTHORIZED_PORTFOLIOS):
        raise ValueError("System frame treatments differ from the registered pair.")
    if set(vault["treatment"].unique()) != set(AUTHORIZED_PORTFOLIOS):
        raise ValueError("Vault frame treatments differ from the registered pair.")
    reference: np.ndarray | None = None
    for treatment in AUTHORIZED_PORTFOLIOS:
        selected = system.loc[system["treatment"].eq(treatment)].sort_values("hour")
        hours = selected["hour"].to_numpy(dtype=int)
        if reference is None:
            reference = hours
        elif not np.array_equal(hours, reference):
            raise ValueError("Treatment system frames have incompatible time grids.")
        if not selected["replication_count"].eq(experiment.REPLICATIONS).all():
            raise ValueError("A system frame does not use all registered replications.")
    if reference is None or not np.array_equal(
        reference, np.arange(experiment.TOTAL_HOURS)
    ):
        raise ValueError("System frame grid is not the registered 768 hours.")
    selected_replication = int(metadata["representative_replication"])
    if set(vault["replication"].unique()) != {selected_replication}:
        raise ValueError("Vault frames differ from the preselected replication.")
    numeric_system = system.drop(columns=["treatment"]).to_numpy(dtype=float)
    numeric_vault = vault.drop(
        columns=["treatment", "collateral_family", "canonical_vault_state"]
    ).to_numpy(dtype=float)
    if not np.isfinite(numeric_system).all() or not np.isfinite(numeric_vault).all():
        raise ValueError("Animation frame tables contain non-finite values.")
    return reference.astype(float)


def compute_axis_limits(system: pd.DataFrame, vault: pd.DataFrame) -> AxisLimits:
    prices = system[
        ["eth_price_index", "wbtc_price_index", "stable_price_index"]
    ].to_numpy(dtype=float)
    price_low, price_high = float(prices.min()), float(prices.max())
    price_pad = max((price_high - price_low) * 0.08, 0.5)
    margin_low = min(float(vault["liquidation_margin"].min()) * 1.2, -0.025)
    margin_high = max(float(vault["liquidation_margin"].max()) * 1.08, 1.0)
    unresolved_max = float(system["unresolved_debt_share_p975"].max())
    liquidated_max = float(system["cumulative_liquidated_debt_share_p975"].max())
    dai_low = min(float(system["dai_price_p025"].min()), PEG_BAND[0], 1.0)
    dai_high = max(float(system["dai_price_p975"].max()), PEG_BAND[1], 1.0)
    dai_span = dai_high - dai_low
    limits = AxisLimits(
        price_index=(price_low - price_pad, price_high + price_pad),
        vault_margin=(margin_low, margin_high),
        unresolved_debt=(0.0, max(unresolved_max * 1.08, 0.001)),
        cumulative_liquidated_debt=(
            0.0,
            max(liquidated_max * 1.08, 0.001),
        ),
        dai_price=(dai_low - 0.06 * dai_span, dai_high + 0.06 * dai_span),
    )
    if any(
        not np.isfinite(values).all() or values[0] >= values[1]
        for values in asdict(limits).values()
    ):
        raise ValueError("Computed animation axis limits are invalid.")
    return limits


def slow_motion_interval(system: pd.DataFrame) -> tuple[int, int, int]:
    eth_only = system.loc[system["treatment"].eq("eth_only")].sort_values("hour")
    unresolved = eth_only["unresolved_debt_share_mean"].to_numpy(dtype=float)
    post = unresolved[experiment.PRE_SHOCK_HOURS :]
    threshold = 0.10 * float(post.max())
    positions = np.flatnonzero(post >= threshold)
    onset = (
        experiment.PRE_SHOCK_HOURS
        if not len(positions)
        else experiment.PRE_SHOCK_HOURS + int(positions[0])
    )
    return max(0, experiment.PRE_SHOCK_HOURS - 6), min(onset + 48, 767), onset


def build_frame_sequence(
    hours: np.ndarray,
    system: pd.DataFrame,
    settings: RenderSettings = RenderSettings(),
) -> list[int]:
    slow_start, slow_end, _ = slow_motion_interval(system)
    weights = np.ones(len(hours), dtype=float)
    weights[hours < slow_start] = 0.55
    weights[(hours >= slow_start) & (hours <= slow_end)] = 5.0
    cumulative = np.cumsum(weights)
    targets = np.linspace(cumulative[0], cumulative[-1], settings.progression_frames)
    progression = np.searchsorted(cumulative, targets, side="left").clip(
        0, len(hours) - 1
    )
    progression[0] = 0
    progression[-1] = len(hours) - 1
    shock_index = int(np.searchsorted(hours, experiment.PRE_SHOCK_HOURS))
    shock_position = int(np.searchsorted(progression, shock_index, side="left"))
    if 0 < shock_position < len(progression) - 1:
        progression[shock_position] = shock_index
    opening = [0] * int(round(settings.opening_hold_seconds * settings.fps))
    closing = [len(hours) - 1] * int(round(settings.final_hold_seconds * settings.fps))
    sequence = opening + progression.astype(int).tolist() + closing
    if any(right < left for left, right in zip(sequence, sequence[1:], strict=False)):
        raise ValueError("Animation sequence moves backwards in time.")
    return sequence


def _series(system: pd.DataFrame, treatment: str, column: str) -> np.ndarray:
    return (
        system.loc[system["treatment"].eq(treatment)]
        .sort_values("hour")[column]
        .to_numpy(dtype=float)
    )


def _vault_arrays(
    vault: pd.DataFrame,
) -> dict[tuple[str, int, str], tuple[np.ndarray, np.ndarray]]:
    arrays: dict[tuple[str, int, str], tuple[np.ndarray, np.ndarray]] = {}
    for (treatment, hour, state), selected in vault.groupby(
        ["treatment", "hour", "canonical_vault_state"], sort=False
    ):
        arrays[(str(treatment), int(hour), str(state))] = (
            selected[["scatter_x", "liquidation_margin"]].to_numpy(dtype=float),
            selected["point_area"].to_numpy(dtype=float),
        )
    return arrays


def _vault_counters(vault: pd.DataFrame) -> dict[tuple[str, int], tuple[int, int, int]]:
    counters = {}
    for (treatment, hour), selected in vault.groupby(["treatment", "hour"]):
        active = len(selected)
        unresolved = int(
            selected["canonical_vault_state"].eq("liquidatable_unresolved").sum()
        )
        counters[(str(treatment), int(hour))] = (
            active,
            unresolved,
            experiment.VAULT_COUNT - active,
        )
    return counters


def _style_axis(axis: Axes, compact: bool) -> None:
    style_axis(axis, compact=compact)


def _build_figure(
    system: pd.DataFrame,
    vault: pd.DataFrame,
    hours: np.ndarray,
    limits: AxisLimits,
    settings: RenderSettings,
    representative_replication: int,
) -> tuple[Figure, Callable[[int], None]]:
    compact = settings.width < 1200
    configure_matplotlib(compact=compact)
    figure = plt.figure(
        figsize=(settings.width / settings.dpi, settings.height / settings.dpi),
        dpi=settings.dpi,
        constrained_layout=False,
    )
    grid = figure.add_gridspec(
        3,
        6,
        height_ratios=(0.92, 1.12, 0.95),
        left=0.075 if compact else 0.06,
        right=0.98,
        top=0.885 if compact else 0.89,
        bottom=0.085,
        hspace=0.48 if compact else 0.38,
        wspace=0.62 if compact else 0.42,
    )
    price_axis = figure.add_subplot(grid[0, :])
    vault_axes = {
        "eth_only": figure.add_subplot(grid[1, :3]),
        "stable_supported": figure.add_subplot(grid[1, 3:]),
    }
    unresolved_axis = figure.add_subplot(grid[2, :2])
    liquidated_axis = figure.add_subplot(grid[2, 2:4])
    dai_axis = figure.add_subplot(grid[2, 4:])
    all_axes = [
        price_axis,
        *vault_axes.values(),
        unresolved_axis,
        liquidated_axis,
        dai_axis,
    ]
    for axis in all_axes:
        _style_axis(axis, compact)
    time_label = add_title_block(
        figure,
        title="Same Shock, Different Balance Sheets",
        subtitle=(
            "ETH-only versus stable-supported collateral · paired illustration and "
            "128-replication ensemble"
        ),
        compact=compact,
    )
    price_axis.set_title(
        "Same registered external collateral-price path", loc="left", fontweight="bold"
    )
    price_axis.set_ylabel("Price index (hour 0 = 100)")
    price_axis.set_xlabel("Simulation hour")
    price_axis.set_xlim(hours[0], hours[-1])
    price_axis.set_ylim(*limits.price_index)
    add_shock_event(
        price_axis,
        hour=experiment.PRE_SHOCK_HOURS,
        label="Registered severe isolated ETH shock",
        compact=compact,
    )
    price_lines = {}
    price_source = system.loc[system["treatment"].eq("eth_only")].sort_values("hour")
    for family, column in (
        ("ETH", "eth_price_index"),
        ("WBTC", "wbtc_price_index"),
        ("STABLE", "stable_price_index"),
    ):
        (price_lines[family],) = price_axis.plot(
            [], [], color=PRICE_COLORS[family], linewidth=LINE_STANDARD, label=family
        )
    style_legend(
        price_axis,
        compact=compact,
        loc="lower right",
        ncol=3,
        fontsize=6.0 if compact else 8.5,
    )
    price_cursor = add_time_cursor(price_axis, hours[0])

    vault_data = _vault_arrays(vault)
    counters = _vault_counters(vault)
    empty_offsets = np.empty((0, 2), dtype=float)
    scatters: dict[tuple[str, str], Any] = {}
    counter_text = {}
    for treatment, axis in vault_axes.items():
        axis.set_title(
            f"{TREATMENT_LABELS[treatment]} · illustrative median-effect pair",
            loc="left",
            fontweight="bold",
        )
        axis.set_xlim(-0.48, 2.48)
        axis.set_xticks(list(FAMILY_X.values()), FAMILY_LABELS)
        axis.set_ylabel("Liquidation margin (symlog)")
        axis.set_yscale("symlog", linthresh=0.05, linscale=0.8)
        axis.set_ylim(*limits.vault_margin)
        axis.axhline(0.0, color="#8B1E3F", linewidth=1.2, linestyle="--")
        axis.text(
            0.01,
            0.96,
            f"Illustrative paired replication: {representative_replication}",
            transform=axis.transAxes,
            va="top",
            fontsize=6.5 if compact else 8.5,
            color="#52667A",
        )
        scatters[(treatment, "safe")] = axis.scatter(
            [],
            [],
            s=[],
            color=TREATMENT_COLORS[treatment],
            alpha=0.45,
            edgecolors="none",
        )
        scatters[(treatment, "liquidatable_unresolved")] = axis.scatter(
            [],
            [],
            s=[],
            color=UNRESOLVED_COLOR,
            alpha=0.9,
            edgecolors="#7A2E00",
            linewidths=0.35,
            zorder=5,
        )
        counter_text[treatment] = axis.text(
            0.99,
            0.96,
            "",
            transform=axis.transAxes,
            ha="right",
            va="top",
            fontsize=6.5 if compact else 8.5,
            color="#17324D",
        )

    system_axes = {
        "unresolved": unresolved_axis,
        "liquidated": liquidated_axis,
        "dai": dai_axis,
    }
    unresolved_axis.set_title("Unresolved debt", loc="left", fontweight="bold")
    unresolved_axis.set_ylabel("Share of initial debt")
    unresolved_axis.set_ylim(*limits.unresolved_debt)
    liquidated_axis.set_title(
        "Cumulative liquidated debt", loc="left", fontweight="bold"
    )
    liquidated_axis.set_ylabel("Share of initial debt")
    liquidated_axis.set_ylim(*limits.cumulative_liquidated_debt)
    dai_axis.set_title("Stage 1 DAI price", loc="left", fontweight="bold")
    dai_axis.set_ylabel("DAI / USD")
    dai_axis.set_ylim(*limits.dai_price)
    add_peg_reference(dai_axis)
    for axis in system_axes.values():
        axis.set_xlim(hours[0], hours[-1])
        axis.set_xlabel("Simulation hour")
        axis.text(
            0.01,
            0.96,
            "Across 128 registered replications",
            transform=axis.transAxes,
            va="top",
            fontsize=5.8 if compact else 8,
            color="#52667A",
        )

    metric_config = {
        "unresolved": "unresolved_debt_share",
        "liquidated": "cumulative_liquidated_debt_share",
        "dai": "dai_price",
    }
    metric_lines: dict[tuple[str, str], Any] = {}
    band_clips: dict[str, Rectangle] = {}
    cursors = [price_cursor]
    for name, axis in system_axes.items():
        low, high = axis.get_ylim()
        clip = Rectangle((hours[0], low), 0.0, high - low, transform=axis.transData)
        band_clips[name] = clip
        metric = metric_config[name]
        for treatment in AUTHORIZED_PORTFOLIOS:
            lower = _series(system, treatment, f"{metric}_p025")
            upper = _series(system, treatment, f"{metric}_p975")
            band = axis.fill_between(
                hours,
                lower,
                upper,
                color=TREATMENT_COLORS[treatment],
                alpha=0.08,
                linewidth=0,
            )
            band.set_clip_path(clip)
            (metric_lines[(name, treatment)],) = axis.plot(
                [],
                [],
                color=TREATMENT_COLORS[treatment],
                linewidth=(LINE_STRONG if treatment == "eth_only" else LINE_STANDARD),
                label=TREATMENT_LABELS[treatment],
            )
        cursor = add_time_cursor(axis, hours[0])
        cursors.append(cursor)
        style_legend(
            axis,
            compact=compact,
            loc="upper right" if name != "dai" else "lower right",
            fontsize=5.8 if compact else 7.5,
        )

    price_values = {
        family: price_source[column].to_numpy(dtype=float)
        for family, column in (
            ("ETH", "eth_price_index"),
            ("WBTC", "wbtc_price_index"),
            ("STABLE", "stable_price_index"),
        )
    }
    metric_values = {
        (name, treatment): _series(system, treatment, f"{metric}_mean")
        for name, metric in metric_config.items()
        for treatment in AUTHORIZED_PORTFOLIOS
    }

    def update(index: int) -> None:
        stop = index + 1
        current_hours = hours[:stop]
        for family, line in price_lines.items():
            line.set_data(current_hours, price_values[family][:stop])
        for treatment in AUTHORIZED_PORTFOLIOS:
            for state in ("safe", "liquidatable_unresolved"):
                offsets, sizes = vault_data.get(
                    (treatment, index, state), (empty_offsets, np.empty(0))
                )
                scatters[(treatment, state)].set_offsets(offsets)
                scatters[(treatment, state)].set_sizes(sizes)
            active, unresolved, closed = counters[(treatment, index)]
            counter_text[treatment].set_text(
                f"Active {active} · unresolved {unresolved} · liquidated {closed}"
            )
        for name in system_axes:
            band_clips[name].set_width(max(hours[index] - hours[0], 0.1))
            for treatment in AUTHORIZED_PORTFOLIOS:
                metric_lines[(name, treatment)].set_data(
                    current_hours, metric_values[(name, treatment)][:stop]
                )
        for cursor in cursors:
            cursor.set_xdata([hours[index], hours[index]])
        time_label.set_text(f"Hour {hours[index]:,.0f}")

    return figure, update


def _ffmpeg_executable() -> str | None:
    configured = os.environ.get("DAI_ANIMATION_FFMPEG")
    command = configured or shutil.which("ffmpeg")
    if command is None:
        return None
    path = Path(command).expanduser()
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    try:
        subprocess.run([str(path), "-version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    matplotlib.rcParams["animation.ffmpeg_path"] = str(path)
    return str(path.resolve())


def _tool_version(command: str) -> str:
    result = subprocess.run(
        [command, "-version"], check=True, capture_output=True, text=True
    )
    return result.stdout.splitlines()[0]


def _ffmpeg_details() -> dict[str, Any]:
    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required to render the animation.")
    sibling = Path(ffmpeg).with_name("ffprobe")
    ffprobe = str(sibling) if sibling.is_file() else shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("FFprobe is required to validate the animation.")
    return {
        "path": ffmpeg,
        "version": _tool_version(ffmpeg),
        "ffprobe_path": str(Path(ffprobe).resolve()),
        "ffprobe_version": _tool_version(ffprobe),
        "environment_override": os.environ.get("DAI_ANIMATION_FFMPEG"),
    }


def _rate(value: str) -> float:
    numerator, denominator = value.split("/", maxsplit=1)
    return float(numerator) / float(denominator)


def _probe_and_decode(
    path: Path, settings: RenderSettings, expected_frames: int
) -> dict[str, Any]:
    tools = _ffmpeg_details()
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Rendered video is missing or empty: {path}")
    result = subprocess.run(
        [
            tools["ffprobe_path"],
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,pix_fmt,avg_frame_rate,nb_frames:format=duration,size,format_name",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if len(payload.get("streams", [])) != 1:
        raise RuntimeError(f"Expected one video stream in {path}.")
    stream = payload["streams"][0]
    metadata = {
        "codec": stream["codec_name"],
        "pixel_format": stream["pix_fmt"],
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "frame_rate": stream["avg_frame_rate"],
        "frames": int(stream["nb_frames"]),
        "duration_seconds": float(payload["format"]["duration"]),
        "size_bytes": int(payload["format"]["size"]),
        "container": payload["format"]["format_name"],
    }
    expected = (
        metadata["codec"] == "h264"
        and metadata["pixel_format"] == "yuv420p"
        and metadata["width"] == settings.width
        and metadata["height"] == settings.height
        and abs(_rate(metadata["frame_rate"]) - settings.fps) <= 1e-12
        and metadata["frames"] == expected_frames
        and abs(metadata["duration_seconds"] - expected_frames / settings.fps)
        <= 1.0 / settings.fps
    )
    if not expected:
        raise RuntimeError(f"Rendered video metadata failed validation: {metadata}")
    decoded = subprocess.run(
        [
            tools["path"],
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if decoded.returncode != 0:
        raise RuntimeError(f"Video failed full decode: {path}: {decoded.stderr}")
    metadata["full_decode"] = "passed_through_final_frame"
    return metadata


def _render_video(
    system: pd.DataFrame,
    vault: pd.DataFrame,
    metadata: Mapping[str, Any],
    destination: Path,
    settings: RenderSettings,
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite animation: {destination}")
    if _ffmpeg_executable() is None:
        raise RuntimeError("FFmpeg is required to render the animation.")
    hours = validate_frame_tables(system, vault, metadata)
    limits = compute_axis_limits(system, vault)
    sequence = build_frame_sequence(hours, system, settings)
    figure, update = _build_figure(
        system,
        vault,
        hours,
        limits,
        settings,
        int(metadata["representative_replication"]),
    )

    def animate(index: int) -> None:
        update(index)

    animation = FuncAnimation(
        figure,
        animate,
        frames=sequence,
        interval=1000 / settings.fps,
        blit=settings.blit,
        repeat=False,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    writer = FFMpegWriter(
        fps=settings.fps,
        codec=settings.codec,
        bitrate=settings.bitrate_kbps,
        extra_args=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        metadata={
            "title": "Same Shock, Different Balance Sheets",
            "artist": "DAI ABM dissertation reporting",
        },
    )
    animation.save(destination, writer=writer, dpi=settings.dpi)
    plt.close(figure)
    probe = _probe_and_decode(destination, settings, len(sequence))
    slow_start, slow_end, onset = slow_motion_interval(system)
    return {
        "path": destination,
        "settings": asdict(settings),
        "frame_count": len(sequence),
        "duration_seconds": len(sequence) / settings.fps,
        "first_hour": float(hours[sequence[0]]),
        "last_hour": float(hours[sequence[-1]]),
        "axis_limits": asdict(limits),
        "frame_timing": {
            "pre_slow_weight": 0.55,
            "normal_weight": 1.0,
            "slow_weight": 5.0,
            "slow_interval": [slow_start, slow_end],
            "shock_hour": experiment.PRE_SHOCK_HOURS,
            "first_post_shock_substantial_unresolved_hour": onset,
            "substantial_rule": (
                "first post-shock hour at or above 10% of the post-shock "
                "ensemble maximum unresolved-debt share"
            ),
        },
        "codec_metadata": probe,
    }


def _render_static(
    system: pd.DataFrame,
    vault: pd.DataFrame,
    metadata: Mapping[str, Any],
    destination: Path,
    settings: RenderSettings,
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite static frame: {destination}")
    hours = validate_frame_tables(system, vault, metadata)
    figure, update = _build_figure(
        system,
        vault,
        hours,
        compute_axis_limits(system, vault),
        settings,
        int(metadata["representative_replication"]),
    )
    hour = int(metadata["representative_static_hour"])
    update(hour)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=settings.dpi, facecolor=figure.get_facecolor())
    plt.close(figure)
    return {"path": destination, "hour": hour}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ("git", *args),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_porcelain": run("status", "--porcelain=v1").splitlines(),
        "staged_paths": run("diff", "--cached", "--name-only").splitlines(),
    }


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.partial")
    if temporary.exists():
        raise FileExistsError(f"Refusing to overwrite temporary manifest: {temporary}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _presentation_replacement_path(path: Path) -> Path:
    return presentation_replacement_path(path)


def _completed_render_for_replacement(
    paths: Mapping[str, Path], source_paths: tuple[Path, ...]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    manifest_path = paths["manifest"]
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Presentation replacement requires the completed manifest: {manifest_path}"
        )
    completed = json.loads(manifest_path.read_text())
    if completed.get("status") != "complete":
        raise ValueError(
            "Presentation replacement requires a completed render manifest."
        )
    outputs = completed.get("outputs", [])
    expected_outputs = {
        _relative(paths[label]) for label in ("preview", "static", "video")
    }
    if {record.get("path") for record in outputs} != expected_outputs:
        raise ValueError(
            "Completed manifest output paths differ from requested outputs."
        )
    for record in outputs:
        output_path = REPOSITORY_ROOT / record["path"]
        if not output_path.is_file() or sha256_file(output_path) != record.get(
            "sha256"
        ):
            raise ValueError(
                f"Completed render checksum differs before replacement: {output_path}"
            )
    recorded_sources = {
        record.get("path"): record.get("sha256")
        for record in completed.get("source_paths", [])
    }
    for source_path in source_paths:
        if recorded_sources.get(_relative(source_path)) != sha256_file(source_path):
            raise ValueError(
                f"Validated source checksum differs before replacement: {source_path}"
            )
    static_record = completed["rendering"]["static"]
    return (
        {
            "path": paths["static"],
            "hour": int(static_record["hour"]),
            "reused_from_validated_completed_manifest": True,
        },
        outputs,
    )


def render_outputs(
    *,
    system_path: Path = DEFAULT_SYSTEM_PATH,
    vault_path: Path = DEFAULT_VAULT_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    video_path: Path = DEFAULT_VIDEO_PATH,
    preview_path: Path = DEFAULT_PREVIEW_PATH,
    static_path: Path = DEFAULT_STATIC_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    replace_completed_render: bool = False,
) -> Mapping[str, Path]:
    paths = {
        "video": video_path,
        "preview": preview_path,
        "static": static_path,
        "manifest": manifest_path,
    }
    source_paths = (system_path, vault_path, metadata_path)
    prior_outputs: list[dict[str, str]] | None = None
    reused_static: dict[str, Any] | None = None
    encode_paths = {
        "video": video_path,
        "preview": preview_path,
        "static": static_path,
    }
    if replace_completed_render:
        if _ffmpeg_executable() is None:
            raise RuntimeError(
                "FFmpeg is unavailable; presentation replacement failed."
            )
        reused_static, prior_outputs = _completed_render_for_replacement(
            paths, source_paths
        )
        encode_paths = {
            label: _presentation_replacement_path(paths[label])
            for label in ("preview", "video")
        }
        conflicts = [path for path in encode_paths.values() if path.exists()]
        if conflicts:
            raise FileExistsError(
                f"Refusing to overwrite temporary render artefacts: {conflicts}"
            )
    else:
        conflicts = [path for path in paths.values() if path.exists()]
        if conflicts:
            raise FileExistsError(
                f"Refusing to overwrite reporting artefacts: {conflicts}"
            )
    system = pd.read_csv(system_path)
    vault = pd.read_csv(vault_path)
    metadata = json.loads(metadata_path.read_text())
    validate_frame_tables(system, vault, metadata)
    if _ffmpeg_executable() is None:
        static = _render_static(system, vault, metadata, static_path, RenderSettings())
        manifest = {
            "schema_version": 1,
            "producer": "workflows.experiments.final.render_balance_sheet_animation",
            "status": "static_complete_video_blocked_ffmpeg_unavailable",
            "static": {
                **static,
                "path": _relative(static_path),
                "sha256": sha256_file(static_path),
            },
        }
        _write_manifest(manifest_path, manifest)
        return {"static": static_path, "manifest": manifest_path}
    preview_settings = RenderSettings(
        fps=10,
        width=960,
        height=540,
        dpi=100,
        bitrate_kbps=1800,
        opening_hold_seconds=0.5,
        final_hold_seconds=1.0,
        progression_frames=85,
    )
    preview = _render_video(
        system, vault, metadata, encode_paths["preview"], preview_settings
    )
    final_settings = RenderSettings()
    static = reused_static or _render_static(
        system, vault, metadata, encode_paths["static"], final_settings
    )
    final = _render_video(
        system, vault, metadata, encode_paths["video"], final_settings
    )
    if replace_completed_render:
        for label in ("preview", "video"):
            encode_paths[label].replace(paths[label])
        preview["path"] = preview_path
        final["path"] = video_path
    manifest = {
        "schema_version": 1,
        "producer": "workflows.experiments.final.render_balance_sheet_animation",
        "status": "complete",
        "title": "Same Shock, Different Balance Sheets",
        "subtitle": "ETH-only versus stable-supported collateral",
        "experiment_id": metadata["experiment_id"],
        "experiment_identity": metadata["experiment_identity"],
        "shock": AUTHORIZED_SHOCK,
        "treatments": list(AUTHORIZED_PORTFOLIOS),
        "replication_count": experiment.REPLICATIONS,
        "representative_replication": metadata["representative_replication"],
        "representative_replication_selection": metadata[
            "representative_replication_selection"
        ],
        "scientific_interpretation": (
            "Stable collateral reduces liquidation pressure under an isolated "
            "ETH shock. Balance-sheet resilience improves, while the Stage 1 "
            "DAI path remains unchanged."
        ),
        "source_git": _git_state(),
        "source_paths": [
            {"path": _relative(path), "sha256": sha256_file(path)}
            for path in (system_path, vault_path, metadata_path)
        ],
        "derived_metrics": metadata["derived_metrics"],
        "reconciliation": {
            "replay_row_level": metadata["replay_manifest"]["row_level_reconciliation"],
            "replay_aggregate": metadata["replay_manifest"]["aggregate_reconciliation"],
            "vault_accounting": metadata["replay_manifest"]["vault_accounting"],
            "frame_endpoints": metadata["validation"]["endpoint_reconciliation"],
        },
        "rendering": {
            "command": shlex.join(
                [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
            ),
            "ffmpeg": _ffmpeg_details(),
            "presentation_replacement": (
                {
                    "reason": "remove in-video final interpretation card",
                    "prior_outputs": prior_outputs,
                }
                if prior_outputs is not None
                else None
            ),
            "preview": {**preview, "path": _relative(preview_path)},
            "static": {
                **static,
                "path": _relative(static_path),
                "sha256": sha256_file(static_path),
            },
            "final": {**final, "path": _relative(video_path)},
            "treatment_encoding": {
                treatment: {
                    "label": TREATMENT_LABELS[treatment],
                    "color": TREATMENT_COLORS[treatment],
                }
                for treatment in AUTHORIZED_PORTFOLIOS
            },
            "vault_state_encoding": {
                "safe": "treatment colour, translucent",
                "liquidatable_unresolved": UNRESOLVED_COLOR,
                "closed": "omitted from active scatter and retained in counters",
            },
            "uncertainty": "pointwise 2.5th--97.5th percentile bands",
            "shared_presentation_style": {
                "path": _relative(PRESENTATION_STYLE_PATH),
                "sha256": sha256_file(PRESENTATION_STYLE_PATH),
            },
            "closing_hold": {
                "duration_seconds": final_settings.final_hold_seconds,
                "frames": int(
                    round(final_settings.final_hold_seconds * final_settings.fps)
                ),
                "visual_state": "completed final data frame",
                "overlay": None,
                "interpretation_delivery": "spoken or surrounding slide",
            },
        },
        "outputs": [
            {"path": _relative(path), "sha256": sha256_file(path)}
            for path in (preview_path, static_path, video_path)
        ],
        "reproduction_commands": {
            "replay": metadata["replay_manifest"]["execution"]["command"],
            "frames": (
                "PYTHONPATH=src:. python workflows/experiments/final/"
                "build_balance_sheet_animation_frames.py"
            ),
            "render": shlex.join(
                [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
            ),
        },
        "original_checkpoints_unchanged": True,
        "final_conclusions_changed": False,
    }
    _write_manifest(manifest_path, manifest)
    return {
        "preview": preview_path,
        "static": static_path,
        "video": video_path,
        "manifest": manifest_path,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", type=Path, default=DEFAULT_SYSTEM_PATH)
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO_PATH)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--replace-completed-render",
        action="store_true",
        help=(
            "Checksum-gated presentation rerender of a completed animation; encode "
            "to visible temporary files and promote only after validation."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        outputs = render_outputs(
            system_path=args.system,
            vault_path=args.vault,
            metadata_path=args.metadata,
            video_path=args.video,
            preview_path=args.preview,
            static_path=args.static,
            manifest_path=args.manifest,
            replace_completed_render=args.replace_completed_render,
        )
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
