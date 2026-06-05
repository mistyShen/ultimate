# bcl-convert Handoff

用途：Illumina BCL 到 FASTQ demultiplex。

这是授权/用户自带软件路径检测模板，不作为默认依赖安装。运行前必须确认 RunFolder、SampleSheet、index 设置和输出目录。

示例命令：

```bash
bcl-convert --bcl-input-directory /shared/path/to/runfolder \
  --sample-sheet /shared/path/to/SampleSheet.csv \
  --output-directory /shared/shen/2026/ultimate/external/bcl_convert/fastq
```
