# Whole-local true-lateral BranchUnit development protocol

## Status and scope

This is a non-formal development fixture for `proto_sw_1_3`. It tests one
question only: whether a complete primary branch plus coordinated lateral
descendants can form a useful BranchUnit. It is not an L/C/G ablation and it
does not evaluate a commercial image model.

The fixed development seeds are `4101`, `4102`, and `4103`. Every seed is
generated once and retained. Candidate search, retry, resampling, repair, and
validation-guided mutation are forbidden.

## Input boundary

The generator may consume only:

- the `proto_sw_1_3` backbone polyline;
- the two flower reserve ellipses and their collar geometry;
- the repeat x-range and canvas bounds.

It must not read or inherit branches, branch roles, guides, growth regions,
space samples, region graphs, or QA fields from the SVG/profile.

## Hierarchy contract

The exact topology is `7 + 12 + 2`:

- seven complete level-1 branches rooted on the backbone;
- twelve genuine level-2 branches rooted on the interior of level 1;
- two genuine level-3 branches rooted on the interior of level 2.

A level-2 curve is never a renamed continuation of level 1. Every child must:

- use `0 < mount_fraction < 0.8`;
- start at the sampled point on its parent, not at the parent tip;
- have an actual entry opening of `34-70` degrees;
- have a root-tip chord direction `30-150` degrees from the local parent
  tangent, excluding both same-direction continuation and reverse retracing.

The level-2 distribution is `2, 2, 2, 1, 1, 2, 2` across the seven primaries.
The two single-child units are the two flower-support units. The exact parent
map and every declared secondary budget are validated.

## Edge-band contract

Only the top and bottom are strict edge bands. The left and right edges are
repeat seams and carry no frontier-coverage requirement.

Five free units must reach a vertical edge band:

- `primary_1_free` -> top;
- `secondary_2a_lat` -> bottom;
- `primary_3_free` -> bottom;
- `primary_6_balance` -> top;
- `secondary_7a_lat` -> top.

The two child frontiers remain true lateral branches. Their roots are inside
their primary parents and their whole-curve chord direction must pass the same
lateral-angle gate as every other child.

A registered frontier must terminate at its target point, leave parallel to
the boundary, place its visible extremum at the apex, and remain inside the
shared top/bottom envelope. Entering an edge approach band and stopping is
allowed; unregistered visible contact or envelope overflow is not.

## Geometry and scene gates

For every curve:

- at most two cubic pieces;
- at most two visible bends and one curvature-sign reversal;
- no degenerate handles or self-intersection;
- no parent recontact after the root contact zone;
- no backbone contact by descendants;
- no non-registered flower intrusion;
- no inter-curve clearance violation outside registered parent-child roots.

Curvature is measured as maximum centerline sagitta divided by root-tip chord.
At least four of five free primaries must lie in `0.055-0.20`, at least nine of
twelve secondaries in `0.05-0.20`, and at least one of two tertiaries in
`0.05-0.20`. Any individual curve above `0.25` fails as over-bent.

## Visible seed-variation gates

Hash differences are insufficient. All three seed pairs must pass every gate:

- attachment coordinates are checked directly, before screen-space motion:
  - `primary_4_flower_1` is the sole fixed trough anchor;
  - each of the other six primary `mount_s` values changes by at least `0.020`;
  - every secondary `mount_fraction` changes by at least `0.035`, with at
    least `8/12` changing by `0.070` or more;
  - after removing parent motion, at least `7/12` secondary attachment points
    slide at least `5 px` along the parent, at least `3/12` slide `9 px`, and
    these changes cover at least four BranchUnits;
  - both tertiary `mount_fraction` values change by at least `0.10`;
- free-primary roots: at least `3/5` move `>=6 px`, median `>=5 px`;
- secondary roots: at least `7/12` move `>=5 px`, at least `3/12` move
  `>=9 px`, across at least four parent subtrees;
- direction: at least `3/5` free primaries change `>=8 deg`; at least `7/12`
  secondaries change `>=10 deg`, including at least `3/12 >=18 deg`;
- length: free-primary median symmetric relative change `>=0.12`; at least
  `6/12` secondaries change `>=0.15`, including at least `2/12 >=0.25`;
- normalized shape: after equal-arclength sampling, root translation, chord
  alignment, and chord normalization, at least `6/12` secondary RMS values are
  `>=0.045`, including at least `2/12 >=0.08`.

Replaying a seed must remain byte-identical even while different seeds pass
the visible-variation gates.

Screen-space root displacement is auxiliary evidence only. It cannot replace
the direct `mount_s`, `mount_fraction`, and parent-relative slide gates because
a child root can move on screen merely when its parent moves.

## Required evidence

The development run must retain:

1. the three generated hierarchy records;
2. per-seed read-only validation with every failure reason;
3. replay, ignored-input, traversal-order, global-control, subtree-control,
   and visible seed-variation proofs;
4. individual whole-repeat renders and one side-by-side contact sheet;
5. a direct mount-position chart for all three seeds, independent of parent
   screen-space motion;
6. the exact plan/kernel identifiers and one-pass generation policy.

Structural passage is necessary but not sufficient. The contact sheet still
requires an explicit whole-scene and local-unit visual review before this
branch route can be treated as visually successful or used in a later L test.
