# Ultimate Bioinfo Workbench

`ultimate` is a CLI-first, HPC-ready workbench for Codex-assisted reproducible
human/mouse multi-omics analysis delivery under the formal remote project root:

```text
/shared/shen/2026/ultimate
```

The user provides raw data paths, available sample information, organism/group
context when known, and a plain-language analysis request. Codex then uses
Ultimate to triage the request, choose suitable modules/tools/presets, run
preflight checks, submit Slurm jobs when needed, and produce figures, reports,
manifests, and reproducible-code packages. The platform is not an automatic
quoting system and does not replace human biological interpretation.

It supports request triage, project templates, input validation, raw-QC
handoff, validated-run handoff, selectable figure styles, Chinese reports, and
explicit manifests for the current human/mouse order-ready module set:

- bulk RNA-seq
- single-cell RNA-seq
- single-cell ATAC-seq
- single-cell Multiome
- VDJ / TCR / BCR repertoire
- single-cell DNA / genome
- single-cell mtDNA
- single-cell epigenomics / chromatin accessibility
- CITE-seq / ADT tag analysis
- spatial transcriptomics
- Perturb-seq / CRISPR screen handoff
- HTO / Cell Hashing demultiplex handoff
- genotype demultiplex handoff
- single-cell functional state and tumor specialty summaries
- cross-sample / clinical association
- method tools / cellxgene handoff
- methylation array / beta matrix
- proteomics / metabolomics abundance tables
- public database mining
- WGCNA
- single-gene analysis

The production audit reports module-level `ready_basic` or explicit partial
status per modality. This is a
basic order-ready guarantee: raw or semi-raw contracts, preflight checks, QC
handoff, standard matrix/object handoff, figures, tables, Chinese reports, and
manifests are available for human and mouse. Advanced algorithms such as
SCENIC, CellChat/NicheNet, inferCNV/CopyKAT, chromVAR, RNA velocity, Cell
Ranger, Space Ranger, and CIBERSORT are exposed as optional presets, adapters,
or user-provided licensed paths instead of being promised as fully automatic
best-parameter runs.

Explicitly out of scope for this single-cell gap-fill pass: true single-cell
mass-spectrometry proteomics, spatial protein / multiplex imaging platforms,
complex lineage/barcode-tracing libraries, and non-human/non-mouse organisms.

## Supported Inputs

- RNA-seq: FASTQ command plans, external tool detection, existing count matrix,
  or generated demo matrix.
- BCL / upstream demux: `bcl-convert` / `bcl2fastq` path detection and Slurm
  wrapper contracts only; no licensed software is bundled.
- Single-cell RNA-seq: 10x H5/MTX/h5ad, FASTQ adapter routes, Smart-seq2
  templates, and non-10x matrix handoff for BD Rhapsody, Parse Evercode,
  Drop-seq, Seq-Well, and compatible exports.
- Single-cell ATAC / epigenomics: FASTQ adapter contracts, fragments, peak
  matrices, Cell Ranger ATAC outputs, and specialty epigenome handoff templates.
- Multiome / CITE-seq / VDJ / spatial: 10x-style matrices, ARC outputs,
  RNA+ATAC fragments, ADT matrices, contig annotations, AIRR tables, Visium
  outputs, spatialdata/SOPA-compatible spatial exports, or validated
  public/existing handoff objects.
- Perturb-seq / HTO / genotype demux: guide count, hashtag count, BAM/VCF/barcode
  and result-table contracts that produce standardized tables and report entries.
- scDNA / mtDNA: BAM/FASTQ/variant-table handoff plus optional MissionBio/Tapestri,
  mgatk, MitoTrace, mitoClone2, cellsnp-lite/vireo-style import contracts.
- Methylation: beta matrix import; IDAT is recorded as a formal raw contract and
  can be handled by optional parser/backends.
- Proteomics/metabolomics: bulk MaxQuant, Proteome Discoverer, or generic
  abundance tables remain supported; true single-cell mass-spec proteomics is
  not part of this pass.
- PublicDB: cached public expression and clinical tables or generated demo
  cohort data.
- WGCNA, single-gene, and clinical association: standardized expression/feature
  matrices plus sample or clinical metadata.

## Quickstart

