"""Render the dissertation oracle-delay animation with Matplotlib."""

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
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from workflows.experiments.final.animation_presentation_style import (  # noqa: E402
    LINE_REFERENCE,
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
from workflows.experiments.final.build_oracle_delay_animation_frames import (  # noqa: E402
    DEFAULT_FRAME_PATH,
    DEFAULT_METADATA_PATH,
    DEFAULT_OUTPUT_DIR,
    DELAY_TO_TREATMENT,
    REPOSITORY_ROOT,
    sha256_file,
)


DEFAULT_VIDEO_PATH = DEFAULT_OUTPUT_DIR / "oracle_delay_false_safety.mp4"
DEFAULT_PREVIEW_PATH = DEFAULT_OUTPUT_DIR / "oracle_delay_false_safety_preview.mp4"
DEFAULT_STATIC_PATH = DEFAULT_OUTPUT_DIR / "oracle_delay_false_safety_static.png"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "oracle_delay_animation_manifest.json"
PRESENTATION_STYLE_PATH = Path(__file__).with_name("animation_presentation_style.py")
PEG_BAND_SOURCE = (
    REPOSITORY_ROOT / "config" / "sensitivities" / "eth_recovery_matrix.yaml"
)
COLORS = {0: "#708090", 1: "#E69F00", 2: "#C23B4A"}
MARKET_COLOR = "#17324D"
DELAY_LABELS = {delay: f"{delay}-hour delay" for delay in DELAY_TO_TREATMENT}
REGISTERED_SHOCK_HOUR = 48


@dataclass(frozen=True)
class RenderSettings:
    fps: int = 20
    width: int = 1920
    height: int = 1080
    dpi: int = 100
    bitrate_kbps: int = 6500
    opening_hold_seconds: float = 1.0
    final_hold_seconds: float = 2.0
    progression_frames: int = 260
    codec: str = "h264"
    blit: bool = False


@dataclass(frozen=True)
class AxisLimits:
    risk_share: tuple[float, float]
    false_safe_debt: tuple[float, float]
    mismatch: tuple[float, float]
    dai_price: tuple[float, float]


def _series(frame: pd.DataFrame, delay: int, column: str) -> np.ndarray:
    selected = frame.loc[frame["delay_hours"].eq(delay)].sort_values("hour")
    return selected[column].to_numpy(dtype=float)


def validate_frame_table(frame: pd.DataFrame) -> np.ndarray:
    required = {"hour", "delay_hours", "treatment"}
    for metric in (
        "market_unsafe_debt_share",
        "oracle_unsafe_debt_share",
        "false_safe_debt",
        "cumulative_absolute_mismatch",
        "dai_price",
    ):
        required.update((metric, f"{metric}_p025", f"{metric}_p975"))
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Animation frame table is missing columns: {missing}.")
    if set(frame["delay_hours"].unique()) != set(DELAY_TO_TREATMENT):
        raise ValueError("Animation frame table does not contain delays 0, 1 and 2.")
    reference: np.ndarray | None = None
    for delay, treatment in DELAY_TO_TREATMENT.items():
        selected = frame.loc[frame["delay_hours"].eq(delay)].sort_values("hour")
        if not selected["treatment"].eq(treatment).all():
            raise ValueError(
                f"Delay {delay} treatment label differs from the registry."
            )
        hours = selected["hour"].to_numpy(dtype=float)
        if reference is None:
            reference = hours
        elif not np.array_equal(hours, reference):
            raise ValueError("Animation treatments have incompatible time grids.")
    numeric = frame.drop(columns=["treatment"]).to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("Animation frame table contains missing or infinite values.")
    assert reference is not None
    return reference


def compute_axis_limits(frame: pd.DataFrame) -> AxisLimits:
    risk_max = max(
        float(frame["market_unsafe_debt_share"].max()),
        float(frame["oracle_unsafe_debt_share"].max()),
    )
    false_safe_max = float(frame["false_safe_debt"].max())
    mismatch_max = float(frame["cumulative_absolute_mismatch"].max())
    dai_low = min(float(frame["dai_price"].min()), PEG_BAND[0], 1.0)
    dai_high = max(float(frame["dai_price"].max()), PEG_BAND[1], 1.0)
    dai_span = max(dai_high - dai_low, 0.002)
    limits = AxisLimits(
        risk_share=(0.0, max(risk_max * 1.10, 0.001)),
        false_safe_debt=(0.0, max(false_safe_max * 1.12, 1.0)),
        mismatch=(0.0, max(mismatch_max * 1.08, 0.001)),
        dai_price=(dai_low - 0.08 * dai_span, dai_high + 0.08 * dai_span),
    )
    arrays = [
        limits.risk_share,
        limits.false_safe_debt,
        limits.mismatch,
        limits.dai_price,
    ]
    if any(
        not np.isfinite(values).all() or values[0] >= values[1] for values in arrays
    ):
        raise ValueError("Computed animation axis limits are invalid.")
    return limits


def stress_interval(frame: pd.DataFrame) -> tuple[float, float]:
    by_hour = frame.groupby("hour", sort=True)["false_safe_debt"].max()
    maximum = float(by_hour.max())
    if maximum <= 0.0:
        return float(by_hour.index.min()), float(by_hour.index.max())
    peak_hour = float(by_hour.idxmax())
    # Slow the 48-hour window centred on the principal disagreement peak.
    # Later isolated spikes remain visible but do not make the entire horizon slow.
    return (
        max(float(by_hour.index.min()), peak_hour - 24.0),
        min(float(by_hour.index.max()), peak_hour + 24.0),
    )


def build_frame_sequence(
    hours: np.ndarray,
    frame: pd.DataFrame,
    settings: RenderSettings = RenderSettings(),
) -> list[int]:
    """Repeat/subsample indices while retaining the original simulation grid."""
    stress_start, stress_end = stress_interval(frame)
    weights = np.ones(hours.size, dtype=float)
    weights[(hours >= stress_start) & (hours <= stress_end)] = 4.0
    cumulative = np.cumsum(weights)
    targets = np.linspace(cumulative[0], cumulative[-1], settings.progression_frames)
    progression = np.searchsorted(cumulative, targets, side="left").clip(
        0, hours.size - 1
    )
    progression[0] = 0
    progression[-1] = hours.size - 1
    mechanism_hour = int(
        frame.groupby("hour", sort=True)["false_safe_debt"].max().idxmax()
    )
    for retained_hour in sorted({REGISTERED_SHOCK_HOUR, mechanism_hour}):
        retained_index = int(np.searchsorted(hours, retained_hour))
        position = int(np.searchsorted(progression, retained_index, side="left"))
        if 0 < position < len(progression) - 1:
            progression[position] = retained_index
    opening = [0] * int(round(settings.opening_hold_seconds * settings.fps))
    closing = [hours.size - 1] * int(round(settings.final_hold_seconds * settings.fps))
    sequence = opening + progression.astype(int).tolist() + closing
    if sequence[0] != 0 or sequence[-1] != hours.size - 1:
        raise ValueError("Animation sequence does not preserve time endpoints.")
    if any(right < left for left, right in zip(sequence, sequence[1:], strict=False)):
        raise ValueError("Animation sequence moves backwards in simulation time.")
    return sequence


def _style_axis(axis: Axes, *, compact: bool) -> None:
    style_axis(axis, compact=compact)


def _format_dai(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}m DAI"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k DAI"
    return f"{value:,.0f} DAI"


def _build_figure(
    frame: pd.DataFrame,
    hours: np.ndarray,
    limits: AxisLimits,
    settings: RenderSettings,
) -> tuple[Figure, Callable[[int], None]]:
    compact = settings.width < 1200
    configure_matplotlib(compact=compact)
    figure = plt.figure(
        figsize=(settings.width / settings.dpi, settings.height / settings.dpi),
        dpi=settings.dpi,
        constrained_layout=False,
    )
    grid = figure.add_gridspec(
        2,
        3,
        height_ratios=(1.65, 1.0),
        left=0.075 if compact else 0.06,
        right=0.98,
        top=0.885 if compact else 0.89,
        bottom=0.085,
        hspace=0.40 if compact else 0.36,
        wspace=0.48 if compact else 0.34,
    )
    risk_axis = figure.add_subplot(grid[0, :])
    bar_axis = figure.add_subplot(grid[1, 0])
    mismatch_axis = figure.add_subplot(grid[1, 1])
    dai_axis = figure.add_subplot(grid[1, 2])
    for axis in (risk_axis, bar_axis, mismatch_axis, dai_axis):
        _style_axis(axis, compact=compact)
    time_label = add_title_block(
        figure,
        title="Risk the Oracle Has Not Yet Seen",
        subtitle="Oracle delay under correlated crypto stress · 128-replication ensemble",
        compact=compact,
    )
    risk_axis.set_title(
        "Market-observed risk vs protocol recognition", loc="left", fontweight="bold"
    )
    risk_axis.set_ylabel("Unsafe debt share")
    risk_axis.set_xlabel("Simulation hour")
    risk_axis.set_xlim(hours[0], hours[-1])
    risk_axis.set_ylim(*limits.risk_share)
    add_shock_event(
        risk_axis,
        hour=REGISTERED_SHOCK_HOUR,
        label="Registered correlated crypto stress",
        compact=compact,
    )
    risk_axis.text(
        0.012,
        0.94,
        "Unsafe in the market, still safe to the protocol",
        transform=risk_axis.transAxes,
        ha="left",
        va="top",
        fontsize=7.5 if compact else 10.5,
        color="#7A3E00",
        bbox={"facecolor": "#FFF7E6", "edgecolor": "none", "alpha": 0.9, "pad": 4},
    )
    market = _series(frame, 0, "market_unsafe_debt_share")
    risk_lines: dict[int, Any] = {}
    (market_line,) = risk_axis.plot(
        [],
        [],
        color=MARKET_COLOR,
        linewidth=LINE_STRONG,
        label="Market unsafe (0h paired reference)",
    )
    for delay in DELAY_TO_TREATMENT:
        (risk_lines[delay],) = risk_axis.plot(
            [],
            [],
            color=COLORS[delay],
            linewidth=(
                LINE_REFERENCE
                if delay == 0
                else LINE_STANDARD
                if delay == 1
                else LINE_STRONG
            ),
            linestyle="--" if delay == 0 else "-",
            label=f"Oracle unsafe · {DELAY_LABELS[delay]}",
        )
    style_legend(
        risk_axis,
        compact=compact,
        loc="upper right",
        ncol=2,
        fontsize=6.0 if compact else 8.5,
    )
    risk_cursor = add_time_cursor(risk_axis, hours[0])
    shade_artists: list[Any] = []

    bar_axis.set_title("Current false-safe debt", loc="left", fontweight="bold")
    bar_axis.set_xlim(*limits.false_safe_debt)
    bar_axis.set_xlabel("DAI")
    bar_positions = np.arange(3)
    bars = bar_axis.barh(
        bar_positions,
        np.zeros(3),
        color=[COLORS[delay] for delay in DELAY_TO_TREATMENT],
        height=0.58,
    )
    bar_axis.set_yticks(
        bar_positions, [DELAY_LABELS[delay] for delay in DELAY_TO_TREATMENT]
    )
    bar_axis.invert_yaxis()
    bar_labels = [
        bar_axis.text(
            0.0,
            position,
            "0 DAI",
            va="center",
            ha="left",
            fontsize=7.5 if compact else 10,
            color="#17324D",
        )
        for position in bar_positions
    ]

    mismatch_axis.set_title(
        "Cumulative information mismatch", loc="left", fontweight="bold"
    )
    mismatch_axis.set_xlabel("Simulation hour")
    mismatch_axis.set_ylabel("Unsafe-debt share-hours")
    mismatch_axis.set_xlim(hours[0], hours[-1])
    mismatch_axis.set_ylim(*limits.mismatch)
    mismatch_lines: dict[int, Any] = {}
    for delay in DELAY_TO_TREATMENT:
        (mismatch_lines[delay],) = mismatch_axis.plot(
            [],
            [],
            color=COLORS[delay],
            linewidth=(
                LINE_REFERENCE
                if delay == 0
                else LINE_STANDARD
                if delay == 1
                else LINE_STRONG
            ),
            label=DELAY_LABELS[delay],
        )
    style_legend(
        mismatch_axis,
        compact=compact,
        loc="upper left",
        fontsize=6.0 if compact else 8.5,
    )
    mismatch_cursor = add_time_cursor(mismatch_axis, hours[0])

    dai_axis.set_title("DAI price", loc="left", fontweight="bold")
    dai_axis.set_xlabel("Simulation hour")
    dai_axis.set_ylabel("DAI / USD")
    dai_axis.set_xlim(hours[0], hours[-1])
    dai_axis.set_ylim(*limits.dai_price)
    add_peg_reference(dai_axis)
    dai_lines: dict[int, Any] = {}
    for delay in DELAY_TO_TREATMENT:
        (dai_lines[delay],) = dai_axis.plot(
            [],
            [],
            color=COLORS[delay],
            linewidth=(
                LINE_REFERENCE
                if delay == 0
                else LINE_STANDARD
                if delay == 1
                else LINE_STRONG
            ),
            label=DELAY_LABELS[delay],
        )
    style_legend(
        dai_axis,
        compact=compact,
        loc="lower right",
        fontsize=5.8 if compact else 7.5,
    )
    dai_cursor = add_time_cursor(dai_axis, hours[0])

    oracle = {
        delay: _series(frame, delay, "oracle_unsafe_debt_share")
        for delay in DELAY_TO_TREATMENT
    }
    treatment_market = {
        delay: _series(frame, delay, "market_unsafe_debt_share")
        for delay in DELAY_TO_TREATMENT
    }
    false_safe = {
        delay: _series(frame, delay, "false_safe_debt") for delay in DELAY_TO_TREATMENT
    }
    mismatch = {
        delay: _series(frame, delay, "cumulative_absolute_mismatch")
        for delay in DELAY_TO_TREATMENT
    }
    dai = {delay: _series(frame, delay, "dai_price") for delay in DELAY_TO_TREATMENT}

    def update(index: int) -> None:
        nonlocal shade_artists
        stop = index + 1
        current_hours = hours[:stop]
        market_line.set_data(current_hours, market[:stop])
        for artist in shade_artists:
            artist.remove()
        shade_artists = []
        for delay in (1, 2):
            shade_artists.append(
                risk_axis.fill_between(
                    current_hours,
                    treatment_market[delay][:stop],
                    oracle[delay][:stop],
                    where=treatment_market[delay][:stop] > oracle[delay][:stop],
                    color=COLORS[delay],
                    alpha=0.09,
                    linewidth=0.0,
                    zorder=1,
                )
            )
        for delay in DELAY_TO_TREATMENT:
            risk_lines[delay].set_data(current_hours, oracle[delay][:stop])
            mismatch_lines[delay].set_data(current_hours, mismatch[delay][:stop])
            dai_lines[delay].set_data(current_hours, dai[delay][:stop])
        current_values = np.array(
            [false_safe[delay][index] for delay in DELAY_TO_TREATMENT]
        )
        for bar, label, value in zip(bars, bar_labels, current_values, strict=True):
            bar.set_width(value)
            offset = limits.false_safe_debt[1] * 0.012
            if value > limits.false_safe_debt[1] * 0.82:
                label.set_x(value - offset)
                label.set_ha("right")
                label.set_color("white")
            else:
                label.set_x(value + offset)
                label.set_ha("left")
                label.set_color("#17324D")
            label.set_text(_format_dai(value))
        for cursor in (risk_cursor, mismatch_cursor, dai_cursor):
            cursor.set_xdata([hours[index], hours[index]])
        time_label.set_text(f"Hour {hours[index]:,.0f}")

    return figure, update


def _ffmpeg_executable() -> str | None:
    configured = os.environ.get("DAI_ANIMATION_FFMPEG")
    executable = Path(configured).expanduser() if configured else None
    if executable is not None:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return None
        matplotlib.rcParams["animation.ffmpeg_path"] = str(executable)
        command = str(executable)
    else:
        discovered = shutil.which("ffmpeg")
        if discovered is None:
            return None
        command = discovered
    try:
        subprocess.run([command, "-version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return str(Path(command).resolve())


def _ffmpeg_available() -> bool:
    return _ffmpeg_executable() is not None


def _tool_version(command: str) -> str:
    result = subprocess.run(
        [command, "-version"], check=True, capture_output=True, text=True
    )
    return result.stdout.splitlines()[0]


def _ffmpeg_details() -> dict[str, Any]:
    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required to render the H.264 animation.")
    sibling_probe = Path(ffmpeg).with_name("ffprobe")
    ffprobe = (
        str(sibling_probe.resolve())
        if sibling_probe.is_file() and os.access(sibling_probe, os.X_OK)
        else shutil.which("ffprobe")
    )
    if ffprobe is None:
        raise RuntimeError(
            "FFprobe is required to validate rendered animation metadata."
        )
    return {
        "available": True,
        "path": ffmpeg,
        "version": _tool_version(ffmpeg),
        "ffprobe_path": str(Path(ffprobe).resolve()),
        "ffprobe_version": _tool_version(ffprobe),
        "environment_override": os.environ.get("DAI_ANIMATION_FFMPEG"),
    }


def _rate(value: str) -> float:
    numerator, denominator = value.split("/", maxsplit=1)
    return float(numerator) / float(denominator)


def _probe_and_decode_video(
    destination: Path,
    settings: RenderSettings,
    expected_frames: int,
) -> dict[str, Any]:
    tools = _ffmpeg_details()
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError(f"Rendered video is missing or empty: {destination}")
    probe = subprocess.run(
        [
            tools["ffprobe_path"],
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            (
                "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,"
                "nb_frames,pix_fmt:format=duration,size,format_name"
            ),
            "-of",
            "json",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    streams = payload.get("streams", [])
    if len(streams) != 1:
        raise RuntimeError(f"Expected one readable video stream in {destination}.")
    stream = streams[0]
    metadata = {
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "frame_rate": stream.get("avg_frame_rate") or stream.get("r_frame_rate"),
        "frames": int(stream["nb_frames"]),
        "duration_seconds": float(payload["format"]["duration"]),
        "size_bytes": int(payload["format"]["size"]),
        "container": payload["format"].get("format_name"),
    }
    expected_duration = expected_frames / settings.fps
    failures = []
    if metadata["codec"] != "h264":
        failures.append(f"codec={metadata['codec']} (expected h264)")
    if (metadata["width"], metadata["height"]) != (
        settings.width,
        settings.height,
    ):
        failures.append(
            f"dimensions={metadata['width']}x{metadata['height']} "
            f"(expected {settings.width}x{settings.height})"
        )
    if abs(_rate(str(metadata["frame_rate"])) - settings.fps) > 1e-12:
        failures.append(
            f"frame_rate={metadata['frame_rate']} (expected {settings.fps}/1)"
        )
    if metadata["frames"] != expected_frames:
        failures.append(f"frames={metadata['frames']} (expected {expected_frames})")
    if abs(metadata["duration_seconds"] - expected_duration) > 1.0 / settings.fps:
        failures.append(
            f"duration={metadata['duration_seconds']} (expected {expected_duration})"
        )
    if failures:
        raise RuntimeError(
            f"Rendered video metadata validation failed for {destination}: "
            + "; ".join(failures)
        )
    decoded = subprocess.run(
        [
            tools["path"],
            "-v",
            "error",
            "-i",
            str(destination),
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
        raise RuntimeError(
            f"Rendered video did not decode through its final frame: {destination}: "
            f"{decoded.stderr.strip()}"
        )
    metadata["full_decode"] = "passed_through_final_frame"
    return metadata


def _render_video(
    frame: pd.DataFrame,
    destination: Path,
    settings: RenderSettings,
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing animation: {destination}"
        )
    if not _ffmpeg_available():
        raise RuntimeError("FFmpeg is required to render the H.264 animation.")
    hours = validate_frame_table(frame)
    limits = compute_axis_limits(frame)
    sequence = build_frame_sequence(hours, frame, settings)
    figure, update = _build_figure(frame, hours, limits, settings)

    def animate(position: int) -> None:
        update(position)

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
            "title": "Risk the Oracle Has Not Yet Seen",
            "artist": "DAI ABM dissertation reporting",
        },
    )
    animation.save(destination, writer=writer, dpi=settings.dpi)
    plt.close(figure)
    validation = _probe_and_decode_video(destination, settings, len(sequence))
    return {
        "path": destination,
        "settings": asdict(settings),
        "frame_count": len(sequence),
        "duration_seconds": len(sequence) / settings.fps,
        "first_hour": float(hours[sequence[0]]),
        "last_hour": float(hours[sequence[-1]]),
        "axis_limits": asdict(limits),
        "stress_interval": list(stress_interval(frame)),
        "codec_metadata": validation,
    }


def _render_static(
    frame: pd.DataFrame, destination: Path, settings: RenderSettings
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing static frame: {destination}"
        )
    hours = validate_frame_table(frame)
    by_hour = frame.groupby("hour", sort=True)["false_safe_debt"].max()
    representative_hour = float(by_hour.idxmax())
    index = int(np.flatnonzero(hours == representative_hour)[0])
    figure, update = _build_figure(frame, hours, compute_axis_limits(frame), settings)
    update(index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=settings.dpi, facecolor=figure.get_facecolor())
    plt.close(figure)
    return {"path": destination, "hour": representative_hour}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _versioned(path: Path, version_tag: str | None) -> Path:
    if version_tag is None:
        return path
    safe = "".join(
        character
        for character in version_tag
        if character.isalnum() or character in "-_"
    )
    if not safe or safe != version_tag:
        raise ValueError(
            "Version tag may contain only letters, numbers, hyphens and underscores."
        )
    return path.with_name(f"{path.stem}_{safe}{path.suffix}")


def _presentation_replacement_path(path: Path) -> Path:
    """Keep the temporary MP4 visible so macOS does not retain UF_HIDDEN."""
    return presentation_replacement_path(path)


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise FileExistsError(f"Refusing to overwrite temporary manifest: {temporary}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _resume_static(paths: Mapping[str, Path], frame_path: Path) -> dict[str, Any]:
    manifest_path = paths["manifest"]
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Resume requires the existing blocked manifest: {manifest_path}"
        )
    blocked = json.loads(manifest_path.read_text(encoding="utf-8"))
    if blocked.get("status") != "static_complete_video_blocked_ffmpeg_unavailable":
        raise ValueError(
            "Resume is permitted only for the validated FFmpeg-unavailable manifest."
        )
    rendering = blocked.get("rendering", {})
    expected_paths = {
        "preview": rendering.get("preview", {}).get("planned_path"),
        "video": rendering.get("final", {}).get("planned_path"),
        "static": rendering.get("static", {}).get("path"),
    }
    for label, expected in expected_paths.items():
        if expected != _relative(paths[label]):
            raise ValueError(
                f"Blocked manifest {label} path differs from the requested output."
            )
    for label in ("preview", "video"):
        if paths[label].exists():
            raise FileExistsError(
                f"Refusing to overwrite existing animation during resume: {paths[label]}"
            )
    static_path = paths["static"]
    static_record = rendering.get("static", {})
    if not static_path.is_file() or static_path.stat().st_size <= 0:
        raise FileNotFoundError(
            f"Validated representative static is missing: {static_path}"
        )
    if static_record.get("sha256") != sha256_file(static_path):
        raise ValueError(
            "Representative static checksum differs from the blocked manifest."
        )
    frame_checksum = sha256_file(frame_path)
    frame_records = [
        record
        for record in blocked.get("source_paths", [])
        if record.get("path") == _relative(frame_path)
    ]
    if len(frame_records) != 1 or frame_records[0].get("sha256") != frame_checksum:
        raise ValueError(
            "Validated frame table checksum differs from the blocked manifest."
        )
    return {
        "path": static_path,
        "hour": float(static_record["hour"]),
        "reused_from_validated_blocked_manifest": True,
    }


def _completed_render_for_replacement(
    paths: Mapping[str, Path], frame_path: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    manifest_path = paths["manifest"]
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Presentation replacement requires the completed manifest: {manifest_path}"
        )
    completed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if completed.get("status") != "complete":
        raise ValueError(
            "Presentation replacement requires a completed render manifest."
        )
    outputs = completed.get("outputs", [])
    expected = {_relative(paths[label]) for label in ("preview", "video", "static")}
    if {record.get("path") for record in outputs} != expected:
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
    frame_records = [
        record
        for record in completed.get("source_paths", [])
        if record.get("path") == _relative(frame_path)
    ]
    if len(frame_records) != 1 or frame_records[0].get("sha256") != sha256_file(
        frame_path
    ):
        raise ValueError("Validated frame table checksum differs before replacement.")
    static_record = completed["rendering"]["static"]
    return (
        {
            "path": paths["static"],
            "hour": float(static_record["hour"]),
            "reused_from_validated_completed_manifest": True,
        },
        outputs,
    )


def render_outputs(
    frame_path: Path = DEFAULT_FRAME_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    video_path: Path = DEFAULT_VIDEO_PATH,
    preview_path: Path = DEFAULT_PREVIEW_PATH,
    static_path: Path = DEFAULT_STATIC_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    version_tag: str | None = None,
    resume_blocked_render: bool = False,
    replace_completed_render: bool = False,
) -> Mapping[str, Path]:
    if (
        sum(
            option is not None and option is not False
            for option in (version_tag, resume_blocked_render, replace_completed_render)
        )
        > 1
    ):
        raise ValueError(
            "Versioning, blocked-render resume and completed-render replacement "
            "are mutually exclusive."
        )
    paths = {
        "video": _versioned(video_path, version_tag),
        "preview": _versioned(preview_path, version_tag),
        "static": _versioned(static_path, version_tag),
        "manifest": _versioned(manifest_path, version_tag),
    }
    ffmpeg_available = _ffmpeg_available()
    resumed_static: dict[str, Any] | None = None
    replaced_outputs: list[dict[str, str]] | None = None
    encode_paths = {
        "preview": paths["preview"],
        "static": paths["static"],
        "video": paths["video"],
    }
    if resume_blocked_render:
        if not ffmpeg_available:
            raise RuntimeError(
                "FFmpeg is unavailable; the blocked render cannot resume."
            )
        resumed_static = _resume_static(paths, frame_path)
    elif replace_completed_render:
        if not ffmpeg_available:
            raise RuntimeError(
                "FFmpeg is unavailable; presentation replacement failed."
            )
        resumed_static, replaced_outputs = _completed_render_for_replacement(
            paths, frame_path
        )
        encode_paths = {
            label: _presentation_replacement_path(paths[label])
            for label in ("preview", "video")
        }
        temporary_conflicts = [path for path in encode_paths.values() if path.exists()]
        if temporary_conflicts:
            raise FileExistsError(
                f"Refusing to overwrite temporary render artefacts: {temporary_conflicts}"
            )
    else:
        conflict_candidates = (
            paths.values() if ffmpeg_available else (paths["manifest"],)
        )
        conflicts = [path for path in conflict_candidates if path.exists()]
        if conflicts:
            raise FileExistsError(
                f"Refusing to overwrite existing final reporting artefacts: {conflicts}"
            )
    frame = pd.read_csv(frame_path)
    hours = validate_frame_table(frame)
    extraction = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not ffmpeg_available:
        final_settings = RenderSettings()
        if paths["static"].exists():
            by_hour = frame.groupby("hour", sort=True)["false_safe_debt"].max()
            static = {"path": paths["static"], "hour": float(by_hour.idxmax())}
        else:
            static = _render_static(frame, paths["static"], final_settings)
        sequence = build_frame_sequence(hours, frame, final_settings)
        manifest = {
            "schema_version": 1,
            "producer": "workflows.experiments.final.render_oracle_delay_animation",
            "status": "static_complete_video_blocked_ffmpeg_unavailable",
            "title": "Risk the Oracle Has Not Yet Seen",
            "subtitle": "Oracle delay under correlated crypto stress",
            "experiment_id": extraction["experiment_id"],
            "experiment_identity": extraction["experiment_identity"],
            "anchor": extraction["anchor"],
            "treatments": extraction["treatments"],
            "replication_count": extraction["aggregation"]["replication_count"],
            "time_range": extraction["time_range"],
            "timestep_hours": extraction["timestep_hours"],
            "aggregation": extraction["aggregation"],
            "derived_metrics": extraction["derived_metrics"],
            "reconciliation": extraction["reconciliation"],
            "reporting_replay": extraction.get("reporting_replay"),
            "registered_peg_band": list(PEG_BAND),
            "final_interpretation": (
                "Oracle delay increases information mismatch and false-safe debt. "
                "The downstream DAI path remains largely unchanged. H2 is partially "
                "supported."
            ),
            "source_paths": extraction["source_paths"]
            + [
                {"path": _relative(frame_path), "sha256": sha256_file(frame_path)},
                {
                    "path": _relative(PEG_BAND_SOURCE),
                    "sha256": sha256_file(PEG_BAND_SOURCE),
                },
            ],
            "rendering": {
                "ffmpeg": {
                    "available": False,
                    "required": (
                        "Install an ffmpeg executable on PATH or set "
                        "DAI_ANIMATION_FFMPEG=/absolute/path/to/ffmpeg."
                    ),
                },
                "preview": {
                    "status": "blocked_ffmpeg_unavailable",
                    "planned_path": _relative(paths["preview"]),
                },
                "final": {
                    "status": "blocked_ffmpeg_unavailable",
                    "planned_path": _relative(paths["video"]),
                    "settings": asdict(final_settings),
                    "planned_frame_count": len(sequence),
                    "planned_duration_seconds": len(sequence) / final_settings.fps,
                    "axis_limits": asdict(compute_axis_limits(frame)),
                    "stress_interval": list(stress_interval(frame)),
                },
                "static": {
                    **static,
                    "path": _relative(static["path"]),
                    "sha256": sha256_file(static["path"]),
                },
                "uncertainty_displayed": False,
                "uncertainty_reason": (
                    "Pointwise intervals were retained in frame data but omitted "
                    "to keep four panels legible."
                ),
                "market_line_definition": "0-hour paired-reference ensemble mean",
                "shading_definition": (
                    "treatment-specific market unsafe debt exceeds oracle unsafe debt"
                ),
                "shared_presentation_style": {
                    "path": _relative(PRESENTATION_STYLE_PATH),
                    "sha256": sha256_file(PRESENTATION_STYLE_PATH),
                },
            },
            "outputs": [
                {
                    "path": _relative(paths["static"]),
                    "sha256": sha256_file(paths["static"]),
                }
            ],
            "git_commit": _git_commit(),
        }
        paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
        _write_manifest(paths["manifest"], manifest)
        return {"static": paths["static"], "manifest": paths["manifest"]}
    preview_settings = RenderSettings(
        fps=10,
        width=960,
        height=540,
        dpi=100,
        bitrate_kbps=1800,
        opening_hold_seconds=0.5,
        final_hold_seconds=1.0,
        progression_frames=70,
    )
    preview = _render_video(frame, encode_paths["preview"], preview_settings)
    final_settings = RenderSettings()
    static = resumed_static or _render_static(
        frame, encode_paths["static"], final_settings
    )
    final = _render_video(frame, encode_paths["video"], final_settings)
    if replace_completed_render:
        for label in ("preview", "video"):
            encode_paths[label].replace(paths[label])
        preview["path"] = paths["preview"]
        final["path"] = paths["video"]
    ffmpeg = _ffmpeg_details()
    manifest = {
        "schema_version": 1,
        "producer": "workflows.experiments.final.render_oracle_delay_animation",
        "status": "complete",
        "title": "Risk the Oracle Has Not Yet Seen",
        "subtitle": "Oracle delay under correlated crypto stress",
        "experiment_id": extraction["experiment_id"],
        "experiment_identity": extraction["experiment_identity"],
        "anchor": extraction["anchor"],
        "treatments": extraction["treatments"],
        "replication_count": extraction["aggregation"]["replication_count"],
        "time_range": extraction["time_range"],
        "timestep_hours": extraction["timestep_hours"],
        "aggregation": extraction["aggregation"],
        "derived_metrics": extraction["derived_metrics"],
        "reconciliation": extraction["reconciliation"],
        "reporting_replay": extraction.get("reporting_replay"),
        "registered_peg_band": list(PEG_BAND),
        "final_interpretation": (
            "Oracle delay increases information mismatch and false-safe debt. The "
            "downstream DAI path remains largely unchanged. H2 is partially supported."
        ),
        "source_paths": extraction["source_paths"]
        + [
            {"path": _relative(frame_path), "sha256": sha256_file(frame_path)},
            {
                "path": _relative(PEG_BAND_SOURCE),
                "sha256": sha256_file(PEG_BAND_SOURCE),
            },
        ],
        "rendering": {
            "command": shlex.join(
                [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
            ),
            "ffmpeg": ffmpeg,
            "presentation_replacement": (
                {
                    "reason": "remove in-video final interpretation card",
                    "prior_outputs": replaced_outputs,
                }
                if replaced_outputs is not None
                else None
            ),
            "preview": {**preview, "path": _relative(preview["path"])},
            "final": {**final, "path": _relative(final["path"])},
            "static": {**static, "path": _relative(static["path"])},
            "uncertainty_displayed": False,
            "uncertainty_reason": "Pointwise intervals were retained in frame data but omitted to keep four panels legible.",
            "market_line_definition": "0-hour paired-reference ensemble mean",
            "shading_definition": "treatment-specific market unsafe debt exceeds oracle unsafe debt",
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
            "treatment_encoding": {
                str(delay): {
                    "label": DELAY_LABELS[delay],
                    "color": COLORS[delay],
                    "visual_strength": (
                        "reference"
                        if delay == 0
                        else "intermediate"
                        if delay == 1
                        else "strongest"
                    ),
                }
                for delay in DELAY_TO_TREATMENT
            },
        },
        "outputs": [
            {"path": _relative(path), "sha256": sha256_file(path)}
            for path in (paths["preview"], paths["video"], paths["static"])
        ],
        "git_commit": _git_commit(),
    }
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    _write_manifest(paths["manifest"], manifest)
    return paths


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, default=DEFAULT_FRAME_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO_PATH)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--version-tag")
    parser.add_argument(
        "--resume-blocked-render",
        action="store_true",
        help=(
            "Resume only an exact validated FFmpeg-unavailable manifest, reusing "
            "its representative static without weakening overwrite protection."
        ),
    )
    parser.add_argument(
        "--replace-completed-render",
        action="store_true",
        help=(
            "Checksum-gated presentation rerender of a completed animation; encode "
            "to temporary files and promote them only after validation."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        outputs = render_outputs(
            frame_path=args.frames,
            metadata_path=args.metadata,
            video_path=args.video,
            preview_path=args.preview,
            static_path=args.static,
            manifest_path=args.manifest,
            version_tag=args.version_tag,
            resume_blocked_render=args.resume_blocked_render,
            replace_completed_render=args.replace_completed_render,
        )
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
