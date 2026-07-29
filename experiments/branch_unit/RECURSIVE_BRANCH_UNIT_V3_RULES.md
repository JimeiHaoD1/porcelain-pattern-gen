# Recursive BranchUnit V3A rule-inheritance contract

Status: `frozen_for_rule_inheritance_development`

## Question

Can level-3 recursive growth be added to the last structurally valid
`proto_sw_1_3` whole/local baseline without abandoning the branch rules that
made its level-1 and level-2 hierarchy readable?

This is a deliberately isolated development step.  It is not a final
recursive architecture and it is not an L/C/G comparison.

## Frozen comparison boundary

For each fixed seed `4101`, `4102`, and `4103`:

- the seven level-1 rows and their compiled geometry must be byte-identical to
  `whole_local_branch.plan_j0a`;
- the twelve level-2 rows and their compiled geometry must be byte-identical to
  the same baseline;
- the baseline's two level-3 rows are removed;
- exactly `6..9` newly planned level-3 rows are added.

Consequently this run tests only whether the recovered rules can govern
recursive children.  Any change to level 1, level 2, the backbone, flower
reserves, or the five existing top/bottom frontier paths invalidates the run.

The five frontier paths remain the baseline paths in V3A.  Moving a frontier
goal down to the deepest descendant is a separate V3B reachability test.  It
must not be mixed into V3A because V2 already showed that a forced edge chain
can hide a failure of the ordinary child rule.

## Topology

- seven level-1 branches and twelve genuine level-2 branches are frozen;
- only the five free units may receive level-3 branches;
- every free unit receives at least one level-3 branch;
- each free unit receives at most two level-3 branches;
- each level-2 parent receives at most one level-3 child;
- total level-3 count is seed-dependent in `[6, 9]`;
- maximum depth is three.

The planner must choose the level-2 parent from the unit's legal parents.  A
fixed carrier slot per unit is forbidden.

## One recursive child rule

Every new level-3 branch is planned in the coordinate frame of its actual
level-2 parent.  World-angle templates are forbidden.

### Attachment

- root is sampled by parent arclength, not by a nearby screen coordinate;
- `mount_fraction` is in `[0.28, 0.72]`;
- at least `max(8 px, 0.20 * parent_length)` of parent tail remains after the
  root;
- a child cannot start at the parent tip or at a parent/ancestor junction;
- the selected parent and mount must come from a non-empty legal interval;
  an empty interval is retained as a planning failure and is never widened.

### Direction

Two different angles are recorded and checked:

- actual entry opening from the local parent tangent: `[34, 60]` degrees;
- root-tip chord opening from the local parent tangent: `[42, 78]` degrees.

The first controls visible departure at the root.  The second proves that the
child occupies a genuinely lateral direction instead of becoming a renamed
continuation or reverse tracing of its parent.  The turn sign is chosen from
the legal free-space components of the unit and its cyclic neighbours.

### Length and hierarchy

- child chord length is in `[0.48, 0.72] * parent_arclength`;
- it is also in the absolute interval `[12 px, 34 px]`;
- the sampled domain is the intersection of those intervals and all scene
  constraints;
- actual child arclength must be shorter than `0.82 * parent_arclength`;
- no fallback such as `high = low + constant` is permitted.

These bounds are intended to prevent both dense short ticks and a child that
visually replaces its parent.

### Curvature and bends

- every semantic child contains at most two cubic pieces;
- sampled bend count is at most two;
- curvature-sign reversal count is at most one;
- normalized sagitta is in `[0.055, 0.20]`;
- self-intersection, degenerate handles, and hook-like terminal reversal are
  failures.

Segment count alone is not accepted as proof of bend count.

## Unit and neighbour context

Before a level-3 row is sampled, the planner constructs a context record from:

- both level-2 children in the current unit;
- the unit's occupied envelope and flower reserve clearance;
- the left and right unit envelopes;
- already allocated level-3 directions and short-branch count;
- the cyclic neighbour across the repeat seam, translated by one repeat width
  before geometric comparison.

Context may remove an illegal parent, side, angle component, or length
component.  It may not expand any numerical rule above.  Once the final legal
domain is known, each parameter is sampled once.  There is no candidate image
search, validation feedback, retry, resampling, repair, deletion, or failed
result replacement.

## Scene rules

- no parent recontact after the registered root zone;
- no descendant/backbone contact;
- no flower-reserve intrusion;
- no unrelated-curve intersection or stroke-aware clearance violation;
- short descendants do not cluster at adjacent roots;
- top and bottom are the only strict frontier bands;
- left and right remain repeat seams;
- the baseline's five free-unit frontier responsibilities and one shared
  visible envelope remain unchanged.

## Seed and replay gates

- replaying the same seed must reproduce equal plan bytes and geometry hash;
- the three seeds must produce different plan and geometry hashes;
- the five mandatory unit-level tertiary paths exist in every seed;
- for every seed pair, at least four of those five paths change parent-relative
  mount by `>= 0.10`;
- at least three of five change chord direction by `>= 10 degrees`;
- at least three of five change chord length by symmetric relative difference
  `>= 0.12`;
- topology may change through the seed-dependent sixth through ninth rows, but
  it cannot change by retry or validation.

## Required evidence and decision

The run retains, without selection:

1. all three exact plans and read-only validation reports;
2. proof that frozen level-1 and level-2 plan rows and geometry equal the
   baseline;
3. the sampled legal range and sampled value of every new parameter;
4. whole-repeat, level-colour debug, seven-unit, and horizontal `2x` views;
5. replay and visible seed-variation reports;
6. every failure reason, including an empty legal domain.

Automatic passage is necessary but insufficient.  The route advances only if
all three images also show readable parent-child departure, long/short
hierarchy, curved but non-snake-like branches, useful whitespace, no dense
short-tick clusters, coherent neighbouring-unit rhythm, and clean repeat seams.

If V3A fails, V3B edge-goal propagation does not start.  If V3A passes, V3B
must preserve this exact child rule and may only intersect it with a backward
reachable top/bottom goal domain.
