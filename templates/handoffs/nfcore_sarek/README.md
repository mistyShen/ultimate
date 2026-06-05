# nf-core/sarek Handoff

用途：WGS/WES/panel 的 SNV、Indel、CNV、LOH、tumor-normal variant calling 外部生产流程交接。

本模板只负责生成可复查的 Nextflow/Slurm 运行计划。`ultimate` 第一版不自动运行 `nf-core/sarek`，下游只读取整理后的 VCF、CNV segment、cell/sample-level matrix 或报告表。

运行原则：

- 原始 FASTQ/BAM 只读。
- 大下载、比对、variant calling 必须通过 Slurm。
- 参考基因组、panel BED、known sites 和 tumor-normal 配对表必须在运行前人工确认。
- `sarek` 结果进入 `scdna` 或 `tumor_sc` 模块时，只能作为 genome-level evidence 或 handoff，不可和 scRNA 推断 CNV 混写。
