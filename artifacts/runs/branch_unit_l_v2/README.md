# BranchUnit L v1

Scope: only the local L0/L1 causal screening on `proto_sw_1_3`.

- Generated pairs: 12/12
- Child-positive pairs: 8/8
- All preregistered budget checks passed: True
- Visual status: `pending_blind_review`

Start blind review from `contact_sheet_blind.png`; use individual images under
`pairs/blind/` when details are too small.  Freeze a copy of
`blind_review_template.json` as `blind_review_round1.json`, then score it with:

```powershell
python "D:\sdxl\chanzhi_sw_clean\experiments\branch_unit\run_l.py" score --run-dir "D:\sdxl\chanzhi_sw_clean\artifacts\runs\branch_unit_l_v2" --review "D:\sdxl\chanzhi_sw_clean\artifacts\runs\branch_unit_l_v2\blind_review_round1.json"
```

Verify the saved profile, exact geometry payloads, source hashes, and indexed
artifact hashes with:

```powershell
python "D:\sdxl\chanzhi_sw_clean\experiments\branch_unit\run_l.py" verify --run-dir "D:\sdxl\chanzhi_sw_clean\artifacts\runs\branch_unit_l_v2"
```

Do not infer visual success from `hard_valid` or budget metrics.
