"""Portable ownership of the accepted Stage 1 residual process."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from dai_sim.calibration.market import ResidualBlockSource
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file


RESIDUAL_PATH: Final = (
    REPOSITORY_ROOT
    / "data/model_inputs/calibration/stage1_residual_source.csv"
)
MANIFEST_PATH: Final = RESIDUAL_PATH.with_suffix(".manifest.json")


def load_portable_stage1_residual_source(
    path: Path = RESIDUAL_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[ResidualBlockSource, dict[str, Any]]:
    """Load and verify the exact accepted residual sequence and block owner."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("classification") != "portable_stage1_residual_source_v1":
        raise ValueError("Portable Stage 1 residual classification differs.")
    if sha256_file(path) != manifest.get("derivative_sha256"):
        raise ValueError("Portable Stage 1 residual checksum differs.")
    frame = pd.read_csv(path, dtype={"centred_residual_float64_hex": str})
    required = [
        "residual_index", "run_id", "run_position", "timestamp_utc",
        "centred_residual_float64_hex",
    ]
    if list(frame.columns) != required or len(frame) != manifest.get("row_count"):
        raise ValueError("Portable Stage 1 residual schema or rows differ.")
    if frame["residual_index"].tolist() != list(range(len(frame))):
        raise ValueError("Portable Stage 1 residual indices are not contiguous.")
    timestamps = tuple(
        pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    )
    residuals = np.asarray(
        [float.fromhex(value) for value in frame["centred_residual_float64_hex"]],
        dtype="<f8",
    )
    run_lengths = tuple(int(value) for value in manifest["run_lengths"])
    if sum(run_lengths) != len(frame):
        raise ValueError("Portable Stage 1 run lengths differ.")
    block_indices: list[tuple[int, ...]] = []
    offset = 0
    for run_id, run_length in enumerate(run_lengths):
        observed = frame.loc[
            frame["run_id"].eq(run_id), "run_position"
        ].tolist()
        if observed != list(range(run_length)):
            raise ValueError("Portable Stage 1 run ownership differs.")
        for start in range(max(0, run_length - 24 + 1)):
            block_indices.append(tuple(range(offset + start, offset + start + 24)))
        offset += run_length
    residual_hash = sha256(residuals.tobytes()).hexdigest()
    block_hash = sha256(
        json.dumps(tuple(block_indices), separators=(",", ":")).encode()
    ).hexdigest()
    if residual_hash != manifest.get("centred_residual_sequence_sha256"):
        raise ValueError("Portable Stage 1 residual values differ.")
    if block_hash != manifest.get("block_index_specification_sha256"):
        raise ValueError("Portable Stage 1 block indices differ.")
    source = ResidualBlockSource(
        timestamps=timestamps,
        centred_residuals=residuals,
        block_indices=tuple(block_indices),
        run_lengths=run_lengths,
        mean_before_centring=float.fromhex(
            manifest["mean_before_centring_float64_hex"]
        ),
    )
    return source, manifest

