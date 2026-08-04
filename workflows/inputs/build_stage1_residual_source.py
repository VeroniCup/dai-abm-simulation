"""Build the exact portable Stage 1 residual source from full evidence.

This optional local workflow never estimates coefficients. It applies the
already accepted coefficients to the verified historical panel and serialises
the resulting residual source without rounding.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from dai_sim.calibration.event_simulation import (
    EXPECTED_RESIDUAL_BLOCK_SHA256,
    EXPECTED_RESIDUAL_SEQUENCE_SHA256,
)
from dai_sim.calibration.market import (
    CONFIDENCE_EVIDENCE,
    CONFIDENCE_PANEL,
    CONFIDENCE_PANEL_SHA256,
    build_residual_block_source,
    load_confidence_panel,
    ordinary_confidence_sample,
)
from dai_sim.calibration.simulated_moments import build_event_catalogue
from dai_sim.inputs.configuration import REPOSITORY_ROOT


DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "data/model_inputs/calibration/stage1_residual_source.csv"
)
DEFAULT_MANIFEST = DEFAULT_OUTPUT.with_suffix(".manifest.json")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.",
        suffix=".partial", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build(output: Path = DEFAULT_OUTPUT, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    """Build and validate the content-addressed residual derivative."""
    if _sha256_file(CONFIDENCE_PANEL) != CONFIDENCE_PANEL_SHA256:
        raise ValueError("Canonical Stage 1 panel checksum differs.")
    stage1 = json.loads(
        (CONFIDENCE_EVIDENCE / "stage1_market_estimates.json").read_text()
    )
    panel = load_confidence_panel(CONFIDENCE_PANEL)
    events = build_event_catalogue(panel)
    hourly = ordinary_confidence_sample(
        panel, events, daily=False, require_lagged_eth=False
    )
    source = build_residual_block_source(
        hourly,
        below_peg_response=float(stage1["below_peg_response"]["point_estimate"]),
        above_peg_response=float(stage1["above_peg_response"]["point_estimate"]),
    )
    residual_hash = sha256(
        np.asarray(source.centred_residuals, dtype="<f8").tobytes()
    ).hexdigest()
    block_hash = sha256(
        json.dumps(source.block_indices, separators=(",", ":")).encode()
    ).hexdigest()
    if residual_hash != EXPECTED_RESIDUAL_SEQUENCE_SHA256:
        raise ValueError("Residual sequence differs from frozen evidence.")
    if block_hash != EXPECTED_RESIDUAL_BLOCK_SHA256:
        raise ValueError("Residual block ownership differs from frozen evidence.")

    rows: list[list[str]] = []
    offset = 0
    run_id = 0
    for run_length in source.run_lengths:
        for position in range(run_length):
            index = offset + position
            rows.append([
                str(index),
                str(run_id),
                str(position),
                source.timestamps[index].isoformat().replace("+00:00", "Z"),
                float(source.centred_residuals[index]).hex(),
            ])
        offset += run_length
        run_id += 1
    buffer = __import__("io").StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "residual_index", "run_id", "run_position", "timestamp_utc",
        "centred_residual_float64_hex",
    ])
    writer.writerows(rows)
    _atomic_write(output, buffer.getvalue().encode("utf-8"))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "classification": "portable_stage1_residual_source_v1",
        "historical_source_path": CONFIDENCE_PANEL.relative_to(REPOSITORY_ROOT).as_posix(),
        "historical_source_sha256": CONFIDENCE_PANEL_SHA256,
        "derivative_path": output.relative_to(REPOSITORY_ROOT).as_posix(),
        "derivative_sha256": _sha256_file(output),
        "row_count": len(rows),
        "column_count": 5,
        "columns": [
            "residual_index", "run_id", "run_position", "timestamp_utc",
            "centred_residual_float64_hex",
        ],
        "centred_residual_sequence_sha256": residual_hash,
        "block_index_specification_sha256": block_hash,
        "run_lengths": list(source.run_lengths),
        "mean_before_centring_float64_hex": float(source.mean_before_centring).hex(),
        "below_peg_response_float64_hex": float(
            stage1["below_peg_response"]["point_estimate"]
        ).hex(),
        "above_peg_response_float64_hex": float(
            stage1["above_peg_response"]["point_estimate"]
        ).hex(),
        "network_calls": 0,
        "scientific_value_changes": 0,
    }
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
