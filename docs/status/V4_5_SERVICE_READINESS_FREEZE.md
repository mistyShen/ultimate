# Ultimate V4.5 Service-Readiness Freeze

Ultimate enters service-readiness freeze after the V4.5 controlled 100-job
batch rehearsal. This freeze records the current order-ready platform surface
and stops feature expansion until service-readiness issues have been worked
down.

## Status

- Commit: `c0f8a691bd22203db31ea548111523fa2859b339`.
- Freeze decision: service-readiness freeze is active.
- Service posture: controlled standard bioinformatics service workbench is ready
  for limited real-order trial.
- Evidence posture: large-scale standard order rehearsal passed.
- Scope boundary: complex mechanism analyses remain manual-review or
  handoff-required.

## V4.5 Rehearsal Evidence

The V4.5 rehearsal used controlled lightweight inputs and did not use real
customer data.

| Metric | Result |
| --- | --- |
| Slurm array job id | `9420521` |
| Slurm finalize job id | `9420531` |
| Expected jobs | `100` |
| Observed jobs | `100` |
| Chunk summaries found | `10/10` |
| Ready | `100` |
| Blocked | `0` |
| Failed | `0` |
| Storage total | `74.704549 GB` |
| Storage under 500 GB | `true` |
| Negative controls | `10` |
| Negative controls status | `ready` |
| Negative preflight status | `10/10 blocked` |
| Negative delivery-check status | `10/10 not_run_preflight_blocked` |
| Negative controls counted toward 100 | `false` |
| Top blockers | `none` |

## Per-Module Pass Rate

| Module | Passed jobs |
| --- | ---: |
| `rnaseq` | `20/20` |
| `scrna` | `15/15` |
| `proteomics` | `15/15` |
| `methylation` | `10/10` |
| `scatac` | `10/10` |
| `spatial` | `10/10` |
| `multiome` | `8/8` |
| `cite_seq` | `5/5` |
| `vdj` | `4/4` |
| `functional_state` | `3/3` |

## Required Artifact Checks

The following required artifacts existed and were non-empty during the V4.5
acceptance check:

- `reports/v4_5_100_job_rehearsal_report.md`
- `reports/batch_status_v4_5_100_job/batch_status_manifest.json`
- `audits/storage_v4_5_100_job_latest/storage_audit_summary.json`
- `audits/order_readiness_v4_5_100_job_latest/module_order_readiness_matrix.tsv`
- `reports/v4_5_100_job_negative_controls/negative_control_preflight_manifest.json`

`sacct` did not return records in the checked environment. Completion was
confirmed by cleared `squeue`, Slurm logs, chunk summaries, finalize output, and
the required non-empty artifacts above.

## Freeze Rules

No new algorithms should be added during the freeze. Do not modify the V4.5
main path unless a blocker requires a minimal scoped fix.

Allowed during freeze:

- Blocker bug fixes.
- Documentation wording fixes.
- Sanitization QA fixes.
- Delivery-check and customer-package QA fixes.
- Remote stability fixes.

Not allowed during freeze:

- New algorithm backends.
- Expansion of the V4.5 rehearsal path.
- Reclassifying handoff or manual-review analyses as automatic.
- Claiming real customer delivery from controlled rehearsal evidence.
- Weakening approval, sanitization, or delivery-check gates to improve pass
  rates.
