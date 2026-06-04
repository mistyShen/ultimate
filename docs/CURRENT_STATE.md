# Ultimate 当前状态基线

更新时间：2026-06-04

## 服务器基线

- 正式根目录：`/shared/shen/2026/ultimate`
- 当前体积约：`27G`
- 已完成 validation guard 标准化：`/shared/shen/2026/ultimate/audits/validation_guard_latest/validation_guard_check.tsv`
- 验证总索引：`/shared/shen/2026/ultimate/reports/validation_index/validation_index.tsv`
- 生产审计：`/shared/shen/2026/ultimate/audits/production_readiness_latest/production_audit.json`
- 肿瘤单细胞专项验证：`/shared/shen/2026/ultimate/validations/slurm_tumor_sc_maynard_raw_counts`

## 已通过状态

- 22 个模块标准外壳均为 `ready`。
- 严格 guard 后 production audit 当前为 `ready_basic=19`，`partial:validation_manifest_not_ready=3`。
- `perturb_seq`、`hto_demux`、`genotype_demux` 当前只有 synthetic/demo validation，按交付护栏不得作为 validated_backend 证据。
- validation guard 当前无 non-ready 项；validation-index 当前汇总 31 个验证 run。
- final acceptance 当前通过 13 项，1 项 partial，原因是 synthetic/demo validation 不再抬升为正式验证证据。
- `tumor_sc` 已完成 NSCLC raw-count Slurm 专项验证，`analysis_level=validated_backend`，`delivery_allowed=false`。
- `slurm_tumor_sc_maynard_raw_counts` 基于 Maynard raw h5ad 抽样 3000 细胞，输出 16 个表、4 张图、1 个 h5ad 对象，并纳入 validation index 和 production audit。
- inferCNV、CopyKAT、Seurat 在 `ultimate-scrna-r` 中可用；Maynard 输入通过 raw integer count gate，CopyKAT/inferCNV 完整后端当前被人工放行 gate 阻断，阻断原因写入 `backend_attempts.tsv`。
- inferCNV gene order 已通过 Lambrechts 参考 h5ad 映射，29634 个基因中 22138 个完成染色体坐标映射。
- 单细胞能力矩阵仍保留授权工具边界：Cell Ranger、Space Ranger、CIBERSORT 等只做路径检测或 adapter，不默认声明为 fully automatic。

## 当前边界

- `validated_backend` 只代表公开数据或内部验证数据跑通，不等于客户正式交付。
- `production_backend` 必须经过 approval gate。
- demo/synthetic/smoke 结果不得作为正式交付证据。
- 高级工具若只完成输入准备或可用性检测，必须写成 `handoff`、`optional backend` 或 `adapter`。

## 下一推进点

- 下一优先级：把 CopyKAT 或 inferCNV 从“raw-count 输入准备完成”推进到完整 backend 执行，建议先小抽样 CopyKAT，再扩展到 inferCNV。
- 备选方向：scATAC/Multiome fragments-level 验证、CellChat/NicheNet 通讯专项、clinical association/survival 模板。
- 真实或较重计算继续通过 Slurm 提交，不在登录节点运行。
