# bcl2fastq Handoff

用途：旧版 Illumina BCL 到 FASTQ demultiplex。

这是授权/用户自带软件路径检测模板，不作为默认依赖安装。优先使用 `bcl-convert`；老数据或老仪器项目再使用本模板。

示例命令：

```bash
bcl2fastq --runfolder-dir /shared/path/to/runfolder \
  --sample-sheet /shared/path/to/SampleSheet.csv \
  --output-dir /shared/shen/2026/ultimate/external/bcl2fastq/fastq
```
