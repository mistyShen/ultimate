# Ultimate V4.4 Large-Scale Standard Scope

V4.4 is a controlled large-scale standard order rehearsal. It tests batch job
layout, Slurm execution, storage guardrails, batch-status, customer-package,
delivery-check, and failure recovery on standard inputs. It is not a mechanism
discovery expansion.

## Included

- `rnaseq standard matrix`: count matrix plus sample metadata.
- `scrna standard h5ad/10x matrix`: standard object or 10x matrix import and QC.
- `proteomics standard abundance table`: abundance matrix plus sample metadata.
- `methylation/SCEPI matrix-level`: beta/accessibility matrix-level analysis.
- `functional_state signature scoring`: reviewed gene set scoring only.
- `single_gene/publicdb table-level`: table-level summaries and handoff-ready evidence.

## Manual Review Required

The following analyses are explicitly excluded from automatic V4.4 standard
rehearsal conclusions and must be treated as `manual_review_required` or
handoff-only unless a separate approved backend validation is run:

- CellChat/NicheNet communication inference.
- inferCNV/CopyKAT malignant inference.
- RNA velocity.
- Complex spatial communication.
- Clinical survival or risk model.
- Full FASTQ/BCL upstream production.

## Customer Boundary

V4.4 uses controlled synthetic/lightweight or existing internal validation data.
It does not use real customer data and does not imply automatic customer
delivery. Any future customer delivery still requires `production_backend`,
approval gate, customer-package generation, and delivery-check pass.
