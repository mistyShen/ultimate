# nf-core/scrnaseq Handoff Template

用途：把 10x/Smart-seq 等 scRNA FASTQ 上游交给 nf-core/scrnaseq，在 Slurm 上生成表达矩阵和 MultiQC 报告，再由 `ultimate validate-scrna` 或正式 `ultimate run` 接下游分析。

本模板只记录 handoff 契约，不在 `ultimate validate-scrna` 中自动运行 nf-core 全流程。

## 需要填写

- `samplesheet.csv`：替换为真实 FASTQ 绝对路径，原始数据只读。
- `params.yaml`：替换 `<job_id>`、参考基因组和资源限制。
- 容器/缓存目录建议放在 `/shared/shen/2026/ultimate/containers/` 和 `/shared/shen/2026/ultimate/work/`，不要放 home。

## Slurm/Nextflow 命令计划

```bash
set -euo pipefail

export NXF_HOME=/shared/shen/2026/ultimate/.nextflow
export NXF_WORK=/shared/shen/2026/ultimate/jobs/<job_id>/work/nfcore_scrnaseq

nextflow run nf-core/scrnaseq \
  -profile apptainer,slurm \
  -params-file /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_scrnaseq_params.yaml \
  -work-dir "$NXF_WORK" \
  -resume
```

## 交接输出

- nf-core 输出矩阵：记录到 `analysis_request.yaml` 的 `raw.output_matrix/object`。
- MultiQC HTML：纳入 Ultimate delivery index。
- 后续下游：用 `ultimate validate-scrna --analysis-level production_backend` 或统一 `ultimate run --config ...` 继续。
