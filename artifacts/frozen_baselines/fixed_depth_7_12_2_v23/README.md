# Frozen fixed BranchUnit baseline

Baseline: `fixed_depth_7_12_2_v23`

- prototype: `proto_sw_1_3`;
- topology: `7 L1 / 12 L2 / 2 L3`;
- seeds: `4101`, `4102`, `4103`;
- strict paired-comparison scope: `proto_sw_1_3` only;
- generalized five-prototype fixed baseline: not claimed.

The snapshot contains recovery copies of the fixed implementation, its exact
input profile, all v23 output artifacts, and the development protocol. Run the
dynamic module's `freeze_fixed_baseline.py --verify --check-sources --replay`
command to verify integrity and deterministic geometry replay.
