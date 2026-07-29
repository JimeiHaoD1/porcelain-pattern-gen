# BranchUnit L blind review protocol

This is a development screening, not paper-level statistical evidence.

Review only `pairs/blind/B01.png` through `B12.png` or `contact_sheet_blind.png`.
Do not open `blind_key.json`, `replay_manifest.json`, `pairs/unblinded/`, `debug/`,
or the metric files until every judgment is frozen.

For A and B separately, mark usable only when all five visual conditions hold:

1. The primary sweep is dominant and readable.
2. Every child reads as growing from the primary rather than floating or forming hair.
3. Child position/length/direction has a readable rhythm; for zero-child trials this is true by construction.
4. The terminal reads as a continuous closure of the primary.
5. The whole object reads as one growth unit.

Use one primary label per panel: `unit_success` for usable results, otherwise one
of `straight_stick`, `hard_angle_bend`, `hairlike_cluster`, `floating_child`,
`crowded_reserve`, or `weak_hierarchy`.  Preserve every failure; there is no
replacement draw.

After review is frozen, run the score command.  L passes only if all three
development gates hold: L1 usable >= 4/12, L1 blind preference >= 7/12, and L1
blind preference within child_count >= 1 trials >= 5/8.  Passing does not start
C automatically; it only permits discussion of C.
