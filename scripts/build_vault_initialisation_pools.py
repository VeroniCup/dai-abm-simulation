"""
Build compact Tranche B vault initialisation pools from validated openings.

The script keeps runtime sampling independent of the large reconstructed vault
datasets. It preserves only paired debt/collateral-ratio observations and
minimal provenance needed for distribution-aware initialisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import hashlib
import json

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT / "config" / "empirical" / "data" / "vault_initialisation_pools.csv"
)
DEFAULT_METADATA = (
    REPOSITORY_ROOT
    / "config"
    / "empirical"
    / "data"
    / "vault_initialisation_pools_manifest.json"
)
DEFAULT_AUDIT = (
    REPOSITORY_ROOT
    / "data"
    / "processed"
    / "estimation"
    / "tranche_b"
    / "vault_initialisation_pool_audit.csv"
)


@dataclass(frozen=True)
class PoolSource:
    """One validated representative-regime opening-state source."""

    window: str
    regime_label: str
    source_window: str
    path: Path
    sha256: str


POOL_SOURCES = (
    PoolSource(
        window="quiet_mature",
        regime_label="normal",
        source_window="quiet_mature_2024-02-01_2024-03-01",
        path=(
            REPOSITORY_ROOT
            / "data/processed/vaults/representative_regimes/"
            / "quiet_mature_2024-02-01_2024-03-01/opening_vault_state.csv"
        ),
        sha256="5bb240cfa175339887c9e4254bc5edcdca469f349baa35bc5da43e1514f42ebe",
    ),
    PoolSource(
        window="usdc_svb",
        regime_label="moderate_stress",
        source_window="usdc_svb_2023-03-06_2023-03-20",
        path=(
            REPOSITORY_ROOT
            / "data/processed/vaults/representative_regimes/"
            / "usdc_svb_2023-03-06_2023-03-20/opening_vault_state.csv"
        ),
        sha256="35e34954d2916b4829798547bc7a62e249329777fe961719421567d24ce67bac",
    ),
    PoolSource(
        window="terra_cefi",
        regime_label="severe_stress",
        source_window="terra_cefi_2022-05-05_2022-06-20",
        path=(
            REPOSITORY_ROOT
            / "data/processed/vaults/representative_regimes/"
            / "terra_cefi_2022-05-05_2022-06-20/opening_vault_state.csv"
        ),
        sha256="d0a956716525e9db0493e30f91e2d66ee39147c40ccd1abcfac3c33086993c2f",
    ),
)

OUTPUT_COLUMNS = (
    "pool_row_id",
    "source_window",
    "regime_label",
    "state_label",
    "timestamp_utc",
    "ilk",
    "collateral_family",
    "debt_dai",
    "collateral_ratio",
    "liquidation_ratio",
    "absolute_buffer",
    "relative_buffer",
)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collateral_family_from_ilk(ilk: str) -> str:
    """Map exact Maker ilk to the implemented collateral family."""
    prefix = str(ilk).split("-", maxsplit=1)[0].upper()
    if prefix == "WBTC":
        return "WBTC"
    if prefix == "ETH":
        return "ETH"
    raise ValueError(f"Unsupported ilk for Tranche B pool: {ilk}.")


def _load_source(source: PoolSource) -> pd.DataFrame:
    observed = sha256_file(source.path)
    if observed != source.sha256:
        raise ValueError(
            f"Checksum mismatch for {source.path}: "
            f"expected {source.sha256}, observed {observed}."
        )
    frame = pd.read_csv(source.path)
    required = {
        "window",
        "state_label",
        "timestamp_utc",
        "ilk",
        "debt_dai",
        "collateral_ratio",
        "liquidation_ratio",
        "active",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{source.path} missing required columns: {sorted(missing)}")
    frame["source_window"] = source.source_window
    frame["regime_label"] = source.regime_label
    return frame


def build_pool(sources: tuple[PoolSource, ...] = POOL_SOURCES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the compact pool and exclusion audit."""
    pool_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, object]] = []

    for source in sources:
        frame = _load_source(source)
        work = frame.copy()
        work["debt_dai_numeric"] = pd.to_numeric(work["debt_dai"], errors="coerce")
        work["collateral_ratio_numeric"] = pd.to_numeric(
            work["collateral_ratio"], errors="coerce"
        )
        work["liquidation_ratio_numeric"] = pd.to_numeric(
            work["liquidation_ratio"], errors="coerce"
        )
        active = work["active"].astype(str).str.lower().eq("true")
        valid = (
            active
            & work["debt_dai_numeric"].gt(0)
            & work["collateral_ratio_numeric"].notna()
            & work["liquidation_ratio_numeric"].gt(1)
        )
        reasons = {
            "inactive": int((~active).sum()),
            "non_positive_debt": int((active & ~work["debt_dai_numeric"].gt(0)).sum()),
            "missing_collateral_ratio": int(
                (active & work["collateral_ratio_numeric"].isna()).sum()
            ),
            "invalid_liquidation_ratio": int(
                (active & ~work["liquidation_ratio_numeric"].gt(1)).sum()
            ),
        }
        audit_rows.append(
            {
                "source_window": source.source_window,
                "source_rows": len(work),
                "included_rows": int(valid.sum()),
                **reasons,
                "source_sha256": source.sha256,
            }
        )

        selected = work.loc[valid].copy()
        selected["collateral_family"] = selected["ilk"].map(collateral_family_from_ilk)
        selected["absolute_buffer"] = (
            selected["collateral_ratio_numeric"]
            - selected["liquidation_ratio_numeric"]
        )
        selected["relative_buffer"] = (
            selected["collateral_ratio_numeric"]
            / selected["liquidation_ratio_numeric"]
            - 1.0
        )
        if (selected["absolute_buffer"] < 0).any():
            raise ValueError(f"{source.source_window} contains initially liquidatable rows.")

        pool_frames.append(
            selected.assign(
                state_label="opening",
                debt_dai=selected["debt_dai_numeric"],
                collateral_ratio=selected["collateral_ratio_numeric"],
                liquidation_ratio=selected["liquidation_ratio_numeric"],
            )[
                [
                    "source_window",
                    "regime_label",
                    "state_label",
                    "timestamp_utc",
                    "ilk",
                    "collateral_family",
                    "debt_dai",
                    "collateral_ratio",
                    "liquidation_ratio",
                    "absolute_buffer",
                    "relative_buffer",
                ]
            ]
        )

    pool = pd.concat(pool_frames, ignore_index=True)
    pool = pool.sort_values(
        [
            "regime_label",
            "source_window",
            "collateral_family",
            "ilk",
            "debt_dai",
            "collateral_ratio",
        ],
        kind="mergesort",
    ).reset_index(drop=True)
    pool.insert(0, "pool_row_id", [f"tranche_b_pool_{i:06d}" for i in range(len(pool))])
    return pool.loc[:, OUTPUT_COLUMNS], pd.DataFrame(audit_rows)


