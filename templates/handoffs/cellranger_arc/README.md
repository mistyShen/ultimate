# Cell Ranger ARC Handoff Template

用途：用用户提供的 Cell Ranger ARC 处理 10x Multiome RNA+ATAC FASTQ，交回 Ultimate `multiome`。

## 命令计划

```bash
set -euo pipefail

CELLRANGER_ARC=/path/to/cellranger-arc
REFERENCE=/shared/shen/2026/ultimate/references/10x/refdata-cellranger-arc-GRCh38-2024-A
LIBRARIES=/shared/shen/2026/ultimate/jobs/<job_id>/config/cellranger_arc_libraries.csv
OUT_ROOT=/shared/shen/2026/ultimate/jobs/<job_id>/runs/cellranger_arc

mkdir -p "$OUT_ROOT"
cd "$OUT_ROOT"
"$CELLRANGER_ARC" count \
  --id=<sample_id> \
  --reference="$REFERENCE" \
  --libraries="$LIBRARIES" \
  --localcores=16 \
  --localmem=96
```

## Ultimate handback

- `outs/filtered_feature_bc_matrix.h5`
- `outs/atac_fragments.tsv.gz` and `.tbi`
- `outs/web_summary.html`

Multiome 必须检查 RNA/ATAC barcode overlap；peak-gene linkage 是统计关联，不是实验证明。
