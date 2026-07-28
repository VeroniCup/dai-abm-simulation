"""Generate the local-only Phase 2 parameter-adoption review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
from dai_sim.calibration.adoption import (
    AdoptionReviewConfig,
    DEFAULT_OUTPUT,
    run_adoption_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(
        run_adoption_review(AdoptionReviewConfig(output_dir=args.output_dir)),
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
