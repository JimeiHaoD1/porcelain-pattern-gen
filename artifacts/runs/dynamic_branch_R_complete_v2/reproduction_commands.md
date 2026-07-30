# Reproduction commands

Run from `D:\sdxl\chanzhi_sw_clean`:

```powershell
python experiments/branch_unit/dynamic/diagnostics/selection_generate_R6_visual.py
python -m pytest -q tests/branch_unit_R/test_R2D_intersections.py tests/branch_unit_R/test_R3_intersections.py tests/branch_unit_R/test_R4_intersections.py tests/branch_unit_R/test_R5_intersections.py tests/branch_unit_R/test_R6_intersections.py
python experiments/branch_unit/dynamic/diagnostics/selection_finalize_R_complete_v2.py
```

The automated regression scope is intersections only. Inspect
`five_prototype_three_seed_contact_sheet.png` and
`region_plan_contact_sheet.png` for all other acceptance.