```bash
python -m pip install -e '.[dev]'
ultimate init-project --type all --output-dir example_projects/demo_all --demo-data
ultimate preflight --config example_projects/demo_all/config/project.yaml
ultimate run --config example_projects/demo_all/config/project.yaml
ultimate report --run-dir example_projects/demo_all/runs/demo_all
ultimate delivery-check --run-dir /shared/shen/2026/ultimate/jobs/<job_id>
ultimate handoff-check --root /shared/shen/2026/ultimate
ultimate styles --style soft_color --output-dir example_projects/style_review
ultimate audit-production --root /shared/shen/2026/ultimate
ultimate audit-backends --root /shared/shen/2026/ultimate
ultimate audit-modules --output-dir /shared/shen/2026/ultimate/audits/module_standardization_latest
ultimate prepare-intake --root /shared/shen/2026/ultimate --output-dir /shared/shen/2026/ultimate/intake_packages/latest --refresh-audit
ultimate audit-tools --root /shared/shen/2026/ultimate
ultimate trial-tools --root /shared/shen/2026/ultimate --batch scrna_core --no-install
pytest -q
```

## V3 Backend Registry

V3 adds backend-level tracking on top of the v2 module maturity table. A
backend is only treated as fully automatic when it has a registered input
contract, dependency environment, Slurm profile, output contract, validation
dataset, limitations, manifest fields, and evidence/approval gate. Planned,
optional, handoff, or licensed tools remain visible in reports but are not
promoted to formal automatic results.

```bash
ultimate audit-backends \
  --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/audits/backends_latest

python /shared/shen/2026/ultimate/01_tools/write_v3_status_report.py \
  --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/reports
```

Backend fields are written into preflight, module manifests, reports, and
production audit outputs:

- `backend_id`
- `backend_status`
- `backend_analysis_level`
- `backend_delivery_allowed`
- `backend_validation_evidence_allowed`
- `backend_skip_reason`
- `backend_resource_profile`
- `backend_slurm_job_id`

Current `fully_automatic_mvp` entries are intentionally conservative matrix or
validated-entrypoint backends. High-value V3 targets such as CellTypist,
Scrublet, LIANA, CopyKAT/inferCNV, scVelo, pseudobulk DESeq2/edgeR, Signac or
SnapATAC2-compatible matrix entrypoints, MuData, squidpy, scirpy, DSB, WGCNA R
handoff, and public-table backends are tracked at backend level and must keep
pytest, Slurm validation, and report warnings before they are treated as
current evidence. Licensed tools such as Cell Ranger and Space Ranger remain
user-provided path backends.

### V3.1 Advanced Presets

Advanced presets now resolve to explicit backend groups instead of requiring a
manual notebook edit. For example:

```yaml
modules:
  scrna:
    enabled: true
    preset: communication
    backends:
      annotation: celltypist
      communication: liana,cellchat,nichenet
  scatac:
    enabled: true
    preset: publication
    backends:
      motif: chromvar
```

The resolver records `preset_selected_backends`, `active_backends`,
`skipped_optional_backends`, and interpretation warnings in backend manifests.
`CellChat`, `NicheNet`, and `chromVAR/Signac` are guarded optional backends:
they run only when the required labels, mappings, packages, resources, and
input contracts are present; otherwise they write explicit skip/blocked rows in
`backend_execution_manifest.json` or module backend status tables. Skip rows are
not delivery evidence.

