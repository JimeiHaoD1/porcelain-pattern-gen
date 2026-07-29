# BranchUnit L v3 neutral development fixtures

These three pairs are non-formal D0/D1/D2 fixtures. They are not L01-L12,
cannot count toward any development gate, and cannot replace a formal result.

- Automated L1 checks passed: True
- Visual status: `pending_user_confirmation`
- Formal generation locked: True

Verify exact geometry, source hashes, and artifacts with:

```powershell
python "D:\sdxl\chanzhi_sw_clean\experiments\branch_unit\run_l_v3.py" verify-dev --run-dir "D:\sdxl\chanzhi_sw_clean\artifacts\runs\branch_unit_l_v3_dev01"
```
