# BranchUnit L v3 experiment contract

Status: draft pending executable contract tests

## Question

Does a real unit-level plan for child placement, child rhythm, and terminal
closure outperform independent per-curve parameter decisions when both methods
use the same primary, curve primitives, parameter domains, topology, and total
role budgets?

This run tests L only on `proto_sw_1_3`, `growth_region_2`. It does not implement
or infer C or G.

## Fixed matrix and gates

- Reuse the twelve registered trials `L01` through `L12` and their existing
  length ratio, sweep depth, child count, and seed.
- Four trials have zero children; eight have one or two children.
- Generate exactly one L0 and one L1 result per trial.
- No candidate search, retry, validation-driven projection, repair, resampling,
  or failed-result replacement.
- Pass only if L1 is usable in at least 4/12, preferred in at least 7/12, and
  preferred in at least 5/8 child-positive pairs.
- Passing only permits discussion of C; it does not start C.

## Shared factors

For each pair, L0 and L1 share:

- prototype, growth region, anchor, context, trial seed, and raw token vector;
- the exact same two-cubic primary control points and geometry hash;
- child count, topology, one-cubic child/terminal compiler, validator, and
  renderer;
- role widths, primary length, total child length `B_child`, and terminal
  length;
- the same allowed parameter domains:
  - child mount fraction: `[0.28, 0.78]`;
  - each child length: `[0.20P, 0.33P]`, where `P` is primary length;
  - child angle: `[42, 66]` degrees;
  - child bow: `[0.12, 0.36]`;
  - terminal angle: `[20, 32]` degrees for both variants;
  - terminal bow: `[0.12, 0.32]`.

Fairness does not require identical realized mount, per-child length, angle,
bow, side, or terminal-direction value sets. Those are the treatment variables
that L1 is required to coordinate. Only `B_child` is locked between variants.

## L0: independent decisions

- Each child maps its own mount, length, side, angle, and bow token directly.
- The terminal maps its own side, angle, and bow tokens directly.
- L0 receives neither the primary summary nor another child's parameters.
- Changing a child-2 token cannot change child 1 or the terminal.

## L1: one deterministic unit plan

L1 receives only the shared primary, raw token vector, and nominal budget. It
does not receive L0 geometry, a `Scene`, validation results, or a trial id. It
emits one complete plan before any dependent curve is compiled.

Let `tau` be the sign of the primary cumulative turn and let
`release_side = -tau`. Mirroring the primary must flip `release_side` and must
therefore flip both child and terminal sides.

### Joint mounts

For two children, the raw mount tokens become a unit center token and a unit gap
token. They are not two independent proposed mounts.

```text
u_center    = raw["child.1.mount"]
u_gap       = raw["child.2.mount"]
gap_px     = 10 + 8 * u_gap
gap_s      = gap_px / P
max_gap_s  = 18 / P
center_lo  = 0.28 + max_gap_s / 2
center_hi  = 0.78 - max_gap_s / 2
center     = center_lo + u_center * (center_hi - center_lo)
s_proximal = center - gap_s / 2
s_distal   = center + gap_s / 2
```

Thus the physical root separation is constructed once in `[10, 18]` px.
Changing `u_center` moves both roots together; changing `u_gap` moves them in
opposite directions while preserving their center. With one child, its mount
uses the full `[0.28, 0.78]` domain directly.

For one child, L1 uses the following exact mapping. There is no sibling rhythm
to synthesize, but the child and terminal still consume the same unit release
side.

```text
mount = 0.28 + 0.50 * raw["child.1.mount"]
length = B_child
angle = 42 + 24 * raw["child.1.angle"]
bow = 0.12 + 0.24 * raw["child.1.bow"]
side = release_side
```

### Total-length rhythm

For two children, L1 redistributes the shared total `B_child`; it must not copy,
sort, or permute L0's individual lengths.

```text
u_dominance = raw["child.1.side"]
rho_lo = max(0.54, 0.20P / B_child, 1 - 0.33P / B_child)
rho_hi = min(0.60, 0.33P / B_child, 1 - 0.20P / B_child)
rho = rho_lo + u_dominance * (rho_hi - rho_lo)
L_proximal = rho * B_child
L_distal   = (1 - rho) * B_child
```

Both values must remain in the shared `[0.20P, 0.33P]` domain. Changing the
dominance token moves the two lengths in opposite directions while preserving
their exact sum. `rho_lo > rho_hi` makes the contract invalid; it must not be
repaired.

### Shared fan

Child directions are generated in one transported unit frame. At each mount,
the primary tangent is the local zero direction; both children consume the same
`release_side`, fan center, and fan spread.

```text
u_fan_center = raw["child.1.angle"]
u_fan_spread = raw["child.2.angle"]
fan_center = 51 + 6 * u_fan_center
fan_spread = 6 + 6 * u_fan_spread
angle_proximal = fan_center + fan_spread / 2
angle_distal   = fan_center - fan_spread / 2
```