Slurm validation entrypoints:

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/scrna_cellchat_validation.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/scrna_nichenet_validation.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/scatac_chromvar_validation.sbatch
```

CellChat results are ligand-receptor candidates, not direct mechanism proof.
NicheNet-style ligand-target scoring is a mechanism-hypothesis screen and
requires reviewed labels plus a compatible ligand-target resource.
chromVAR/Signac motif deviation and gene activity outputs are
accessibility-derived inferences, not TF activity assays or gene expression.

### V3.3 Production-Style Rehearsal And Delivery QA

V3.3 turns validated backends into an order-facing rehearsal path. It does not
make validated public evidence a customer delivery; customer or rehearsal
delivery still requires `production_backend`, an approved production JSON, a
Slurm job id, reproducibility files, and a passing delivery QA gate.

The delivery QA gate is:

```bash
ultimate delivery-check --run-dir /shared/shen/2026/ultimate/jobs/<job_id>
```

`delivery-check` accepts either a concrete run directory with
`run_manifest.json` or a prepared job directory with
`deliverables/latest_run_pointer.json`. It writes:

```text
reports/delivery_check.json
reports/delivery_check.tsv
deliverables/latest_delivery_check.json
deliverables/latest_delivery_check.tsv
```

It blocks delivery when any required evidence is missing, including:

- `analysis_level=production_backend`
- `delivery_scope` of `internal_rehearsal` or `customer_delivery`
- approved `production_approval.json` whose `input_path` and `output_dir`
  match the run
- non-empty Slurm job id
- `report.html`, `methods.md`, `delivery_index.tsv`
- `software_versions.tsv`, `input_checksums.tsv`, and `rerun.sh`
- backend execution manifest rows for scRNA/scATAC advanced presets
- report warning text that preserves interpretation boundaries

The V3.3 rehearsal suite submits three internal production-style jobs under
`/shared/shen/2026/ultimate/jobs/<job_id>/`:

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/v3_3_production_rehearsal.sbatch
```

The suite covers:

- `rnaseq` matrix `standard`
- `scrna` `communication`
- `scatac` `publication`

Each rehearsal job writes its own `config/project.yaml`,
`config/production_approval.json`, run manifest, reports, deliverables mirror,
and reproducible-code package. These runs use
`delivery_scope=internal_rehearsal`; they are not `customer_delivery`.

After the suite, refresh the status reports:

```bash
ROOT=/shared/shen/2026/ultimate
PY=$ROOT/.conda/envs/ultimate-core/bin/python

$PY -m ultimate.cli validation-index --root $ROOT \
  --output-dir $ROOT/reports/validation_index
$PY -m ultimate.cli audit-production --root $ROOT \
  --output-dir $ROOT/audits/production_latest
$PY -m ultimate.cli audit-backends --root $ROOT \
  --output-dir $ROOT/audits/backends_latest
$PY $ROOT/01_tools/write_v3_3_order_ready_report.py \
  --root $ROOT \
  --output-dir $ROOT/reports
```

`reports/v3_3_order_ready_report.md` separates order-ready presets from
validated-only evidence, handoff-required presets, license-required presets,
and presets that still require manual review.

The raw upstream handoff QA gate is:

```bash
ultimate handoff-check --root /shared/shen/2026/ultimate
```

It writes `audits/handoff_latest/handoff_check_manifest.json` and
`audits/handoff_latest/handoff_check.tsv` and only checks the packaged
nf-core-style handoff templates. It does not execute upstream Nextflow
workflows and does not convert FASTQ directly inside Ultimate.

### V3.4 Order-Ready Rehearsal Expansion

The V3.4 rehearsal suite extends the production-style rehearsal path to the
next order-ready modules:

- `cite_seq` `standard`
- `vdj` `standard`
- `spatial` `standard`
- `functional_state` `standard`

Submit the rehearsal suite with:

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/v3_4_order_ready_rehearsal.sbatch
```

Each rehearsal job writes its own
`jobs/<job_id>/{config,samples,runs,logs,deliverables,reproducible_code,raw_links}/`
tree, stamps `delivery_scope=internal_rehearsal`, generates a
`production_approval.json`, and runs `ultimate delivery-check --run-dir
/shared/shen/2026/ultimate/jobs/<job_id>`.

After the suite, refresh the server-side metadata views with:

```bash
ROOT=/shared/shen/2026/ultimate
PY=$ROOT/.conda/envs/ultimate-core/bin/python

$PY -m ultimate.cli validation-index --root $ROOT \
  --output-dir $ROOT/reports/validation_index
$PY -m ultimate.cli audit-production --root $ROOT \
  --output-dir $ROOT/audits/production_latest
$PY -m ultimate.cli audit-backends --root $ROOT \
  --output-dir $ROOT/audits/backends_latest
