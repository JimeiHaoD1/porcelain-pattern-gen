# Multi-branch L development protocol

Status: `draft_development`

This protocol replaces the single-local-unit interpretation in
`L_V3_PROTOCOL.md` for the next development gate.  The earlier files and
artifacts are retained as rejected evidence; they are not formal results.

## Question

Does one closed-form joint mapping of a first-level branch set produce a more
coherent result than mapping the same branch roles independently?

This is still the L question.  There is one fixed repeat and one branch set.
There is no density field, candidate search, beam search, backtracking, repair,
or replacement.  Those remain outside this stage.

## Input whitelist

The generator may consume only these fields from `proto_sw_1_3`:

1. `backbone.arc_samples`;
2. `flowers[*].flower_id/center/rx/ry`;
3. `repeat_x_range`;
4. `canvas.width/height`;
5. `prototype_id`.

It must not consume `existing_guides`, `growth_regions`, `space_samples`,
`region_graph`, inferred attachments, old branch roles, or old clearance
values.  Hiding old guides in the renderer is insufficient because those
derived fields already contain information from the inherited SVG branches.

The stripped input has the policy id
`backbone_flower_reserves_repeat_bounds_only_v1`.  Its digest is calculated
from the whitelist alone.  Mutating every ignored profile field must leave the
digest and generated geometry unchanged.

## Output topology

Each result is one set of first-level branches:

- branch count is exactly `N in {4, 5}`;
- every branch attaches directly to the backbone;
- exactly two branches are flower branches, one for each flower reserve;
- the remaining `N-2` branches are free branches;
- there are no branch-on-branch children and no inherited SVG branches.

For this development gate, the flower branch ends at the reserve collar facing
the backbone.  It approaches the collar without entering the reserve earlier.
The flower ellipse remains a position/reserve condition, not inherited branch
geometry.

## Bend definition

The two-cubic capacity is an upper bound, not the bend count.

For every complete branch:

1. sample the curve by arc length densely enough for a stable tangent trace;
2. unwrap consecutive tangent changes;
3. group consecutive changes with the same sign into one turn lobe;
4. remove a lobe only when both its accumulated turn is below 12 degrees and
   its covered length is below 8 percent of the branch length;
5. merge adjacent same-sign lobes after removing numerical noise.

The remaining lobe count is the measured bend count.  A C-shaped sweep has one
bend; an S-shaped sweep has two.  Every branch must satisfy
`measured_bend_count <= 2`.  Equivalently, a valid branch may have at most one
effective curvature-sign reversal.  Segment count alone never proves this.

## L0 and L1

Both variants share the same stripped P0, branch count, role list, raw tokens,
curve compiler, maximum two-cubic capacity, width, role-length budget,
validator, and renderer.  Generation is one pass and validation is read-only.

The two flower-support mount positions are derived from P0 alone and held
identical across L0/L1 in these two compiler-development fixtures.  This keeps
flower connection feasibility from confounding the first multi-branch visual
gate.  They are still newly generated curves; no SVG branch is reused.  The
`center + gap` intervention below is applied to the `N-2` free branches.  A
formal L matrix may expand the joint mapping to all mounts only after this
development representation is visually accepted.

### L0 independent

Each free branch maps its own token row to its mount, local shape, and release
without reading sibling parameters.  A flower branch may read only its assigned
flower reserve and the shared P0-derived support mount.  Changing one token row
must change at most that branch.

### L1 joint set

All free-branch mount positions are produced at once from `center + gap`.
Their sides and bend modes are derived as one alternating sequence.  The two
shared flower-support branches are compiled by the same programmatic flower
compiler in both variants.  There is no post-generation sorting, repair,
validation feedback, or candidate selection.

## Development gate only

Generate exactly two paired fixtures:

- one pair with four branches;
- one pair with five branches.

These fixtures test the input stripping, topology, bend audit, and whether a
full-repeat comparison is visually meaningful.  They are not part of the
12-pair formal matrix and cannot be used as paper evidence.

Before a formal matrix is frozen, the user must visually confirm that:

1. no old SVG branch remains visible or influences placement;
2. four or five generated branches are readable as a set;
3. no branch appears snake-like or contains more than two visible bends;
4. the flower-branch relationship is readable;
5. the result is worth using for the L0/L1 comparison.
