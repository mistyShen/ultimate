# Cell Ranger Multi / Feature Barcode Handoff Template

用途：处理 10x multi config，包括 GEX + ADT/CITE-seq、GEX + VDJ 或 multiplexing。Ultimate 只调用用户提供的 Cell Ranger 路径，结果交回 `scrna`、`cite_seq`、`vdj` 或 `hto_demux` 模块。

## 命令计划

```bash
set -euo pipefail

CELLRANGER=/path/to/cellranger
MULTI_CONFIG=/shared/shen/2026/ultimate/jobs/<job_id>/config/cellranger_multi_config.csv
OUT_ROOT=/shared/shen/2026/ultimate/jobs/<job_id>/runs/cellranger_multi

mkdir -p "$OUT_ROOT"
cd "$OUT_ROOT"
"$CELLRANGER" multi \
  --id=<sample_id> \
  --csv="$MULTI_CONFIG" \
  --localcores=16 \
  --localmem=96
```

## Ultimate handback

- GEX: `outs/per_sample_outs/<sample>/count/sample_filtered_feature_bc_matrix.h5`
- ADT: feature-barcode H5 中 Antibody Capture features
- VDJ: `filtered_contig_annotations.csv` 和 `clonotypes.csv`
- HTO: multiplexing assignment 或 hashtag count matrix

ADT 不是全蛋白组；抗体 panel 决定解释范围。
