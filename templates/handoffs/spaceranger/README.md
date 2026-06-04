# Space Ranger Handoff Template

用途：用用户提供的 Space Ranger 处理 10x Visium/Visium HD FASTQ 与组织图像，输出 Space Ranger `outs/`，再交回 Ultimate `spatial`。

Space Ranger 是授权/用户自带工具，Ultimate 只做路径检测、命令模板和输出读取。

## 命令计划

```bash
set -euo pipefail

SPACERANGER=/path/to/spaceranger
TRANSCRIPTOME=/shared/shen/2026/ultimate/references/10x/refdata-gex-GRCh38-2024-A
FASTQS=/shared/shen/2026/ultimate/jobs/<job_id>/raw_links/fastqs
IMAGE=/shared/shen/2026/ultimate/jobs/<job_id>/raw_links/tissue_image.tif
OUT_ROOT=/shared/shen/2026/ultimate/jobs/<job_id>/runs/spaceranger

mkdir -p "$OUT_ROOT"
cd "$OUT_ROOT"
"$SPACERANGER" count \
  --id=<sample_id> \
  --transcriptome="$TRANSCRIPTOME" \
  --fastqs="$FASTQS" \
  --sample=<sample_id> \
  --image="$IMAGE" \
  --slide=<slide_id> \
  --area=<area_id> \
  --localcores=16 \
  --localmem=96
```

## Ultimate handback

- `outs/filtered_feature_bc_matrix.h5`
- `outs/spatial/tissue_positions*.csv`
- `outs/spatial/scalefactors_json.json`
- `outs/spatial/tissue_hires_image.png`
- `outs/web_summary.html`

Visium spot 不是单细胞；deconvolution 依赖 reference，必须在报告写限制。
