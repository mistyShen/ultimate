# Cell Ranger ATAC Handoff Template

用途：用用户提供的 Cell Ranger ATAC 处理 10x scATAC FASTQ，输出 fragments、peak matrix 和 summary，再交回 Ultimate `scatac` / `scepi`。

## 命令计划

```bash
set -euo pipefail

CELLRANGER_ATAC=/path/to/cellranger-atac
REFERENCE=/shared/shen/2026/ultimate/references/10x/refdata-cellranger-arc-GRCh38-2024-A
FASTQS=/shared/shen/2026/ultimate/jobs/<job_id>/raw_links/fastqs
OUT_ROOT=/shared/shen/2026/ultimate/jobs/<job_id>/runs/cellranger_atac

mkdir -p "$OUT_ROOT"
cd "$OUT_ROOT"
"$CELLRANGER_ATAC" count \
  --id=<sample_id> \
  --reference="$REFERENCE" \
  --fastqs="$FASTQS" \
  --sample=<sample_id> \
  --localcores=16 \
  --localmem=96
```

## Ultimate handback

- `outs/fragments.tsv.gz` and `.tbi`
- `outs/filtered_peak_bc_matrix.h5`
- `outs/peaks.bed`
- `outs/web_summary.html`

没有 fragments 文件时，Ultimate 不声称完成 TSS/FRiP/peak calling。
