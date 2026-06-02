# Ultimate Bioinfo Workbench

`ultimate` is a CLI-first, HPC-ready scaffold for reproducible multi-omics analysis delivery under:

```text
/shared/shen/2026/ultimate
```

It supports project templates, input validation, raw-QC handoff, Python-first
bulk analysis artifacts, Chinese reports, and explicit manifests for:

- bulk RNA-seq
- single-cell RNA-seq
- methylation array / beta matrix
- proteomics / metabolomics abundance tables
- public database mining
- WGCNA
- single-gene analysis

Bulk modules are now Python-first formal backends: RNA-seq, methylation,
proteomics/metabolomics, public cohorts, WGCNA, single-gene analysis, and
clinical association all write module-specific tables, figures, objects, and
manifests. R entrypoints under `scripts/R/` remain optional comparison or
extension hooks.

Single-cell modules remain supported through the existing validation scripts,
environment files, Slurm launchers, and smoke-run integration while the bulk
layer is hardened first.

## Supported Bulk Inputs

- RNA-seq: FASTQ command plans, external tool detection, existing count matrix,
  or generated demo matrix.
- Methylation: beta matrix import; IDAT is recorded as a formal raw contract and
  can be handled by optional parser/backends.
- Proteomics/metabolomics: MaxQuant, Proteome Discoverer, or generic abundance
  tables; raw spectra are out of scope for this Python v1.
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
pytest -q
```

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
hpc-sbatch /shared/shen/2026/ultimate/slurm/download_public_singlecell_data.sbatch
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

## Figure Styles

Set `report.style` in `config/project.yaml`:

- `soft_color`: 柔彩科研配色，默认推荐。
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
