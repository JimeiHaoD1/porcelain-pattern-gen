# Dynamic BranchUnit stages 0-4

This directory is an independent entry point for the dynamic BranchUnit work.
The fixed `7/12/2` generator is consumed only through the explicit stage-3A
visual prior. Stage 3B does not consume selected layouts from the old
stage-3/stage-4 chain.

Current scope:

- stage 0: freeze and verify the fixed `proto_sw_1_3` baseline;
- stage 1: load the five SW profiles through the `StrictP0 v2` whitelist and
  convert geometry to an isotropic repeat-local frame;
- stage 2: derive one planner-free `PrototypeAnalysis` per SW prototype and
  render SVG/PNG overlays for visual review;
- stage 2.5: bind the five prototypes to three flower/branch morphology
  families, preserve per-prototype density/rhythm evidence as non-binding
  priors, and render source-backed morphology instruction plates;
- stage 3A: verify the immutable fixed baseline and extract role-conditioned
  visual distributions. The strict paired baseline remains `proto_sw_1_3`
  only; cross-prototype fixed-baseline quality is not claimed;
- stage 3B: derive an evidence-driven L1 count and execute one seeded forward
  global flow-lane set solve per task. It controls root position, target zone,
  direction, distance, flower contact, whitespace, and periodic clearance;
- stage 4: freeze the explicitly approved stage-3B launch matrix, enumerate
  the declared complete Unit grammar/role/parameter strata exactly once, and
  materialize L2/L3 cubic Bezier candidates with intrinsic diagnostics;
- former stage-3 v3 and stage-4 v1/v2/v3 outputs remain historical evidence
  and are not planning inputs for stage 3B or its successors;
- editor integration and manual curve editing are not started.

The complete project scope is branch skeleton generation only. Leaves, buds,
and curl heads are not deferred future work; they are outside the current and
later scope. A stage-3 `terminal_intent` records only the intended direction
and ending behavior of a branch tip.

The four implementation decisions are machine-readable in
`IMPLEMENTATION_CONTRACT.json`.

## Commands

```powershell
Set-Location 'D:\sdxl\chanzhi_sw_clean'

# Create the immutable recovery snapshot once.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\freeze_fixed_baseline.py --create

# Verify snapshot hashes, current fixed sources, and deterministic replay.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\freeze_fixed_baseline.py --verify --check-sources --replay

# Materialize StrictP0 v2 for all five SW prototypes.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_stage1_inputs.py

# Analyze all five StrictP0 artifacts and create the review overlays.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_stage2_analysis.py

# Create three-family / five-instance morphology review packages.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_stage25_morphology.py

# Only after explicit human approval, promote both review gates.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\record_stage25_approval.py `
  --reviewer user `
  --note "User approved all five stage-2.5 morphology reviews."

# Extract the formal fixed visual prior.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_stage3a_visual_prior.py

# Execute the formal five-prototype by three-seed global L1 solve.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_stage3b_l1_flow.py

# Only after explicit human approval, bind all fifteen immutable L1 plans.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\record_stage3b_approval.py `
  --reviewer user `
  --note "User approved all fifteen stage-3B L1 flow plans."

# Enumerate complete Unit candidates and render the stage-4 atlases.
D:\Anaconda3\python.exe .\experiments\branch_unit\dynamic\run_stage4_unit_candidates.py
```

`StrictP0 v2` consumes only prototype identity, canvas/repeat geometry,
backbone arc samples, flowers, and the optional new
`structure_protection_zones` field. Legacy branches, guide graphs, space
samples, and growth regions are deliberately ignored.

Stage 2 opens only the materialized `StrictP0 v2` files. Each analysis records
backbone peaks/troughs/turns/slopes, flower relationships and reserves,
two-sided normal probes, continuous blank/crowded/prohibited regions,
candidate L1 attachment intervals, and periodic seam evidence. The intervals
are analysis regions, not selected slots.

Stage 2.5 keeps `StrictP0 v2` unchanged. `MORPHOLOGY_CONTRACT.json` separates
the generation-driving `flower_branch_relation` axis from the
research-annotation-only `pattern_skeleton_class` axis. The old `node_rule`
is used only as curated family provenance. Legacy `unit_type`, old branch
geometry, and old generated layouts are not consumed.

The output is written to
`artifacts/runs/dynamic_branch_stage25_morphology_v1`. Each case contains the
copied source reference, a machine-readable morphology profile, SVG/PNG
instruction plates, and an explicit `morphology_pending_review` record. The
orange/blue arrows on those plates are semantic instructions, not selected
branch slots or curve geometry.

