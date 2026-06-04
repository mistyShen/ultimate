# nf-core/rnaseq Handoff Template

用途：把 bulk RNA-seq FASTQ 上游交给 nf-core/rnaseq，在 Slurm 上完成 FastQC/MultiQC、trim、STAR/Salmon、featureCounts/quant 输出，再把 count matrix 与 MultiQC 报告交回 Ultimate 的 `rnaseq` 模块。

本模板只负责 handoff 契约和可复现命令，不在 `ultimate run` 内自动运行 Nextflow。

## 需要填写

- `samplesheet.csv`：替换为真实 FASTQ 绝对路径；raw data 只读。
- `params.yaml`：替换 `<job_id>`、参考基因组、aligner、outdir。
- `nextflow.config`：按集群分区、容器缓存、资源上限调整。
- 参考资源和容器缓存必须放在 `/shared/shen/2026/ultimate/` 或其子目录，不放 home。

## Slurm/Nextflow 命令计划

```bash
set -euo pipefail

export NXF_HOME=/shared/shen/2026/ultimate/.nextflow
export NXF_WORK=/shared/shen/2026/ultimate/jobs/<job_id>/work/nfcore_rnaseq

nextflow run nf-core/rnaseq \
  -profile apptainer,slurm \
  -c /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_rnaseq_nextflow.config \
  -params-file /shared/shen/2026/ultimate/jobs/<job_id>/config/nfcore_rnaseq_params.yaml \
  -work-dir "$NXF_WORK" \
  -resume
```

## Ultimate handback

- counts: `star_salmon/salmon.merged.gene_counts.tsv` 或 `featurecounts/featurecounts.merged.counts.tsv`
- normalized exploratory matrix: TPM/CPM 只能用于 QC/展示，不用于 DESeq2 原始差异。
- MultiQC: `multiqc/star_salmon/multiqc_report.html`
- 后续进入 `ultimate run --config ...` 的 `rnaseq` 模块，正式 `production_backend` 必须 approval gate。

## 限制

- 没有生物学重复时不得输出正式 DE 结论。
- TPM/FPKM 不得直接作为 DESeq2/edgeR 输入。
- nf-core/rnaseq 结果是上游证据；Ultimate 下游报告仍需记录 analysis_level、manifest、methods 和复现命令。
