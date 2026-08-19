# Ultimate V4.5 100-Job Rehearsal Scope

V4.5 is a controlled rehearsal for scheduling, static job inventory, batch
chunking, delivery guardrails, and status accounting across exactly 100 runnable
jobs. It is not real customer delivery and it is not a raw-upstream production
run.

## Runnable Job Distribution

- `rnaseq`: 20 controlled count-matrix jobs.
- `scrna`: 15 controlled h5ad or 10x matrix jobs.
- `proteomics`: 15 controlled abundance-table jobs.
- `methylation`: 10 controlled beta-matrix jobs.
- `scatac`: 10 controlled peak-matrix jobs.
- `spatial`: 10 controlled Visium-matrix jobs.
- `multiome`: 8 controlled h5mu or paired-matrix jobs.
- `cite_seq`: 5 controlled feature-barcode jobs.
- `vdj`: 4 controlled Cell Ranger VDJ table jobs.
- `functional_state`: 3 controlled signature-scoring jobs.

The 100 runnable jobs are split into 10 chunks of 10 jobs each. Negative controls are declared separately and are not counted in the 100 runnable jobs.

## Excluded Scope

V4.5 excludes heavy algorithms and raw upstream production. The following remain
handoff-only or `manual_review_required` unless a separate approved backend
validation exists:

- FASTQ/BCL processing, raw upstream production, or full public atlas downloads.
- CellChat/NicheNet communication inference.
- inferCNV/CopyKAT malignant inference.
- RNA velocity.
- Full WNN or multiVI integration.
- Complex spatial communication.
- Clinical survival or risk-model claims.
- Any mechanism claim that depends on unvalidated advanced backends.

## Customer Boundary

V4.5 uses controlled synthetic, lightweight, or existing internal validation
inputs. It may exercise customer-package and delivery-check guardrails, but it
must remain `internal_rehearsal` with `delivery_mode=customer_delivery_rehearsal`
and `customer_delivery_actual=false`. Passing the V4.5 rehearsal does not make
any job real customer delivery and does not allow use of raw customer data
without a separate approval gate, sanitized package, and production-specific
evidence.
