# Cell Ranger VDJ Handoff Template

用途：用用户提供的 Cell Ranger VDJ 对 10x VDJ FASTQ 计数，交回 Ultimate `vdj` 模块做 clone summary、sharing、V/J usage。

## 命令计划

```bash
set -euo pipefail

CELLRANGER=/path/to/cellranger
REFERENCE=/shared/shen/2026/ultimate/references/10x/refdata-cellranger-vdj-GRCh38-alts-ensembl-7.1.0
FASTQS=/shared/shen/2026/ultimate/jobs/<job_id>/raw_links/fastqs
OUT_ROOT=/shared/shen/2026/ultimate/jobs/<job_id>/runs/cellranger_vdj

mkdir -p "$OUT_ROOT"
cd "$OUT_ROOT"
"$CELLRANGER" vdj \
  --id=<sample_id> \
  --reference="$REFERENCE" \
  --fastqs="$FASTQS" \
  --sample=<sample_id> \
  --localcores=12 \
  --localmem=64
```

## Ultimate handback

- `outs/filtered_contig_annotations.csv`
- `outs/clonotypes.csv`
- `outs/consensus_annotations.csv`
- `outs/web_summary.html`

clonotype 相同不等于抗原相同；抗原特异性不能自动断言。
