# Repository restructuring final review

## 1. Purpose

The repository restructuring changed organisation, naming and canonical
interfaces without changing model economics, empirical values or established
experiment results. This review records the final architecture and the
evidence used to close the structural migration. It does not claim that the
model-development or dissertation programme is complete.

## 2. Final architecture

The authoritative implementation is the six-package `dai_sim` distribution:

- `dai_sim.model` owns economic and simulation mechanics;
- `dai_sim.inputs` owns configuration and runtime empirical inputs;
- `dai_sim.calibration` owns estimation and adoption methods;
- `dai_sim.experiments` owns scenarios, runners, summaries and plots;
- `dai_sim.common` owns shared repository infrastructure;
- `dai_sim` provides the deliberately small package root.

The other repository layers are similarly semantic:

- `workflows/<domain>/` contains 27 acquisition, processing, input-building,
  calibration and maintenance entry points;
- `config/profiles/` contains the `legacy`, `empirical` and
  `empirical_stress` profiles, while `config/sensitivities/` contains 14
  explicit overrides;
- `data/<domain>/{raw,processed,model_inputs,provenance}/` separates empirical
  lifecycles by market, gas, vault, liquidation and protocol ownership;
- `sql/<domain>/{templates,generated}/` separates reusable SQL from preserved
  generated history;
- `docs/` is organised for overview, model, calibration, experiment, data and
  validation readers, with historical reports under `docs/archive/`;
- `tests/` follows model, input, calibration, workflow and integration
  responsibilities;
- `outputs/{experiments,figures,diagnostics,tables}/` separates generated
  results and remains ignored except for its policy README.

## 3. Migration sequence

The migration is a linear 13-commit sequence with no merge commit or feature
development interleaved:

| Commit | Subject | Role |
| --- | --- | --- |
| `3e87fd26f2110714a07900588e5694d4dd1d1e83` | Record pre-migration repository baseline | Frozen the starting tree, data, SQL, runtime inputs and behavioural regressions. |
| `f7e8502909a919f1f09b9eab6dde9d31d0e4c659` | Add package and repository path infrastructure | Established packaging and canonical repository-path resolution. |
| `0d0f245f95f01505246bb3c0e704a3e1af027529` | Migrate source into semantic dai_sim package | Moved implementation into the model, input, calibration and experiment packages. |
| `eebdb00c60d9f8a3e0ebc76d0e4a12c7f98818a6` | Migrate configurations and runtime model inputs | Established complete profiles, semantic sensitivities and domain-owned compact inputs. |
| `3ed696fc53ccdb3eb74c7c95ac86d92e6feb4452` | Migrate data and provenance into domain hierarchy | Assigned raw, processed, model-input and provenance ownership by empirical domain. |
| `61d20b567a83c08d1ce996c5df75cd63d7b65e77` | Migrate scripts into domain workflows | Replaced the flat script surface with 27 domain workflows. |
| `ab1cbd28a876b47d7ef46cefd03fd95c573343ba` | Migrate SQL into domain hierarchy | Moved 117 byte-identical SQL files into templates and generated history. |
| `0c93c91f1c4c81fe10f90041dc1ed4e7d0d613c8` | Reorganise documentation by reader purpose | Consolidated active guidance and archived chronological reports. |
| `e3618512512543164df9a1c57fd1ff70f7c8f701` | Migrate tests into semantic hierarchy | Aligned tests and fixtures with their maintained responsibilities. |
| `1b3bae7c1ab48936c7cfd161400ae1aeb78f102e` | Establish semantic output hierarchy | Separated generated experiments, figures, diagnostics and tables. |
| `29b94b3561e811089c01efb9e2951736f316783c` | Remove temporary compatibility interfaces | Removed flat imports, wrappers, aliases and fallbacks after the bounded transition. |
| `8eab2f30146005ebdedafef17b1447d232681726` | Correct semantic workflow output names | Post-Stage-11 correction removing chronology-labelled active product names. |
| `80ac0834871f744e6255d9ab07421631033a45e8` | Make tracked clones self-contained | Post-Stage-11 correction promoting compact required evidence and removing ignored-data test dependencies. |

The last two commits are bounded, behaviour-neutral corrections rather than
additional numbered migration stages.

## 4. Canonical interfaces

Canonical imports start with `dai_sim`, for example
`dai_sim.model.simulation`, `dai_sim.inputs.configuration`,
`dai_sim.calibration.validation` and `dai_sim.experiments.runner`.
Workflows are invoked through their semantic paths from the repository root,
such as `python workflows/market/process.py --help`. Live acquisition remains
an explicit, credentialled operation.

Complete configuration is selected from `config/profiles/`. Sensitivities are
passed explicitly from `config/sensitivities/`; they are not inherited or
applied silently. Protocol configuration is owned by `config/protocol/`.
Generated results are owned by the four `outputs/` categories, while compact
runtime inputs remain under the owning data domain's `model_inputs/`
directory.

## 5. Clean-clone reproducibility

Compact calibration and protocol evidence needed by canonical consumers is
tracked and content-addressed. Full empirical panels and generated outputs
remain ignored. At commit `80ac0834871f744e6255d9ab07421631033a45e8`,
both the working repository and an equivalent tracked-only checkout collected
and passed 491 tests with no failures, skips or warnings.

