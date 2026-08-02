# Regression and robustness

## Validation layers

Validation is cumulative:

1. schema, checksum, UTC coverage and formula checks for data;
2. estimator and parameter-level uncertainty checks;
3. distributional and moment comparison;
4. withheld-period validation;
5. fixed-seed model and experiment regression;
6. sensitivity to windows, thresholds, blocks and population assumptions.

The FTX interval from 1–21 November 2022 is withheld from primary market,
regime and parameter fitting. It tests whether a classifier and calibrated
mechanisms respond to a disturbance not used to set their thresholds.

## Runtime-input checksums

| Input | SHA-256 |
| --- | --- |
| Vault initialisation pool | `5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892` |
| Market–gas environment pool | `b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d` |
| Keeper-gas pool | `37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594` |
| Liquidation-arrival hourly pool | `cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a` |
| Liquidation sequence pool | `9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed` |

The complete keeper-gas checksum is recorded in the machine-readable Stage 1
baseline and the tracked model-input manifest.

## Frozen smoke checksums

| Smoke | Substantive SHA-256 |
| --- | --- |
| Legacy | `5f7bb2776d72c846ddfd1ceca791ec3f0f2e111ba445e6d12a178796a812fa64` |
| Empirical market/gas | `078cf67155069c9eecc19416407a2254fd03d22d00cf4864b85638fc4adfd53b` |
| Empirical legacy demand | `078cf67155069c9eecc19416407a2254fd03d22d00cf4864b85638fc4adfd53b` |
| Empirical hurdle demand | `bbe69f0ba6813d3c0ed60f4b30ad5b2adc6e12572b4619560d87a62556befbc1` |
| Bounded multi-collateral | `a8913dff2a6955e5dce2424a0955608d930051dbd050f8aa0fa07b47bba93bf9` |

## Experiments 1–5

| Experiment | Substantive SHA-256 |
| --- | --- |
| Baseline scenarios | `30090453d67c4f9632b0212f9df5df178ee4f1aeb769a013056af2a6383a95da` |
| Oracle delay | `f7c9494e3996b83d962193659472afcbc0d87d7ff5345ef221df7c065ae0c761` |
| Shock severity | `1f02073859d7dda416b73ae1470d76570cb9c9ab475ca054971d2a6ef5765c6d` |
| Confidence sensitivity | `73ccf5d20ddca457822ab5d7d10e63061acdd51ee341f562f2c1344dc235f237` |
| Peg recovery | `b843906be4a59d31b4f7b7306b5c2038df77b49ba361bc24c24dd1f5384fe339` |

Canonicalisation sorts rows and columns, excludes path, timestamp and runtime
metadata, and records numeric content to the established precision. The
historical environment, full baseline and comparison method are in the
[Stage 1 baseline](../repository_restructuring_baseline.md) and
[`repository_restructuring_baseline_manifest.json`](../repository_restructuring_baseline_manifest.json).

## Robustness policy

Required sensitivity dimensions include:

- calibration and validation windows;
- regime thresholds;
- 72-, 168- and 336-hour block lengths;
- empirical and parametric vault distributions;
- gas zero handling and upper-tail selection;
- liquidation hurdle and capacity assumptions;
- multiple fixed seeds;
- collateral-specific and system-level outcomes.

Equivalent scenario paths must be detected rather than interpreted as
independent economic findings. Confidence, stable-depeg transmission and
auction execution remain explicit modelling uncertainties.

## ETH recovery experiment gate

The opt-in ETH recovery matrix adds path, registry, common-random-number,
sustained-recovery, censoring, paired-contrast, interaction, decision and
evidence tests. Its execution must preserve the runtime-input checksums,
confidence registry, Stage 1 and residual evidence, frozen smoke checks and
Experiments 1–5 above. Generated checkpoints remain ignored; only compact
content-addressed evidence is registered. Numerical failure above 1% in any
cell invalidates interpretation.

## Current test gate

The Stage 12 final review collected and passed `491` tests in both the working
repository and a tracked-only checkout, with no failures, skips or warnings.
It also reproduced the runtime inputs, smoke checks and Experiments 1–5
without changing assertions, expected values or tolerances. The current
structural contract is summarised in the
[repository guide](../overview/repository_guide.md).