```

For a lightweight developer sanity check before syncing local changes, run:

```bash
bash /shared/shen/2026/ultimate/scripts/check_dev_entrypoint.sh --mode local
```

Use `--mode remote` only for short shared-root checks through `hpc-run`; full
validation and rehearsal execution still belong on Slurm.

## SCEPI Matrix Backend

The SCEPI module is a matrix-level single-cell epigenomics MVP, not a full
modality-specific scBS-seq, scNMT-seq, CUT&Tag, CUT&RUN, or scATAC best-practice
pipeline. It accepts region/probe/peak matrices where the first column is one
of `feature_id`, `region_id`, `peak_id`, `probe_id`, or `locus_id`, followed by
numeric sample/cell columns. h5ad handoff objects are also accepted when the
runtime has `anndata` available.

The backend writes module artifacts under:

```text
results/tables/scepi/{feature_qc,sample_qc,missing_value_summary,differential_region_handoff,promoter_summary,enhancer_summary,annotation_summary}.tsv
results/figures/scepi/{pca,sample_correlation_heatmap,region_heatmap}.png
objects/scepi/scepi_mvp_object.json
objects/scepi/scepi_mvp_object.rds
reports/scepi/{report.html,methods.md}
```

`differential_region_handoff.tsv` is design-ready/preview output only and must
not be reported as a formal DMR/DAR result. Public validation is run through
Slurm:

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/scepi_backend_validation.sbatch
```

The standalone validation entrypoint is:

```bash
python /shared/shen/2026/ultimate/01_tools/validate_scepi_public.py \
  --output-dir /shared/shen/2026/ultimate/validations/slurm_scepi_matrix
```

Successful validation is `analysis_level=validated_backend`,
`validation_evidence_allowed=true`, `delivery_allowed=false`, and
`delivery_scope=not_customer_delivery`.

## Technical Triage

`ultimate triage` only checks whether a request is technically ready to run. It
does not start analysis, does not quote, does not call the production pipeline,
and does not create `run_manifest.json` or `production_approval.json`.

```bash
ultimate triage \
  --request config/analysis_request.yaml \
  --output-dir triage/<job_id>
```

Triage output status is one of `ready_to_run`, `needs_metadata`,
`needs_dependency`, `needs_license`, `needs_manual_review`, or
`not_supported`. The manifest is always `analysis_level=smoke_backend`,
`delivery_allowed=false`, `validation_evidence_allowed=false`, and
`non_delivery_reason=triage_only_not_analysis_run`.

Triage writes `triage_manifest.json`, `triage_report.md/html`,
`suggested_project.yaml`, `samplesheet_template.tsv`, `input_assessment.tsv`,
`handoff_plan.md`, `slurm_command.txt`, `missing_requirements.tsv`, and
`risk_flags.tsv`.

V3.5 的接单前入口会区分标准输入和上游原始输入：

- matrix/object/table 输入，例如 count matrix、10x matrix、h5ad、h5mu、
  abundance table、beta matrix，可以进入 `prepare-job` 和 `preflight`。
- FASTQ、BCL、fragments 等 raw upstream 输入只生成 handoff 方案；它们不会被
  triage 标成可直接完成分析。
- `slurm_command.txt` 只给出 `prepare-job` 和生成后 job sbatch 的命令草稿，
  不再直接把 `project.yaml` 作为额外参数塞给全局 Slurm wrapper。

## scRNA MVP Validation

`validate-scrna` 的验证级路径统一称为 `scrna_mvp`。真实公开数据验证通过 Slurm 运行，不在登录节点做重计算：

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/scrna_mvp_validation.sbatch
```

默认输出在：

```text
/shared/shen/2026/ultimate/validation_runs/scrna_mvp_validation/{10x_mtx,h5ad}/
/shared/shen/2026/ultimate/validation_runs/scrna_mvp_validation/10x_mtx/
/shared/shen/2026/ultimate/validation_runs/scrna_mvp_validation/h5ad/
```

每个分支至少应包含：

- `run_manifest.json`
- `raw_qc/raw_qc_manifest.json`
- `objects/scrna_mvp.h5ad`
- `results/tables/pseudobulk_counts.tsv`
- `results/tables/pseudobulk_design.tsv`
- `results/tables/pseudobulk_feature_metadata.tsv`
- `results/tables/cell_type_annotation_placeholder.tsv`
- `reports/report.html`

`validated_backend` 只表示真实公开数据或已有验证数据可以作为平台能力证据，不是客户正式交付。正式客户项目必须在生产配置和审批记录齐全后才允许标为 `production_backend`；普通 CLI 不能仅靠 `--analysis-level production_backend` 直接生成正式交付级 manifest。

## Production Readiness And Triage

For a new order, start by giving Codex the raw data paths and analysis request.
Codex can use `triage` to turn that material into a reviewable technical plan:

```bash
ultimate triage --request config/analysis_request.yaml --output-dir triage/<job_id>
```

The triage output should recommend candidate modules, tools, presets, missing
metadata, licensed-tool requirements, and a suggested `project.yaml`. It must not
start heavy computation, quote the project, or mark the job as production.

When reusable forms and catalogs are useful, create an intake package:

```bash
ultimate prepare-intake \
  --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/intake_packages/latest \
  --refresh-audit
