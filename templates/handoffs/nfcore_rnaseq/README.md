# nf-core/rnaseq Handoff Template

用途：把 bulk RNA-seq FASTQ 上游交给开源 nf-core/rnaseq，在 Slurm 上完成 FastQC/MultiQC、trim、STAR/Salmon、featureCounts/quant 输出，再把 raw count matrix 与 MultiQC 报告交回 Ultimate 的 `rnaseq` 模块。

本模板只负责 handoff 契约和可复现命令，不在 `ultimate run` 内自动运行 Nextflow。FASTQ 不直接进入 Ultimate core；FASTQ 必须先经过人工复核的开源 upstream（例如 nf-core/rnaseq）或用户提供的授权 upstream 产出 raw count matrix 后再导入。

## 需要填写

- `samplesheet.csv`：替换为真实 FASTQ 绝对路径；raw data 只读。
- `params.yaml`：替换 `<job_id>`、参考基因组、aligner、outdir。
- `nextflow.config`：按集群分区、容器缓存、资源上限调整。
- `command_plan.sh`：只打印待复核命令，不代表 Ultimate 已执行 upstream。
- `expected_matrix_import.yaml`：记录 nf-core 输出如何转成 Ultimate 下游 `rnaseq` import config。
- 参考资源和容器缓存必须放在 `/shared/shen/2026/ultimate/` 或其子目录，不放 home。
- 运行前必须确认 strandedness/design metadata、参考基因组/注释、容器缓存和 Slurm 分区；不允许在 login node 跑重计算。

## Slurm/Nextflow 命令计划

```bash
set -euo pipefail

JOB_ID=<job_id>
export NXF_HOME=/shared/shen/2026/ultimate/.nextflow
export NXF_WORK=/shared/shen/2026/ultimate/jobs/${JOB_ID}/work/nfcore_rnaseq

nextflow run nf-core/rnaseq \
  -profile apptainer,slurm \
  -c /shared/shen/2026/ultimate/jobs/${JOB_ID}/config/nfcore_rnaseq_nextflow.config \
  -params-file /shared/shen/2026/ultimate/jobs/${JOB_ID}/config/nfcore_rnaseq_params.yaml \
  -work-dir "$NXF_WORK" \
  -resume
```

`command_plan.sh <job_id>` prints the reviewed command plan for copy/review/submission; it is not called by Ultimate and should not be treated as execution evidence.

## Ultimate handback

- counts: `star_salmon/salmon.merged.gene_counts.tsv` 或 `featurecounts/featurecounts.merged.counts.tsv`
- normalized exploratory matrix: TPM/CPM 只能用于 QC/展示，不用于 DESeq2 原始差异。
- MultiQC: `multiqc/star_salmon/multiqc_report.html`
- import config: 按 `expected_matrix_import.yaml` 填写 `modules.rnaseq.input_matrix`、sample metadata 和 design。
- 后续进入 `ultimate run --config ...` 的 `rnaseq` 模块，正式 `production_backend` 必须 approval gate。

## 限制

- 没有生物学重复时不得输出正式 DE 结论。
- TPM/FPKM 不得直接作为 DESeq2/edgeR 输入。
- nf-core/rnaseq 结果是上游证据；Ultimate 下游报告仍需记录 analysis_level、manifest、methods 和复现命令。
- nf-core/rnaseq 是 open-source upstream handoff，不是 Ultimate 内置执行后端；其他授权 upstream 只能走用户提供路径或 handoff，不默认安装、不默认执行。
