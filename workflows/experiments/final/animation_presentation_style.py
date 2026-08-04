"""Shared presentation-only style for the dissertation animation series."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure


FONT_FAMILY = "DejaVu Sans"
FIGURE_BACKGROUND = "#F7F8FA"
AXES_BACKGROUND = "#FFFFFF"
PRIMARY_TEXT = "#102A43"
SECONDARY_TEXT = "#52667A"
AXIS_TEXT = "#34495E"
GRID_COLOR = "#D9DEE5"
CURSOR_COLOR = "#64748B"
SHOCK_COLOR = "#8B4513"
SHOCK_BOX_FACE = "#FFF7E6"
PEG_BAND = (0.995, 1.005)
PEG_BAND_COLOR = "#DDEFE1"
PEG_REFERENCE_COLOR = "#52667A"
LINE_REFERENCE = 1.6
LINE_STANDARD = 1.9
LINE_STRONG = 2.3


def configure_matplotlib(*, compact: bool) -> None:
    """Apply the shared font hierarchy without changing scientific geometry."""
    plt.rcParams.update(
        {
            "font.family": FONT_FAMILY,
            "axes.titlesize": 8.5 if compact else 11.5,
            "axes.labelsize": 7.0 if compact else 9.5,
            "figure.facecolor": FIGURE_BACKGROUND,
            "axes.facecolor": AXES_BACKGROUND,
        }
    )


def style_axis(axis: Axes, *, compact: bool) -> None:
    axis.grid(axis="y", color=GRID_COLOR, linewidth=0.65, alpha=0.72)
    axis.spines[["top", "right"]].set_visible(False)
    axis.tick_params(colors=AXIS_TEXT, labelsize=6.5 if compact else 9.0)
    axis.title.set_color(PRIMARY_TEXT)


def add_title_block(
    figure: Figure,
    *,
    title: str,
    subtitle: str,
    compact: bool,
) -> Any:
    figure.suptitle(
        title,
        x=0.06,
        y=0.972,
        ha="left",
        fontsize=15 if compact else 23,
        fontweight="bold",
        color=PRIMARY_TEXT,
    )
    figure.text(
        0.06,
        0.93,
        subtitle,
        ha="left",
        va="center",
        fontsize=7.5 if compact else 11,
        color=SECONDARY_TEXT,
    )
    return figure.text(
        0.98,
        0.962,
        "",
        ha="right",
        va="top",
        fontsize=9 if compact else 13,
        fontweight="bold",
        color="#17324D",
    )


def add_time_cursor(axis: Axes, hour: float) -> Any:
    return axis.axvline(
        hour,
        color=CURSOR_COLOR,
        linewidth=1.0,
        alpha=0.82,
        zorder=12,
    )


def add_shock_event(
    axis: Axes,
    *,
    hour: float,
    label: str,
    compact: bool,
    label_y: float = 0.055,
) -> None:
    axis.axvline(
        hour,
        color=SHOCK_COLOR,
        linestyle=":",
        linewidth=1.2,
        alpha=0.9,
        zorder=10,
    )
    axis.text(
        hour + 6,
        label_y,
        label,
        transform=axis.get_xaxis_transform(),
        ha="left",
        va="bottom",
        fontsize=6.5 if compact else 9,
        color="#7A3E00",
        bbox={
            "facecolor": SHOCK_BOX_FACE,
            "edgecolor": "none",
            "alpha": 0.92,
            "pad": 3,
        },
        zorder=11,
    )


def add_peg_reference(axis: Axes) -> None:
    axis.axhspan(
        *PEG_BAND,
        color=PEG_BAND_COLOR,
        alpha=0.55,
        label="Registered peg band",
    )
    axis.axhline(
        1.0,
        color=PEG_REFERENCE_COLOR,
        linewidth=1.0,
        linestyle=":",
        label="1.00",
    )


def style_legend(
    axis: Axes,
    *,
    compact: bool,
    loc: str,
    ncol: int = 1,
    fontsize: float | None = None,
) -> Any:
    return axis.legend(
        loc=loc,
        ncol=ncol,
        frameon=compact,
        framealpha=0.88 if compact else None,
        facecolor=AXES_BACKGROUND if compact else None,
        edgecolor="none" if compact else None,
        fontsize=fontsize if fontsize is not None else (6.0 if compact else 8.5),
        borderaxespad=0.5,
        handlelength=2.2,
        labelspacing=0.35,
        columnspacing=1.0,
    )


def presentation_replacement_path(path: Path) -> Path:
    """Return a visible non-dot temporary sibling for checksum-gated promotion."""
    return path.with_name(f"{path.stem}.presentation-replacement{path.suffix}")