```

The package contains:

- `templates/customer_project_intake.tsv`: optional structured fields for raw
  data paths, organism, input type, group design, clinical table, licensed tool
  paths, delivery format, and style choice. The user does not need to pre-select
  every module or backend before Codex triage.
- `module_input_catalog.tsv`: accepted human/mouse raw inputs and required
  sample-sheet columns for every module.
- `figure_style_catalog.tsv`: style keys, colors, and recommended use cases.
- `quote_preflight_checklist.md`: quote-before-run checklist.
- `audit_snapshot/`: production audit, dependency report, order readiness
  checklist, organism support, and next-step notes.

The standard workbench flow is:

1. Provide raw data paths and a natural-language analysis request.
2. Run `ultimate triage` or prepare an intake package to produce a reviewable
   module/tool/preset recommendation.
3. Review `triage/<job_id>/suggested_project.yaml`, `samplesheet_template.tsv`,
   `input_assessment.tsv`, and `handoff_plan.md`.
4. Create a job scaffold with `ultimate prepare-job --config
   triage/<job_id>/suggested_project.yaml --job-id <job_id> --root
   /shared/shen/2026/ultimate`.
5. Run `ultimate preflight --config jobs/<job_id>/config/project.yaml` and resolve missing
   sample columns, paths, references, or licensed tools.
6. Render a style review with `ultimate styles --style <style_key> --output-dir
   <project>/style_review`.
7. Submit raw or large analyses through Slurm, then rebuild reports with
   `ultimate report --run-dir <run_dir>`.
8. Deliver `run_manifest.json`, `raw_qc_manifest.json`, figures, tables,
   objects, `report.html`, and `methods.md`.

To summarize recent triage evidence:

```bash
python /shared/shen/2026/ultimate/01_tools/write_v3_5_intake_ready_report.py \
  --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/reports
```

## Validated Run Handoff

Some production validations are expensive or come from dedicated modality
backends. To include an existing validated run in the unified report without
copying large objects, set one of these in the module config:

```yaml
modules:
  scrna:
    enabled: true
    validated_run_dir: /shared/shen/2026/ultimate/validations/slurm_scrna_nsclc_lambrechts

  spatial:
    enabled: true
    validation:
      run_dir: /shared/shen/2026/ultimate/validations/slurm_spatial_squidpy_visium
```

`ultimate run` reads the source `run_manifest.json`, indexes existing figures,
tables, and objects, writes `validated_artifact_index.tsv`, and includes those
artifacts in the unified Chinese report. The storage policy is reference-first:
large h5ad/RDS/RData files stay where the validated backend wrote them.

## Server Workflow

```bash
cd /shared/shen/2026/ultimate
bash 01_tools/setup_server_env.sh
ultimate init-project --type all --output-dir projects/demo_all --demo-data
ultimate prepare-job --config projects/demo_all/config/project.yaml --job-id demo_all_001 --root /shared/shen/2026/ultimate --run-mode interactive
hpc-sbatch /shared/shen/2026/ultimate/jobs/demo_all_001/config/run_ultimate.sbatch
```

`hpc-sbatch` should submit a ready sbatch script. Do not rely on passing extra
config arguments through the wrapper. For real orders, use `ultimate
prepare-job` first; it creates `jobs/<job_id>/config/run_ultimate.sbatch`,
`production_approval.json`, logs, deliverables, and the fixed output directory
under `/shared/shen/2026/ultimate/jobs/<job_id>/`. Production runs require
`production_approval.json` with `approved=true` before submission.

Small smoke checks, audits, and environment repairs can run directly on the
login node when they are short. Large raw-data analyses, fragments-level
ATAC/Visium production validation, and long downloads should be submitted
through Slurm. Keep large downloads, conda package caches, and analysis outputs
on the remote shared filesystem:

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/singlecell_validation_suite.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/setup_singlecell_envs.sbatch genome_mtdna scrna
hpc-sbatch /shared/shen/2026/ultimate/slurm/tool_trial_batch.sbatch scrna_core
hpc-sbatch /shared/shen/2026/ultimate/slurm/download_public_singlecell_data.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/gapfill_specialty_validation.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/tumor_sc_validation.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/setup_bulk_envs.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/prepare_bulk_public_data.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/bulk_validation_suite.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/validation_index.sbatch
```

