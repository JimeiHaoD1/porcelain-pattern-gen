# Invalid L implementation — do not score or cite

This run was frozen before unblinding, then rejected by the independent
fairness audit.  It is retained only as an implementation-audit record.

Blocking defects:

- L1 used narrower, safer child-mount intervals than L0, violating the shared
  parameter-range requirement.
- L0 child lengths were jointly normalized, so the nominally independent
  baseline contained sibling coupling.
- L1 consumed only the primary turn sign rather than the registered local
  curvature/arc-order summary.
- The replay command targeted the already existing output directory and could
  not execute; analyzer/parser hashes were not recorded.

The blind review file was created while mapping was hidden, but it was not
unblinded or used for an experimental conclusion.  The corrected run uses the
same L01–L12 matrix and the same generation seeds; it is an implementation
correction, not a replacement sample draw.

