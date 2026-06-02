# Ultimate 接单交付检查清单

## 报价前

- [ ] 确认物种为 human 或 mouse。
- [ ] 确认数据类型和 raw input type。
- [ ] 收到样本表、分组信息、批次信息和临床表（如有）。
- [ ] 执行 `ultimate preflight --config config/project.yaml`。
- [ ] 把缺失依赖、授权工具、参考资源和预计耗时写入报价说明。

## 分析中

- [ ] 每次运行有 `run_manifest.json`。
- [ ] 每个模块有 `raw_qc_manifest.json`。
- [ ] 每个模块有标准矩阵/对象交接文件。
- [ ] 缺失可选依赖必须写入 manifest 和报告，不能静默跳过。
- [ ] 正式大计算通过 Slurm 提交。

## 交付前

- [ ] 中文 `report.html` 和 `methods.md` 已生成。
- [ ] `results/figures/` 至少包含 QC、PCA/UMAP、差异图、热图和模块专项图。
- [ ] `results/tables/` 包含差异结果、QC 表、标准矩阵和模块专项表。
- [ ] `objects/` 包含可复现对象或交接对象。
- [ ] 风格已按客户选择渲染，颜色和排版通过人工检查。
