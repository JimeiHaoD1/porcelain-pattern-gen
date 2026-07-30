# R2A stage summary

Status: **PASSED**

- Frozen topology digest: `195e214afd784983e4d4b236795b22b0058ca2c8fd16121c8c78effc89003a36`
- Coverage: 5 prototypes x 3 seeds = 15 topology cases.
- SW1: support, wrap, and balance are independent sibling L1 slots on the backbone for the same service flower.
- SW2: neither SW1 nor SW3 topology is forced.
- SW3: remote support and balance are L1 backbone children; no wrap slot is forced.
- Scope: topology only; regions and role curves remain unmaterialized.
- Unsupported topology count: 0.
- Reproducibility: 15/15 topology digests match across two independent materializations.
- Iteration 1 packaging failed on Unicode path transport; iteration 2 fixed only report path discovery.
