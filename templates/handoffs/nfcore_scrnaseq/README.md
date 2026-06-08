# nf-core/scrnaseq Handoff Template

用途：把 barcode-based scRNA FASTQ 上游交给开源 nf-core/scrnaseq，在 Slurm 上生成表达矩阵和 MultiQC 报告，再由 `ultimate validate-scrna` 或正式 `ultimate run` 接下游分析。

本模板只记录 handoff 契约，不在 `ultimate validate-scrna` 或 `ultimate run` 中自动运行 nf-core 全流程。FASTQ 不直接进入 Ultimate core；FASTQ 必须先经过人工复核的开源 upstream（例如 nf-core/scrnaseq）或用户提供的授权 upstream（例如 Cell Ranger）产出 matrix/object 后再导入。

## 需要填写

- `samplesheet.csv`：替换为真实 FASTQ 绝对路径，原始数据只读。
- `params.yaml`：替换 `<job_id>`、参考基因组和资源限制。
- `nextflow.config`：按集群分区、容器运行时和缓存路径调整。
- `command_plan.sh`：只打印待复核命令，不代表 Ultimate 已执行 upstream。
- `expected_matrix_import.yaml`：记录 nf-core 输出如何转成 Ultimate 下游 `scrna` import config。
- 容器/缓存目录建议放在 `/shared/shen/2026/ultimate/containers/` 和 `/shared/shen/2026/ultimate/work/`，不要放 home。
- 运行前必须确认 protocol、expected_cells、参考基因组/注释、容器缓存和 Slurm 分区；不允许在 login node 跑重计算。

## Slurm/Nextflow 命令计划

```bash
set -euo pipefail

JOB_ID=<job_id>
export NXF_HOME=/shared/shen/2026/ultimate/.nextflow
export NXF_WORK=/shared/shen/2026/ultimate/jobs/${JOB_ID}/work/nfcore_scrnaseq

nextflow run nf-core/scrnaseq \
  -profile apptainer,slurm \
  -c /shared/shen/2026/ultimate/jobs/${JOB_ID}/config/nfcore_scrnaseq_nextflow.config \
  -params-file /shared/shen/2026/ultimate/jobs/${JOB_ID}/config/nfcore_scrnaseq_params.yaml \
  -work-dir "$NXF_WORK" \
  -resume
```

`command_plan.sh <job_id>` prints the reviewed command plan for copy/review/submission; it is not called by Ultimate and should not be treated as execution evidence.

## 交接输出

- nf-core 输出矩阵或对象：按 `expected_matrix_import.yaml` 填写到 Ultimate 下游 config 的 `modules.scrna.input_path`。
- MultiQC HTML：纳入 Ultimate delivery index。
- 后续下游：用 `ultimate validate-scrna` 或统一 `ultimate run --config ...` 继续。
- 如需正式交付级 `production_backend`，必须提供通过审批的 production approval JSON；不要只靠命令行参数把普通输入标成正式交付。

## 边界

- nf-core/scrnaseq 是 open-source upstream handoff，不是 Ultimate 内置执行后端。
- Cell Ranger、BD Rhapsody、Parse 或其他 vendor FASTQ upstream 只能走用户授权路径或 handoff，不默认安装、不默认执行。
- cluster label、annotation placeholder、communication/velocity/regulatory handoff 不能伪装成正式 cell type 或机制结论。
