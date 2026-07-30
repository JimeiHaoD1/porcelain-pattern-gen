# R1 tangent-led L1 motion

- Status: `PASSED`
- Cases: 15 / 15
- L1 metric records: 705
- Hard failures: 0
- Geometry deterministic replay: True
- Selection deterministic replay: True
- L2/L3 generated: false
- Leaves, buds, or curl heads generated: false

R1 changes only the existing Stage-3B L1 candidate motion, rejection, scoring,
and deterministic global search. Every selected lane starts on the parent
tangent, delays its turn, clears the backbone, keeps horizontal motion, remains
inside the vertical canvas, and participates in a crossing-free periodic set.