This keeps both angles in `[42, 66]` while making both target directions respond
to the shared fan variables. Bow is generated from a second shared center and
spread, not a sorted L0 value pool:

```text
u_bow_center = raw["child.1.bow"]
u_bow_spread = raw["child.2.bow"]
bow_center = 0.21 + 0.03 * u_bow_center
bow_spread = 0.06 + 0.06 * u_bow_spread
bow_proximal = bow_center - bow_spread / 2
bow_distal   = bow_center + bow_spread / 2
```

### Joint terminal closure

The terminal uses the same `release_side` as the child fan. Its magnitude is a
deterministic combination of:

- the primary signed turn over its final 10 percent of arc length;
- the length-weighted signed child fan moment, or a primary-derived release
  moment when there are no children;
- the terminal turn token.

The exact magnitude rule, compatible with the one shared existing compiler, is:

```text
theta10 = sum(primary signed-turn samples with s >= 0.90)
q_exit = clamp(abs(theta10) / radians(20), 0, 1)
q_fan = clamp(abs(sum((L_i / B_child) * sin(radians(angle_i))))
              / sin(radians(66)), 0, 1)
        # with no children: q_fan = q_exit
q = (q_exit + q_fan + raw["terminal.turn"]) / 3
terminal_angle = 20 + 12 * q
terminal_bow = 0.12 + 0.20 * raw["terminal.bow"]
```

The terminal is compiled from the actual primary exit tangent. Its signed turn
must oppose the primary cumulative turn and strictly reduce the magnitude of
cumulative turning. L0 uses the same terminal compiler and `[20, 32]` domain,
but chooses `side` independently and uses
`terminal_angle = 20 + 12 * raw["terminal.turn"]`.

There is no validation-driven parameter change. Each unit is compiled once and
then checked once.

## Required automatic evidence before formal generation

- The planner is deterministic and its function signature contains no L0
  result, `Scene`, validation result, or trial id.
- The L0 parameter mapper cannot access the primary summary; L1 must consume
  the primary geometry and derive its summary.
- Every L0 and L1 parameter remains inside the shared domains.
- Center-token intervention moves both L1 roots together.
- Gap-token intervention moves the two L1 roots oppositely and preserves center.
- Dominance-token intervention changes the two lengths oppositely and preserves
  `B_child` exactly.
- Fan-center intervention moves both child angles together; fan-spread
  intervention moves them oppositely while preserving their mean.
- Mirroring a primary flips every L1 child side and the terminal side without
  changing budgets.
- On the compiled terminal, sampled signed turn has the same sign as
  `release_side`, `abs(T_primary + T_terminal) < abs(T_primary)`, and every
  sampled terminal segment has positive dot product with the primary exit
  tangent.
- Separate interventions prove terminal magnitude responds to final-10-percent
  primary turn, child fan moment, and `terminal.turn`; it must not merely copy
  `release_side`.
- A fixed synthetic case proves that L1's mount, length, and angle sets are not
  merely permutations of L0's sets.
- Primary geometry, topology, widths, total length, vector ink, and raster ink
  satisfy the paired fairness thresholds.
- Retry, resample, repair, and candidate counts remain `0, 0, 0, 1`.
- Exact replay and all recorded source/artifact hashes verify.

## Development fixtures before the formal run

Before freezing v3, render exactly three non-formal fixtures with raw tokens all
equal to `0.5`, `length_ratio = 0.725`, `sweep_depth = 0.27`, and child counts
`0`, `1`, and `2`. They are not `L01-L12`, do not count toward any gate, are not
candidates, and cannot replace a formal result. Every development revision must
be retained under a new directory. Only after contract tests and these three
fixtures pass may the contract and source hashes be frozen for one formal run.

Fixture pass is not self-declared. All three L1 fixtures must be hard-valid; D0
must have a forward terminal without reversal; D1 must have one naturally
attached child and a continuous terminal; D2 must have a 10-18 px root gap,
visibly separated fan, readable long-short hierarchy, no internal crossing, and
a continuous terminal. L0 remains an independent comparison and is not repaired
to make the development fixture pass. The user must visually confirm the three
fixtures before formal generation.

## Red lines

- Do not copy, sort, or permute L0 parameter pools to create L1.
- L1 must not read L0 geometry or validation results.
- Do not independently generate children and then project or repair them.
- Do not special-case a trial id.
- Do not give L1 a different compiler, curve count, or extra segment.
- Once the formal twelve images exist, do not modify v3. Any later rule change
  requires a new version and cannot replace failed v3 samples.
- A failed contract test means the experiment is invalid, not that BranchUnit
  failed.

## Interpretation boundary

This experiment can accept or reject only this corrected deterministic unit
plan. It is a development gate, not paper-level statistical evidence.
