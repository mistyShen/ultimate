# Parse Biosciences Pipeline Handoff

用途：Parse Evercode 非 10x scRNA 原始数据交接。

第一版不内置厂商上游流程。推荐先按 Parse 官方流程生成 gene expression matrix、cell metadata 或 h5ad，再进入 `ultimate scrna` 标准下游。

必须记录：

- Parse kit/version
- sample/barcode mapping
- genome/reference
- 官方 pipeline 命令和版本
- 输出矩阵路径和 checksum
