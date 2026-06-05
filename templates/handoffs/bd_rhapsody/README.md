# BD Rhapsody Pipeline Handoff

用途：BD Rhapsody 非 10x scRNA 原始数据交接。

第一版不内置厂商上游流程。推荐先按 BD 官方流程生成表达矩阵、sample/cell metadata 或 h5ad，再进入 `ultimate scrna` 标准下游。

必须记录：

- BD pipeline/version
- sample tag / AbSeq / targeted panel 信息
- genome/reference
- 输出矩阵路径和 checksum
