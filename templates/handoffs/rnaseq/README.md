# rnaseq handoff template

本目录记录 `rnaseq` 模块的外部成熟工具 handoff 约定。第一阶段只生成配置、样本表、输入输出契约和复现命令，不把未接入的高级工具写成 fully automatic。

FASTQ 输入必须先走 upstream handoff：开源路线可用 `nfcore_rnaseq` 模板，授权或用户自带路线必须记录软件路径、版本、命令和输出。Ultimate core 只接收复核后的 raw count matrix、sample metadata、design 和 MultiQC/QC evidence，不直接把 FASTQ 当作已执行差异分析结果。

## 必须记录

- input contract
- tool or workflow version
- command plan
- expected inputs
- expected outputs
- Slurm submission policy
- license or user-provided path requirement
- known limitations
- expected matrix import config

## 交付规则

`demo_result` 和 `smoke_backend` 不能交付；`validated_backend` 只代表公开或内部验证证据；`production_backend` 必须通过 approval gate。