`record_stage25_approval.py` is intentionally separate from generation. It
updates the ten review records and both linked manifests only after explicit
human confirmation.

Stage 3A writes
`artifacts/runs/dynamic_branch_stage3a_fixed_visual_prior_v1`. Its contract is
`FIXED_VISUAL_PRIOR_CONTRACT_V1.json`. Input, hash, topology, and role
mismatches are fatal. No default values or repairs are supplied.

Stage 3B writes
`artifacts/runs/dynamic_branch_stage3b_global_l1_flow_v1`. Its contract is
`STAGE3B_L1_FLOW_CONTRACT_V1.json`. Candidate enumeration belongs to the one
global solve and is preserved for audit; it is not an experimental variant
sweep. There is no retry, resample, auto-repair, auto-deletion, or silent
fallback. Each task emits one selected L1-only layout and remains
`l1_flow_pending_visual_review`.

Stage 4 writes
`artifacts/runs/dynamic_branch_stage4_unit_candidates_v1`. Its contract is
`STAGE4_UNIT_GRAMMAR_CONTRACT_V1.json`. The explicit stage-3B approval is
stored separately as `stage3b_approval.json`, so the reviewed stage-3B
manifest and plans remain immutable. Every approved L1 lane receives a
complete deterministic candidate pool. Invalid candidates are retained with
their reasons, and every lane must still have at least one feasible Unit.
There is no retry, resample, repair, deletion, fallback, best-of-N choice, or
whole-composition selection. The pool remains
`unit_candidate_pool_pending_visual_review`; global conflict-graph selection
belongs to stage 5.

## Superseded chain

The historical symbolic planner contract is frozen in
`STAGE3_PLAN_CONTRACT.json`.
Stage 3 must emit complete `BranchUnitPlan` structures, not independent
curves. There is one raw plan per task, no validation-guided retry/resample,
no automatic repair/deletion, and no curve, leaf, bud, or curl-head geometry.
Its output is written to
`artifacts/runs/dynamic_branch_stage3_plans_v3`. The earlier v1 and v2
iterations remain preserved for visual comparison. Each successful v3 task contains
the input snapshot, symbolic plan JSON, inspectable SVG, PNG review plate, and
an explicit `plan_pending_review` record. Per-prototype and all-task contact
sheets support seed comparison and cross-prototype visual acceptance.

Stage 3 v3 is a directional engineering diagram, not a branch-shape preview.
Ordinary units use one direct root-to-free-space segment. The parent tangent is
recorded only as a reference and is never drawn as an initial segment. Their
outward-normal alignment is at least `0.82`, and their parent clearance after
the initial `0.30` of the path is at least `0.03`.

SW-3 may not use a short near-flower stub. Its support mounts `0.32` to `0.48`
of a repeat arc away, starts below the flower center, passes through a corridor
below the flower reserve, and terminates at the flower underside. Crossings are
hard failures: exact segment intersection returns zero clearance, including
periodic-neighbor copies. Root spacing, density-bin capacity, local direction,
and corridor clearance are all resolved during global selection before any
curve is compiled.

Stage 4 v1 is retained under
`artifacts/runs/dynamic_branch_stage4_curves_v1` as rejected evidence: it
compiled each macro direction into one near-collinear branch and therefore did
not produce complete BranchUnits.

The replacement contract is
`STAGE4_UNIT_CURVE_CONTRACT_V2.json`. Stage 4 v2 preserves the number and
macro placement of stage-3 BranchUnit plans, but it does not trace their
direction lines as final centerlines. It selects visibly bowed two-cubic L1
curves, chooses the actual L2 count from each approved child envelope, places
siblings at coordinated parent arc-length fractions, and optionally adds one
L3. L2/L3 roots and entry derivatives are derived from their actual compiled
parent curves. L3 evaluates both parent-local turn sides before the final
topology is frozen.

The formal output is
`artifacts/runs/dynamic_branch_stage4_unit_curves_v2`. It contains one raw
candidate for every one of the fifteen approved tasks, per-case topology and
read-only diagnostics, original and three-repeat SVG/PNG renderings,
per-prototype contact sheets, and all-prototype contact sheets. Numeric checks
can report straightness, attachment, crossing, repeat, backbone, and flower
reserve problems, but cannot approve the human visual gate.
