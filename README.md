# Ultimate Bioinfo Workbench

`ultimate` is a CLI-first, HPC-ready scaffold for reproducible multi-omics analysis delivery under:

```text
/shared/shen/2026/ultimate
```

It supports project templates, input validation, smoke-run analysis artifacts, Chinese reports, and explicit manifests for:

- bulk RNA-seq
- single-cell RNA-seq
- methylation array / beta matrix
- proteomics / metabolomics abundance tables
- public database mining
- WGCNA
- single-gene analysis

The v1 runner provides deterministic smoke analyses for every module so the platform can be tested end to end before heavy R/Bioconductor backends are installed. Formal R entrypoints are kept under `scripts/R/`.

## Quickstart

```bash
python -m pip install -e '.[dev]'
ultimate init-project --type all --output-dir example_projects/demo_all --demo-data
ultimate preflight --config example_projects/demo_all/config/project.yaml
ultimate run --config example_projects/demo_all/config/project.yaml
ultimate report --run-dir example_projects/demo_all/runs/demo_all
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
