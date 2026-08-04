"""Build the side-by-side visual-QA sheet for the dissertation animations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file  # noqa: E402
from workflows.experiments.final.animation_presentation_style import (  # noqa: E402
    FIGURE_BACKGROUND,
    FONT_FAMILY,
    PRIMARY_TEXT,
    SECONDARY_TEXT,
    presentation_replacement_path,
)
from workflows.experiments.final import (  # noqa: E402
    render_balance_sheet_animation as balance,
)
from workflows.experiments.final import (  # noqa: E402
    render_oracle_delay_animation as oracle,
)


OUTPUT_DIR = REPOSITORY_ROOT / "outputs/reporting/final/animations"
DEFAULT_OUTPUT_PATH = OUTPUT_DIR / "animation_series_contact_sheet.png"


def _load_completed_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text())
    if manifest.get("status") != "complete":
        raise ValueError(f"Animation manifest is not complete: {path}")
    for record in manifest.get("outputs", []):
        output = REPOSITORY_ROOT / record["path"]
        if not output.is_file() or sha256_file(output) != record.get("sha256"):
            raise ValueError(f"Manifest output checksum differs: {output}")
    return manifest


def _settings(cls: type[Any], record: Mapping[str, Any]) -> Any:
    return cls(**record["settings"])


def _frame_for_hour(
    sequence: list[int], hours: np.ndarray, hour: int, *, label: str
) -> int:
    sequence_hours = hours[np.asarray(sequence, dtype=int)]
    positions = np.flatnonzero(sequence_hours == hour)
    if not len(positions):
        raise ValueError(f"{label} hour {hour} is absent from the video sequence.")
    return int(positions[0])


def _oracle_review_frames(
    manifest: Mapping[str, Any], frame: pd.DataFrame
) -> list[dict[str, Any]]:
    hours = oracle.validate_frame_table(frame)
    settings = _settings(oracle.RenderSettings, manifest["rendering"]["final"])
    sequence = oracle.build_frame_sequence(hours, frame, settings)
    mechanism_hour = int(
        frame.groupby("hour", sort=True)["false_safe_debt"].max().idxmax()
    )
    return [
        {"label": "Opening", "hour": int(hours[0]), "frame": 0},
        {
            "label": "Primary stress",
            "hour": oracle.REGISTERED_SHOCK_HOUR,
            "frame": _frame_for_hour(
                sequence,
                hours,
                oracle.REGISTERED_SHOCK_HOUR,
                label="Oracle registered shock",
            ),
        },
        {
            "label": "Maximum mechanism",
            "hour": mechanism_hour,
            "frame": _frame_for_hour(
                sequence,
                hours,
                mechanism_hour,
                label="Oracle maximum false-safe debt",
            ),
        },
        {
            "label": "Clean final hold",
            "hour": int(hours[-1]),
            "frame": len(sequence) - 1,
        },
    ]


def _balance_review_frames(
    manifest: Mapping[str, Any], system: pd.DataFrame, vault: pd.DataFrame
) -> list[dict[str, Any]]:
    hours = np.arange(balance.experiment.TOTAL_HOURS, dtype=float)
    settings = _settings(balance.RenderSettings, manifest["rendering"]["final"])
    sequence = balance.build_frame_sequence(hours, system, settings)
    distress = vault.loc[vault["canonical_vault_state"].eq("liquidatable_unresolved")]
    mechanism_hour = int(
        distress.groupby(["treatment", "hour"], sort=True).size().idxmax()[1]
    )
    return [
        {"label": "Opening", "hour": int(hours[0]), "frame": 0},
        {
            "label": "Primary stress",
            "hour": balance.experiment.PRE_SHOCK_HOURS,
            "frame": _frame_for_hour(
                sequence,
                hours,
                balance.experiment.PRE_SHOCK_HOURS,
                label="Balance-sheet registered shock",
            ),
        },
        {
            "label": "Maximum mechanism",
            "hour": mechanism_hour,
            "frame": _frame_for_hour(
                sequence,
                hours,
                mechanism_hour,
                label="Balance-sheet maximum illustrative vault distress",
            ),
        },
        {
            "label": "Clean final hold",
            "hour": int(hours[-1]),
            "frame": len(sequence) - 1,
        },
    ]


def _ffmpeg() -> str:
    configured = os.environ.get("DAI_ANIMATION_FFMPEG")
    command = configured or shutil.which("ffmpeg")
    if command is None:
        raise RuntimeError("FFmpeg is required to extract contact-sheet frames.")
    path = Path(command).expanduser()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"FFmpeg is not executable: {path}")
    return str(path.resolve())


def _extract_frame(ffmpeg: str, video: Path, frame: int, output: Path) -> None:
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"select=eq(n\\,{frame})",
            "-frames:v",
            "1",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(
            f"Failed to extract frame {frame} from {video}: {result.stderr.strip()}"
        )


def build_contact_sheet(
    output_path: Path = DEFAULT_OUTPUT_PATH, *, replace_existing: bool = False
) -> Path:
    if replace_existing:
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise FileNotFoundError(
                f"Contact-sheet replacement requires the existing output: {output_path}"
            )
        destination = presentation_replacement_path(output_path)
        if destination.exists():
            raise FileExistsError(
                f"Refusing to overwrite temporary contact sheet: {destination}"
            )
    else:
        destination = output_path
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite contact sheet: {destination}")
    oracle_manifest = _load_completed_manifest(oracle.DEFAULT_MANIFEST_PATH)
    balance_manifest = _load_completed_manifest(balance.DEFAULT_MANIFEST_PATH)
    if int(oracle_manifest["replication_count"]) != 128:
        raise ValueError("Oracle animation does not report all 128 replications.")
    if int(balance_manifest["replication_count"]) != 128:
        raise ValueError(
            "Balance-sheet animation does not report all 128 replications."
        )
    if int(balance_manifest["representative_replication"]) != 4:
        raise ValueError("Balance-sheet representative replication is no longer 4.")

    oracle_frame = pd.read_csv(oracle.DEFAULT_FRAME_PATH)
    balance_system = pd.read_csv(balance.DEFAULT_SYSTEM_PATH)
    balance_vault = pd.read_csv(
        balance.DEFAULT_VAULT_PATH,
        usecols=["hour", "treatment", "canonical_vault_state"],
    )
    review = [
        (
            "Experiment E · Oracle delay",
            oracle.DEFAULT_VIDEO_PATH,
            _oracle_review_frames(oracle_manifest, oracle_frame),
        ),
        (
            "Experiment A · Balance sheets",
            balance.DEFAULT_VIDEO_PATH,
            _balance_review_frames(balance_manifest, balance_system, balance_vault),
        ),
    ]
    ffmpeg = _ffmpeg()
    with tempfile.TemporaryDirectory(prefix="dai-animation-series-") as temporary:
        temporary_path = Path(temporary)
        images: list[list[np.ndarray]] = []
        for row_index, (_, video, frames) in enumerate(review):
            row = []
            for column_index, record in enumerate(frames):
                image_path = temporary_path / f"{row_index}-{column_index}.png"
                _extract_frame(ffmpeg, video, int(record["frame"]), image_path)
                row.append(mpimg.imread(image_path))
            images.append(row)

    plt.rcParams.update({"font.family": FONT_FAMILY})
    figure, axes = plt.subplots(
        2,
        4,
        figsize=(19.2, 6.55),
        dpi=200,
        facecolor=FIGURE_BACKGROUND,
    )
    figure.subplots_adjust(
        left=0.075, right=0.995, top=0.89, bottom=0.035, wspace=0.035, hspace=0.23
    )
    figure.suptitle(
        "Dissertation animation series · visual QA",
        x=0.075,
        y=0.975,
        ha="left",
        fontsize=17,
        fontweight="bold",
        color=PRIMARY_TEXT,
    )
    for row_index, (row_label, _, frames) in enumerate(review):
        figure.text(
            0.012,
            0.665 if row_index == 0 else 0.255,
            row_label,
            ha="left",
            va="center",
            rotation=90,
            fontsize=11,
            fontweight="bold",
            color=PRIMARY_TEXT,
        )
        for column_index, record in enumerate(frames):
            axis = axes[row_index, column_index]
            axis.imshow(images[row_index][column_index])
            axis.set_axis_off()
            axis.set_title(
                f"{record['label']} · hour {record['hour']}",
                loc="left",
                fontsize=9.5,
                fontweight="bold",
                color=PRIMARY_TEXT,
                pad=5,
            )
            axis.text(
                0.995,
                -0.035,
                f"video frame {record['frame']}",
                transform=axis.transAxes,
                ha="right",
                va="top",
                fontsize=7,
                color=SECONDARY_TEXT,
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=200, facecolor=figure.get_facecolor())
    plt.close(figure)
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError(f"Contact sheet was not created: {destination}")
    if replace_existing:
        destination.replace(output_path)
    print(f"contact_sheet: {output_path}")
    print(f"sha256: {sha256_file(output_path)}")
    for row_label, _, frames in review:
        print(f"{row_label}: {frames}")
    return output_path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--replace-existing", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build_contact_sheet(args.output, replace_existing=args.replace_existing)
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
