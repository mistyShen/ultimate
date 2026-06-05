# MiXCR Handoff

用途：TCR/BCR/VDJ FASTQ 到 clonotype/AIRR-like table 外部 adapter。

第一版 `vdj` 模块优先读取 Cell Ranger VDJ、AIRR table、MiXCR 输出或 scirpy/immunarch 对象；MiXCR 全流程按项目使用外部二进制/容器。

示例输出进入 `ultimate vdj` 前应至少包含：

- clonotype id
- chain
- productive flag
- CDR3 nucleotide/amino acid
- V/J gene
- sample/cell barcode
