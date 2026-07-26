# Phase 2A Candidate Review

## Scope

This bounded local review audits all 64 Phase 2A candidates without changing
the original registry, simulator configuration or mechanics. The FTX interval
remains held out from every calibration threshold.

## Candidate decisions

- `blocked_by_additional_data`: 0
- `blocked_by_model_mapping`: 26
- `descriptive_only`: 12
- `provisional_sensitivity_required`: 14
- `ready_for_later_adoption`: 12
- `rejected`: 0

Only exact-ilk liquidation-ratio and liquidation-penalty histories are ready
for later timestamp-selected adoption. All adoption remains separately gated.

## Four zero-gas observations

All four rows are unique, successful, clean single-Take top-level
transactions. They precede London, have explicit source `gas_price = 0`, and
have no available fee-cap, priority-fee or base-fee alternative. No join or
internal-call duplication was found. Their precise economic cause is not
identifiable locally.

Retaining them gives median USD cost 72.4294 and mean
168.22; excluding them gives median
72.8486 and mean 168.745. The primary
later estimator should exclude them or treat them as missing without
imputation, with retain-all reported as sensitivity.

## Liquidation sparsity

The unconditional hourly q90 remains zero. This is evidence of a sparse
arrival process, not evidence that positive liquidation severity is zero.
Only 0.8288% of calibration hours contain
positive volume; their conditional median is
109602 DAI. Among baseline stress hours,
activity rises to 6.5086% and the
conditional median to 164439 DAI.
Arrival probability and conditional positive count/volume should be estimated
separately. A hurdle representation is recommended conceptually, but an
exogenous hurdle arrival mechanism would change the current endogenous
liquidation mechanics and is not implemented here.

## Regime robustness and FTX

The baseline stress prevalence is 9.3769%;
the stricter and looser alternatives give 2.9800%
and 27.4864%. Removing one signal at a time produces
6.4497%--9.1395%
stress prevalence. Replacing the zero-q90 liquidation indicator with the
positive-hour median gives 9.2413%.
The baseline remains interpretable but provisional.

The withheld FTX interval is classified as stress for
18.5417% of hours without using the event label for fitting.
Its longest classified stress run is 33 hours,
compared with 2.31 hours implied by the calibration
transition exit probability; persistence is understated. This validates the
classifier diagnostically, not the complete ABM.

## Block length

The 168-hour block remains the default candidate because it follows the
registered absolute-return persistence rule and preserves weekly structure.
Use 72 and 336 hours as sensitivity bounds; 24 hours is a short-memory
robustness case. The bounded composite preservation score is lowest at
336 hours, so 336 hours must remain an
explicit sensitivity rather than being discarded. No large bootstrap dataset
was materialised.

## Protocol and compatibility

All 36 protocol histories preserve exact ilk, non-overlapping effective
intervals and contract-default provenance. Historical replay selects by
timestamp. Generic experiments must select an explicit baseline timestamp or
labelled observed range, never an unlabelled historical average.

The main compatibility gaps are empirical block construction, a regime-aware
gas sampler, transition-state consumption, a hurdle activity mechanism and
within-run effective-dated protocol settings. These are later design choices,
not changes made by this review.

## Phase 1E-B ranking

1. Quiet mature market — ordinary denominator and baseline distributions.
2. USDC/SVB — short, distinctive stablecoin stress.
3. Bull-market expansion — leverage and WBTC-B/C adoption.
4. Terra/CeFi — longest and costliest persistent-stress calibration window.
5. FTX — acquire and preserve only as withheld validation.

Black Thursday remains methodology and legacy-stress validation evidence, not
Liquidations 2.0 calibration.

## Decisions and unresolved issues

- Do not alter the original 64 candidates.
- Use positive clean-Take costs as the primary gas evidence.
- Keep the baseline two-state regime provisional.
- Keep 168 hours as default with 72--336-hour sensitivity.
- Do not adopt conceptual gas, arrival or unsupported protocol fields.
- Acquire Phase 1E-B opening states and representative mutations before vault
  population or owner-behaviour estimation.

## Output checksums

- `data/processed/estimation/phase2a_review/candidate_review.csv` — `acc70230f9c33d4637b4e3b21f31ba82d19677abcf045a8a478d77de68ded9cd`
- `data/processed/estimation/phase2a_review/gas_zero_transaction_review.csv` — `e3ac3fa974ce3c6b48dc3348d03cc705514f072d10be01c1b6a0de30d7b46b8f`
- `data/processed/estimation/phase2a_review/gas_cost_sensitivity.csv` — `456a2c5e3308690456a69127235a0dc786edf01189eb355159788a9bdc65042d`
- `data/processed/estimation/phase2a_review/liquidation_sparsity_review.csv` — `fe90f490659f5efa18c6181efc0f66f645b5266c38f8da561561a5ecc18d620e`
- `data/processed/estimation/phase2a_review/regime_sensitivity.csv` — `ab58169fbe9484478275a00215b903c257d80364dd21ba5ebb8ff45a2af70b51`
- `data/processed/estimation/phase2a_review/ftx_validation_diagnostics.csv` — `16d55a8496c31e36dff762fbce0e486886c7bfe266e36ff7229ed18c69db0439`
- `data/processed/estimation/phase2a_review/block_length_sensitivity.csv` — `6a032daffd99c83ebb62cb9220d6072f93949c187e22e669a2ec9aebdf97a7eb`
- `data/processed/estimation/phase2a_review/protocol_candidate_review.csv` — `c7f945a1b5d442dc7f9229102bdfd27818186d3b876ebe6fef5276275983c05b`
- `data/processed/estimation/phase2a_review/model_compatibility.csv` — `41bc8be0492885b08b1167ebb45e49e0d1ede950ee2d7534eb5d31d6ab7bbac5`
- `data/processed/estimation/phase2a_review/phase1e_b_dependency_review.csv` — `fd9d6e51d819e71f690f06c4182ebbc8c68a369ebc7915530efb21e7b91dfff1`
- `data/processed/estimation/phase2a_review/phase2a_reviewed_candidates.json` — `5875728b0cfe260752dc2f1618a92a1c958145e5eaa82a91505356a064e10300`

## Recommended next task

Prepare a bounded Phase 1E-B acquisition authorisation beginning with the quiet
mature and USDC/SVB windows, including authoritative opening-state evidence.