def write_outputs(
    pool: pd.DataFrame,
    audit: pd.DataFrame,
    output: Path = DEFAULT_OUTPUT,
    metadata: Path = DEFAULT_METADATA,
    audit_path: Path = DEFAULT_AUDIT,
) -> None:
    """Write deterministic pool artefacts."""
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    pool.to_csv(output, index=False, lineterminator="\n")
    audit.to_csv(audit_path, index=False, lineterminator="\n")

    manifest = {
        "artefact": "vault_initialisation_pools",
        "version": "tranche_b_v1",
        "output_path": str(output.relative_to(REPOSITORY_ROOT)),
        "output_sha256": sha256_file(output),
        "rows": int(len(pool)),
        "columns": list(pool.columns),
        "source_rows": [
            {
                "source_window": source.source_window,
                "regime_label": source.regime_label,
                "path": str(source.path.relative_to(REPOSITORY_ROOT)),
                "sha256": source.sha256,
            }
            for source in POOL_SOURCES
        ],
        "audit_path": str(audit_path.relative_to(REPOSITORY_ROOT)),
        "audit_sha256": sha256_file(audit_path),
        "notes": (
            "Opening states only; active indebted vaults with valid collateral "
            "ratio and liquidation ratio. No urn, owner, transaction hash or "
            "event-history fields are included."
        ),
    }
    metadata.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    pool, audit = build_pool()
    write_outputs(pool, audit, args.output, args.metadata, args.audit)


if __name__ == "__main__":
    main()