The clean checkout contains 360 tracked files (13,313,583 bytes). Its offline
wheel has version `0.1.0a0`, 40 logical entries, the six authorised packages
and distribution metadata only. Installation with `--no-deps`, canonical
imports outside the checkout, obsolete-import rejection, all 27 workflow
imports and 19 safe workflow help checks passed without ignored local
artefacts.

## 6. Integrity evidence

The five compact runtime inputs retain these SHA-256 checksums:

| Input | SHA-256 |
| --- | --- |
| Vault initialisation | `5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892` |
| Market and gas environment | `b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d` |
| Keeper gas | `37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594` |
| Liquidation-arrival hourly pool | `cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a` |
| Liquidation-arrival sequence pool | `9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed` |

All 192 ignored raw and processed payloads match the Stage 5 content ledger.
The unchanged path-sensitive domain digests are:

- market: `f84a6626266655850c314fe2536b23ac56b5db1906ea8535f36204e5e4d0093e`;
- gas: `cdd42a54336d2df67b47ecc1a2688b4d75c3ce9dc0b259ecb22060dc12f4775f`;
- vaults: `f4f25024f5ebfd397e2b0aa9ed33e49d86ae4b5f537e64d8ede7414aae557513`.

Protocol and liquidation payloads also match the Stage 5 content multiset
after their approved semantic filename corrections. A Stage 12 deterministic
audit, hashing sorted `size + content SHA-256` records and separately hashing
`lifecycle + current relative path + size + content SHA-256`, produced:

| Domain | Files | Content-normalised | Current semantic-path |
| --- | ---: | --- | --- |
| Protocol | 8 | `e43d48abca18105581b55f5b652371865a6e0c6a603af3ac2b799dfab81adba9` | `8d70b4f4c840e50cae4145f2f9a6b0502215034d99d70bd5e9fbc1da977cc812` |
| Liquidations | 78 | `0328160abe72c71f3fb1942cb5c44ad4606119133c6879c22b434d6523995138` | `cb5bbb7cf57232a2efa751a3b6a888cbd93f89602eae9a7bb6fb80f27e672cd5` |

All 117 SQL files remain byte-identical to the Stage 7 ledger: 20 are
logically hand-authored or templates and 97 are generated. The
path-normalised digest is
`a8f4a8e03276e62d0abd5c7e813f3771b5df6fa062079e868660d55e0552bc7d`
and the semantic digest is
`8c41d15f425ac5595e9b1cba6eb4df8eb41478e5ed4fa519d2226de0364d8f7d`.

All 194 local generated outputs match the Stage 10 ledger byte-for-byte: 31
experiment files, 25 figures, 130 diagnostics and 8 tables. Their frozen
path-normalised and semantic digests are respectively
`73c2fc777285403dbdba41c5d7399d77b22d5fa794c7ca32113ffcef0b58ae45`
and
`250c74b98ef70890269199fd8161c6a9cb1c96b9a3073538417ddf0267c034bc`.

The five smoke checks and Experiments 1–5 reproduced the checksums in the
[regression guide](regression.md). The archived acquisition plan remains
`05587f17600f148d90cc26df4f281258d299188dad8dd53d2ab00f351863ee60`.

## 7. Provenance

`data/provenance/index.json` provides cross-domain entry points; each domain
then owns acquisition, processing and validation records. Compact evidence
required by active consumers is tracked under
`data/provenance/calibration/`, while optional detailed diagnostics remain
ignored under `outputs/`.

The self-contained-clone correction added 13 evidence artefacts (407,999
bytes), their 10,250-byte manifest and a 4,281-byte integrity test: 422,530
new bytes in total. The largest evidence artefact is
`reviewed_candidates.json` at 124,299 bytes, and none exceeds 1 MiB.

Active reverse lookup from data product to checksum, provenance, SQL, query
and execution identifiers is resolvable and unambiguous. Historical paths are
retained only in archives, generated history, provenance history and
restructuring inventories.

## 8. Compatibility removal

The bounded compatibility period has ended. Flat source imports,
`src.estimation`, script wrappers, cumulative configuration aliases and
compatibility fallbacks are absent. Obsolete import forms fail naturally
rather than being redirected. Canonical modules contain the implementation;
no business logic is duplicated in shims.

## 9. Corrective findings

Final review work identified two structural issues before closure:

1. active workflow products still used chronology-labelled output names;
2. tracked-only clones depended on compact evidence that was present only in
   ignored local diagnostics.

They were corrected separately by `Correct semantic workflow output names`
and `Make tracked clones self-contained`. Both commits preserved empirical
payloads, runtime inputs, SQL, smoke checks and experiment results.

## 10. Remaining limitations

- Live acquisition requires external services, credentials and explicit cost
  authorisation.
- Ignored full raw and processed data are not included in a clean clone.
- Generated outputs are local, reproducible where documented and ignored.
- Seven historical generated SQL artefacts do not byte-match current
  generators and therefore remain preserved as historical evidence.
- Historical records intentionally retain paths and terms from their original
  repository state.
- Model development, empirical adoption, counterfactual validation and
  dissertation writing continue beyond this restructuring.

## 11. Conclusion

The canonical architecture, tracked-only reproducibility boundary and frozen
behavioural evidence have passed the Stage 12 gates. Repository restructuring
is complete subject to a dedicated documentation-only Stage 12 closure
commit. This closes the structural migration, not the wider research project.
