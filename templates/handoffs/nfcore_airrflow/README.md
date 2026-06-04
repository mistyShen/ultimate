# nf-core/airrflow Handoff Template

用途：把 TCR/BCR/AIRR FASTQ 或 rearrangement table 上游交给 nf-core/airrflow，生成 AIRR 标准表、克隆型和多样性输出，再交回 Ultimate 的 `vdj` 模块做 clonotype summary、clone sharing、V/J usage 和报告。

本模板是 `handoff_adapter`，不表示 Ultimate 已自动运行 nf-core/airrflow。

## 需要填写

- `samplesheet.csv`：样本、receptor 类型、FASTQ 或已有 AIRR 表路径。
- `params.yaml`：物种、链类型、输出目录和资源。
- `nextflow.config`：Slurm executor 与 Apptainer 缓存路径。

## 命令计划

```bash
set -euo pipefail

export NXF_HOME=/shared/shen/2026/ultimate/.nextflow
export NXF_WORK=/shared/shen/2026/ultimate/jobs/<job_id>/work/nfcore_airrflow

nextflow run nf-core/airrflow \
  -profile apptainer,slurm \
  -c /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_airrflow_nextflow.config \
  -params-file /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_airrflow_params.yaml \
  -work-dir "$NXF_WORK" \
  -resume
```

## Ultimate handback

- AIRR rearrangement table
- clonotype table
- diversity summary
- V/J usage table
- 后续进入 `vdj` 模块；clonotype 相同不等于抗原相同，抗原特异性不得自动断言。
