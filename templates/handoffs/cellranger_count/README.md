# Cell Ranger Count Handoff Template

用途：在用户提供合法 Cell Ranger 路径时，把 10x scRNA FASTQ 计数交给 Cell Ranger `count`，再把 `outs/filtered_feature_bc_matrix.h5` 或 matrix 目录交回 Ultimate `scrna`。

Cell Ranger 是授权/用户自带工具，Ultimate 只做路径检测和命令模板，不自动安装。

## 命令计划

```bash
set -euo pipefail

CELLRANGER=/path/to/cellranger
TRANSCRIPTOME=/shared/shen/2026/ultimate/references/10x/refdata-gex-GRCh38-2024-A
FASTQS=/shared/shen/2026/ultimate/jobs/<job_id>/raw_links/fastqs
OUT_ROOT=/shared/shen/2026/ultimate/jobs/<job_id>/runs/cellranger_count

mkdir -p "$OUT_ROOT"
cd "$OUT_ROOT"
"$CELLRANGER" count \
  --id=<sample_id> \
  --transcriptome="$TRANSCRIPTOME" \
  --fastqs="$FASTQS" \
  --sample=<sample_id> \
  --localcores=16 \
  --localmem=96
```

## Ultimate handback

- `outs/filtered_feature_bc_matrix.h5`
- `outs/raw_feature_bc_matrix.h5`
- `outs/web_summary.html`
- `outs/metrics_summary.csv`

cluster label 不能伪装成 cell type；正式交付仍由 Ultimate 下游 report 和 manifest 控制。