The default cache and output locations are under `/shared/shen/2026/ultimate/.conda/`, `/shared/shen/2026/ultimate/public_data/`, `/shared/shen/2026/ultimate/validations/`, and `/shared/shen/2026/ultimate/audits/`.

Every run writes:

- `results/figures/`
- `results/tables/`
- `objects/`
- `reports/`
- `logs/`
- `run_manifest.json`

Missing optional tools are reported in `preflight_manifest.json`, `run_manifest.json`, and the Chinese report instead of failing silently.

## Remote V2 Evidence Loop

Use this loop when refreshing the production evidence snapshot on the server.
The first commands are lightweight metadata checks and may run directly; real
validation or production-style rehearsals still go through Slurm.

```bash
ROOT=/shared/shen/2026/ultimate
PY=$ROOT/.conda/envs/ultimate-core/bin/python
export PYTHONPATH=$ROOT/src

$PY -m pytest -q $ROOT/tests
$PY -m ultimate.cli audit-modules --root $ROOT \
  --output-dir $ROOT/audits/module_standardization_latest
$PY -m ultimate.cli validation-index --root $ROOT \
  --output-dir $ROOT/reports/validation_index
$PY -m ultimate.cli audit-production --root $ROOT \
  --output-dir $ROOT/audits/production_latest
$PY $ROOT/01_tools/storage_audit.py --root $ROOT \
  --output-dir $ROOT/audits/storage_latest --budget-gb 500
$PY $ROOT/01_tools/write_v2_status_report.py --root $ROOT \
  --output-dir $ROOT/audits/production_latest \
  --storage-summary $ROOT/audits/storage_latest/storage_audit_summary.json \
  --pytest-status passed \
  --pytest-note "full test suite passed"
```

Production-style rehearsal jobs live under `jobs/<job_id>/` and should be
submitted with the generated `config/run_ultimate.sbatch`. The refreshed status
bundle should include `reports/validation_index/validation_index.tsv`,
`audits/production_latest/production_audit.tsv`,
`audits/production_latest/production_audit.json`,
`audits/storage_latest/storage_audit_summary.json`, and
the current workbench status report. The helper script may keep its historical
filename for compatibility, but the report should be read as the current
Ultimate workbench status, not as a fixed version-stage label.

## Current Single-Cell Completion Snapshot

The single-cell line is now smoke-validated across the core public/available
modalities. Refresh the capability matrix and the run index with:

```bash
ultimate audit-singlecell --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/audits/singlecell_latest
ultimate validation-index --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/reports/validation_index
ultimate audit-modules --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/audits/module_standardization_latest
ROOT=/shared/shen/2026/ultimate
$ROOT/.conda/envs/ultimate-core/bin/python $ROOT/01_tools/check_validation_manifests.py \
  --root $ROOT \
  --validations-dir $ROOT/validations \
  --output-tsv $ROOT/audits/validation_guard_latest/validation_guard_check.tsv
```

Interpretation policy:

- `ready`: current dependency/data checks for that audit row pass. Use
  `validation-index` and `audit-production` before treating a module as
  validated evidence.
- `module_standardization_matrix.tsv`: checks every module's shared shell
  (`contract/preflight/demo/validate/run/report/handoff/limitations/tests`),
  demo manifest guard fields, handoff template, limitations, and required
  output roots. This is a code/readiness audit only, not a scientific result.
