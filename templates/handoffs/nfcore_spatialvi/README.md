# nf-core/spatialvi Handoff Template

用途：参考 nf-core/spatialvi 组织 10x Visium 空间转录组上游/下游流程，生成空间 count、QC 和报告，再交回 Ultimate `spatial`。

本模板是 `handoff_adapter`，不表示 Ultimate 自动运行 nf-core/spatialvi。

## 命令计划

```bash
set -euo pipefail

export NXF_HOME=/shared/shen/2026/ultimate/.nextflow
export NXF_WORK=/shared/shen/2026/ultimate/jobs/<job_id>/work/nfcore_spatialvi

nextflow run nf-core/spatialvi \
  -profile apptainer,slurm \
  -c /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_spatialvi_nextflow.config \
  -params-file /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_spatialvi_params.yaml \
  -work-dir "$NXF_WORK" \
  -resume
```

## Ultimate handback

- Space Ranger compatible output directory
- spatial count matrix
- spatial image/coordinate files
- MultiQC or pipeline report

空间通讯和邻域分析是推断，不能写成实验验证。
