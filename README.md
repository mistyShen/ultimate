# Ultimate Bioinfo Workbench

`ultimate` is a CLI-first, HPC-ready scaffold for reproducible human/mouse
multi-omics analysis delivery under:

```text
/shared/shen/2026/ultimate
```

It supports customer intake packages, project templates, input validation,
raw-QC handoff, validated-run handoff, selectable figure styles, Chinese
reports, and explicit manifests for the current human/mouse order-ready module set:

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
ultimate styles --style soft_color --output-dir example_projects/style_review
ultimate audit-production --root /shared/shen/2026/ultimate
ultimate prepare-intake --root /shared/shen/2026/ultimate --output-dir /shared/shen/2026/ultimate/intake_packages/latest --refresh-audit
ultimate audit-tools --root /shared/shen/2026/ultimate
ultimate trial-tools --root /shared/shen/2026/ultimate --batch scrna_core --no-install
pytest -q
```

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

## Production Readiness And Intake

For a new customer order, start with an intake package:

```bash
ultimate prepare-intake \
  --root /shared/shen/2026/ultimate \
  --output-dir /shared/shen/2026/ultimate/intake_packages/latest \
  --refresh-audit
```

The package contains:

- `templates/customer_project_intake.tsv`: customer project fields, organism,
  module, input type, group design, optional clinical table, licensed tool
  paths, delivery format, and style choice.
- `module_input_catalog.tsv`: accepted human/mouse raw inputs and required
  sample-sheet columns for every module.
- `figure_style_catalog.tsv`: style keys, colors, and recommended use cases.
- `quote_preflight_checklist.md`: quote-before-run checklist.
- `audit_snapshot/`: production audit, dependency report, order readiness
  checklist, organism support, and next-step notes.

The standard order flow is:

1. Fill the intake template and create a module-specific project with
   `ultimate init-project`.
2. Run `ultimate preflight --config config/project.yaml` and resolve missing
   sample columns, paths, references, or licensed tools.
3. Render a style review with `ultimate styles --style <style_key> --output-dir
   <project>/style_review`.
4. Submit raw or large analyses through Slurm, then rebuild reports with
   `ultimate report --run-dir <run_dir>`.
5. Deliver `run_manifest.json`, `raw_qc_manifest.json`, figures, tables,
   objects, `report.html`, and `methods.md`.

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
hpc-sbatch /shared/shen/2026/ultimate/slurm/ultimate_run.sbatch projects/demo_all/config/project.yaml
```

Heavy validation, package installation, and public-data preparation should be submitted through Slurm. Keep large downloads, conda package caches, and analysis outputs on the remote shared filesystem:

```bash
hpc-sbatch /shared/shen/2026/ultimate/slurm/singlecell_validation_suite.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/setup_singlecell_envs.sbatch genome_mtdna scrna
hpc-sbatch /shared/shen/2026/ultimate/slurm/tool_trial_batch.sbatch scrna_core
hpc-sbatch /shared/shen/2026/ultimate/slurm/download_public_singlecell_data.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/gapfill_specialty_validation.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/setup_bulk_envs.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/prepare_bulk_public_data.sbatch
hpc-sbatch /shared/shen/2026/ultimate/slurm/bulk_validation_suite.sbatch
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

Use `ultimate styles --output-dir <dir>` to render one review set, or
`ultimate styles --all --output-dir <dir>` to render all style options before delivery.
Generated review images live in `style_reviews/` or the requested output
directory and are intentionally not committed to Git.
