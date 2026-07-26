"""Generate the local-only Phase 2 parameter-adoption review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.estimation.adoption_review import (  # noqa: E402
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