- `validation_guard_check.tsv`: checks validation `run_manifest.json` files for
  explicit `analysis_level`, demo/stub flags, delivery permission, evidence
  permission, and non-delivery reason. It records Slurm metadata when present,
  but short command-line checks are not rejected solely for missing Slurm ids.
  Use `--normalize` only after choosing a backup directory.
- `partial:licensed_optional_missing`: open pipeline is usable; upstream vendor
  tools such as Cell Ranger, Cell Ranger ATAC/ARC, or Space Ranger require a
  user-provided licensed path.
- `partial:data_required` or `partial:dependency_required`: quote and run only
  after the listed data or dependency gap is resolved.

Matrix-level smoke validations are not a promise of best parameters for every
large project. Fragments-level scATAC, full raw FASTQ, and complete Visium
production workflows should be submitted as dedicated Slurm jobs.

## Tool Audit And Lean Trials

The tool registry records every reviewed single-cell / omics package with a final
disposition: keep by default, keep optional, external adapter, reference only,
licensed path only, or rejected and cleaned. Full audit is metadata-only; trial
jobs install and smoke-test one small batch at a time so the platform does not
grow into a fragile mega-environment.

```bash
ultimate audit-tools --root /shared/shen/2026/ultimate
ultimate trial-tools --root /shared/shen/2026/ultimate --batch scrna_core --no-install
ULTIMATE_TRIAL_INSTALL=1 hpc-sbatch /shared/shen/2026/ultimate/slurm/tool_trial_batch.sbatch scrna_core
ultimate prune-tools --root /shared/shen/2026/ultimate
```

The default reusable environments are `ultimate-core`, `ultimate-scrna`,
`ultimate-scrna-heavy`, `ultimate-scrna-r`, `ultimate-workflow`,
`ultimate-scatac-py`, `ultimate-scatac-r`, `ultimate-vdj`, `ultimate-vdj-r`,
`ultimate-spatial-py`, `ultimate-spatial-r`, and `ultimate-genome-mtdna`.
Heavy or conflicting tools are kept optional, with the heaviest single-cell
Python stack isolated in `ultimate-scrna-heavy`, and only promoted after a
smoke run proves they are worth the storage and maintenance cost.

## Figure Styles

Set `report.style` in `config/project.yaml`:

- `soft_color`: 临床期刊版-极光柔彩，默认推荐。
- `okabe_ito`: 色盲友好的经典科研分类色。
- `colorbrewer_set2`: 柔和分类色，适合细胞类型/分组较多的图。
- `nature_modern`: Nature 风格现代科研配色。
- `lancet_clinical`: Lancet 风格临床强化配色。
- `jama_clean`: JAMA 风格清爽克制配色。
- `nejm_warm`: NEJM 风格暖色临床配色。
- `viridis_teal`: Viridis 连续值友好配色。
- `cividis_gold`: Cividis 蓝金连续值配色。
- `clean_clinical`: 清爽蓝灰临床报告配色。
- `warm_academic`: 暖彩学术配色。
- `morandi_clinical`: Morandi 高级临床柔彩，低饱和、留白充足。
- `nord_science`: Nord Science 冷静科研，蓝灰主调。
- `carto_safe`: CARTO Safe 高分辨分类，适合分类较多的图。
- `nejm_blue_red_refined`: NEJM 蓝红精修，适合病例/对照强调。
- `high_contrast_publication`: 高对比出版图，适合打印和投屏。

Use `ultimate styles --style <style_key>` to render one review set into
`style_reviews/v3_6/<style_key>/`, `ultimate styles --output-dir <dir>` to
choose a custom directory, or `ultimate styles --all --output-dir <dir>` to
render all style options before delivery. Use `ultimate styles --list` to print
registered style tokens without rendering figures.
Use `--publication` for full review figures with title, subtitle, legend, grid,
caption and panel labels, or `--minimal` for sparse figures with nonessential
elements switched off. Each review set renders PCA, UMAP, volcano, heatmap, QC
violin/bar, composition bar, dotplot, Kaplan-Meier and spatial scatter examples,
plus `style_review_contact_sheet.png`, `figure_manifest.tsv`,
`style_manifest.json` and `layout_qc.tsv`. Generated review images live in
`style_reviews/` or the requested output directory and are intentionally not
committed to Git.
