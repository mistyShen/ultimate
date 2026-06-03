# Ultimate Bioinfo Workbench 多组学模块最终实施规划

## 1. 目标定位

Ultimate 的目标是构建一个生产级个人多组学生信分析接单平台，而不是单一 scRNA pipeline，也不是高度自动化的 agent 决策系统。

平台要覆盖从原始数据或标准矩阵输入，到 QC、标准对象/矩阵、分析、统一风格出图、中文报告、manifest、可复现代码包的完整交付链路。

所有模块必须共享统一外壳，但每个模块保留自己的生物学逻辑。scRNA 的成熟路径只能作为工程参考，不能强行套用到 scATAC、VDJ、scDNA、mtDNA、methylation、spatial 等模块。

## 2. 全局执行原则

所有实现和远程操作必须遵守仓库根目录 `AGENTS.md`。

核心约束：

- 所有正式服务器路径必须位于 `/shared/shen/2026/ultimate` 或其子目录。
- 重计算、大型下载、真实数据验证必须通过 Slurm。
- 安装、版本检查、小型 import、pytest、manifest 检查可以命令行执行。
- 不允许在 login node 跑重计算。
- 不允许把项目、数据、结果放在 home 目录。
- 不允许覆盖 raw data。
- 不允许静默失败。
- 不允许硬编码个人临时路径。
- 不允许猜测软件路径、环境名、参考基因组位置。
- 不允许把缺失工具、缺失输入、缺失许可证伪装成成功。
- 不允许把 demo、stub、placeholder、cluster label、假数据、简化统计伪装成正式生物学结论。

所有模块必须显式写入：

- `analysis_level`
- `is_demo`
- `is_stub`
- `delivery_allowed`
- `validation_evidence_allowed`
- `non_delivery_reason`

`analysis_level` 只能是：

- `demo_result`
- `smoke_backend`
- `validated_backend`
- `production_backend`

交付规则：

- `demo_result` 和 `smoke_backend` 不允许作为正式交付。
- `validated_backend` 只代表公开数据或内部验证数据跑通，不等于客户正式交付。
- `production_backend` 必须经过 approval gate，不允许 CLI 直接绕过。

## 3. 平台统一外壳

第一优先级是完成统一外壳，再让所有模块接入。

需要落地的公共能力：

- `analysis_levels.py`：统一 analysis level、delivery guard、stub/demo 判定。
- `approval_gate.py`：统一 production approval JSON 校验。
- `manifest_schema.py`：统一 run/module/raw QC manifest 必填字段和写入逻辑。
- `report_contract.py`：统一中文报告必须展示的字段、限制、跳过原因和复现信息。
- `module_maturity.py`：统一模块成熟度记录。
- `audit-production`：汇总全模块 maturity table。
- `export-repro`：生成可复现代码包、rerun 命令、config snapshot、输入 checksum、软件版本。

统一目录结构：

```text
src/ultimate/modules/<module_name>/
  contract.py
  preflight.py
  demo.py
  validate.py
  run.py
  report.py
  handoff.py
  limitations.py
  tests/
```

当前已有 flat 模块逻辑应逐步迁移，迁移期间保持现有 CLI 行为不破坏。

统一 maturity table 字段：

```text
module_name
input_contract_status
preflight_status
demo_smoke_status
public_validation_status
formal_backend_status
report_status
analysis_level
delivery_allowed
known_limitations
next_required_backend
```

## 4. 模块分组与并行执行

### Lane A：平台与通用交付

职责：

- analysis level
- approval gate
- manifest schema
- report contract
- module maturity audit
- export-repro
- 统一图表模板
- figure/table index
- methods generation
- interactive delivery handoff

重点工具：

- MultiQC
- Quarto
- cellxgene
- Vitessce
- Jupyter Book
- Shiny/Dash handoff

### Lane B：bulk/tabular 模块

模块：

- `rnaseq`
- `methylation`
- `clinical_assoc`
- `publicdb`
- `wgcna`
- `single_gene`
- `functional_state`

第一阶段目标：

- 支持矩阵级输入。
- 做样本/特征 QC。
- 做 design check。
- 输出 PCA、相关性热图、基础统计表、design-ready 表。
- 高级统计或数据库下载先做 handoff。

重点工具：

- nf-core/rnaseq
- DESeq2
- edgeR
- limma
- clusterProfiler
- GSEApy
- GSVA
- AUCell
- UCell
- decoupler-py
- WGCNA
- GEOquery
- TCGAbiolinks
- lifelines
- statsmodels

### Lane C：单细胞表达对象模块

模块：

- `scrna`
- `cite_seq`
- `tumor_sc`
- `method_tools`

第一阶段目标：

- 继续加固 `scrna_mvp`。
- 保证 10x h5、10x mtx、h5ad 输入。
- 输出 QC、聚类、marker、composition、annotation placeholder、pseudobulk design-ready。
- CITE-seq/ADT 做 RNA + antibody matrix MVP。
- tumor_sc 只做 summary/handoff，不自动声称 inferCNV/CopyKAT 正式结论。
- method_tools 做 cellxgene-ready 检查、metadata 脱敏扫描、figure/table index、delivery manifest。

重点工具：

- scanpy
- anndata
- Seurat
- scrublet
- SoupX
- celltypist
- scvi-tools
- decoupler-py
- inferCNV
- CopyKAT
- LIANA
- CellChat
- NicheNet
- dsb
- cellxgene

### Lane D：染色质、多模态、空间模块

模块：

- `scatac`
- `multiome`
- `scepi`
- `spatial`

第一阶段目标：

- scATAC 先做 matrix-level MVP 和 fragments-level handoff。
- Multiome 先做 RNA/ATAC modality check、barcode overlap、h5mu/MuData object 和 handoff。
- SCEpi/methylation 类输入只做 matrix-level MVP，不声称 full single-cell epigenomics。
- Spatial 先做 Visium MVP；Xenium、CosMX、MERSCOPE、Visium HD 先做 handoff contract。

重点工具：

- ArchR
- Signac
- SnapATAC2
- chromVAR
- MACS3
- bedtools
- samtools
- muon
- mudata
- squidpy
- spatialdata
- spatialdata-io
- sopa
- Giotto
- stLearn

### Lane E：免疫组库、扰动、拆样、基因组/线粒体

模块：

- `vdj`
- `perturb_seq`
- `hto_demux`
- `genotype_demux`
- `scdna`
- `mtdna`

第一阶段目标：

- VDJ 支持 Cell Ranger VDJ、AIRR、MiXCR、scirpy/immunarch 输入。
- Perturb-seq 先做 guide QC、guide assignment、perturbation design-ready。
- HTO 先做 matrix-level sample assignment summary。
- Genotype demux 先做 existing result import 和 metadata handoff。
- scDNA 先做 BAM/VCF/table handoff 和 matrix-ready 输出，不做 full phylogeny。
- mtDNA 优先对接 `/shared/shen/2026/0518` 结果做 internal validated_backend。

重点工具：

- scirpy
- immunarch
- MiXCR
- nf-core/airrflow
- tcrdist3
- pertpy
- SCEPTRE
- hashsolo
- cellsnp-lite
- vireo
- souporcell
- demuxlet
- popscle
- MissionBio mosaic
- bcftools
- samtools
- pysam
- MitoTrace
- mitoClone2

## 5. GitHub 工具审计与留存策略

大纲中提到的所有 GitHub 项目和关键工具必须进入 `tool_registry.tsv/json`。

每个工具记录：

- tool name
- GitHub 或官方 URL
- module
- purpose
- install method
- conda/pip/R/Bioconductor/container source
- expected environment
- estimated size
- license status
- default/optional/handoff/reference disposition
- smoke command
- validation data
- known limitations
- final decision

处置类型：

- `default_backend`：稳定、常用、安装可靠、能直接提高交付质量。
- `optional_backend`：有价值但重依赖、低频或数据要求特殊。
- `handoff_adapter`：生产中常用，但第一版只生成配置、样本表、输入输出模板。
- `licensed_path_detection`：Cell Ranger、Space Ranger、CIBERSORT 等只检测用户提供路径。
- `reference_only`：只参考工程结构、参数设计、报告组织。
- `rejected_cleaned`：试用后不适合，清理并记录原因。

工具安装原则：

- 优先 mamba/conda。
- 可使用镜像站。
- 小批量安装和 import 测试。
- 每批结束记录空间变化。
- 通过 smoke 后保留。
- 不符合接单需求、维护弱、环境污染大或重复度高的工具要清理。
- 尽量复用环境，不为每个工具单独开环境。

## 6. Execution Waves

### Wave 0：统一外壳

目标：

- 完成公共 schema、approval gate、manifest、report、maturity audit。
- 锁定所有模块输出目录和必须字段。
- 保证现有 scRNA MVP 和 CLI 不被破坏。

验收：

- 公共 pytest 通过。
- `audit-production` 能输出全模块 maturity table。
- demo/stub 不可能被标成可交付。

### Wave 1：全部模块骨架

目标：

- 20 个模块全部补齐 contract、preflight、handoff、limitations、report、pytest。
- 每个模块都有明确 input contract 和 known limitations。
- 每个模块都有 handoff template。

验收：

- 每个模块至少能生成 demo/smoke manifest 和 report。
- 这一阶段只允许 `demo_result` 或 `smoke_backend`。

### Wave 2：全部模块 MVP

目标：

- 每个模块至少能跑一个最小 demo/smoke。
- 生成规定的 tables、figures、objects、report、methods、logs。
- 高级工具未正式接入时只写 handoff，不写 fully automatic。

验收：

- 每个模块都有 pytest 检查关键输出。
- `audit-production` 能区分 ready、partial、missing、licensed_required、data_required。

### Wave 3：GitHub 工具审计与保留

目标：

- 对大纲中所有工具逐项审计。
- 按小批量安装/试用。
- 保留值得进入生产流程的工具。
- 清理不符合需求的工具。

验收：

- `tool_registry.tsv/json` 覆盖全部工具。
- 每个工具都有最终处置。
- 默认环境不过度臃肿。

### Wave 4：validated_backend

目标：

- 每个模块绑定一个公开或内部 validation 数据。
- 大型验证走 Slurm。
- 验证成功后才允许 `analysis_level=validated_backend`。

验收：

- 每个模块至少有 public/internal validation plan。
- 成功验证的模块生成完整 manifest、QC manifest、report、methods、tables、figures、objects。
- 验证失败或缺数据必须写明原因，不能创建假 evidence。

### Wave 5：正式接单闭环

目标：

- 所有模块接入 `ultimate run --config ...`。
- 所有模块接入 `ultimate preflight`。
- 所有模块接入 `ultimate export-repro`。
- 正式客户任务必须通过 approval gate 才能成为 `production_backend`。

验收：

- 交付目录包含：
  - `report.html`
  - `methods.md`
  - `figures/`
  - `tables/`
  - `objects/`
  - `run_manifest.json`
  - QC manifest
  - `delivery_index.tsv`
  - `reproducible_code/`
  - `rerun.sh`
  - software versions
  - input checksums

## 7. 每个模块的最低验收标准

每个模块必须有：

- input contract
- preflight
- demo/smoke
- public 或 internal validation plan
- run manifest
- raw/module QC manifest
- tables
- figures
- objects 或明确 object handoff
- report.html
- methods.md
- logs
- pytest
- known limitations
- handoff template

每个模块不得：

- 把 demo/stub 当正式结果。
- 把 handoff 写成已自动完成。
- 把 placeholder 写成生物学结论。
- 缺输入、缺工具、缺许可证时静默成功。
- 用错误的数据类型套用其他模块逻辑。

## 8. 测试策略

本地测试：

- 配置解析。
- input contract 校验。
- preflight 成功/失败路径。
- analysis level guard。
- approval gate。
- manifest 字段。
- report 必须显示 `analysis_level` 和限制。
- demo/stub 不可交付。
- 每个模块关键输出存在性检查。

远端轻量检查：

- 依赖路径。
- 环境版本。
- import smoke。
- handoff 模板存在。
- Slurm 脚本语法和输出目录。

Slurm 验证：

- bulk/tabular suite。
- single-cell object suite。
- chromatin/multiome/spatial suite。
- immune/genome/demux suite。
- scRNA MVP regression。

审计验收：

- `audit-production` 能汇总所有模块。
- 任意 demo、stub、placeholder、缺授权、缺数据、缺工具都必须在 maturity table 中显示为不可交付。

## 9. 预计工期

现实估计：

- 1-2 天：统一外壳、全模块骨架、pytest、maturity audit 初版。
- 3-5 天：常用接单模块进入可用 MVP，包括 bulk RNA、scRNA、VDJ、scATAC、Multiome、Spatial、CITE-seq、mtDNA。
- 7-14 天：工具审计、环境瘦身、公开/内部 validated_backend、Slurm smoke、交付闭环。

时间最大不确定性来自：

- mamba/conda/R/Bioconductor 依赖冲突。
- 公开数据下载速度。
- HPC 队列等待。
- scATAC/Multiome/Spatial/VDJ/mtDNA 专项工具验证复杂度。

## 10. 当前执行优先级

推荐立即执行顺序：

1. 固化公共 schema、approval gate、manifest、report contract。
2. 建立模块 maturity audit。
3. 生成所有模块目录骨架和最低 contract。
4. 给所有模块补 pytest。
5. 补全 GitHub tool registry。
6. 先做矩阵级 MVP，不抢跑 full advanced backend。
7. 按 lane 提交 Slurm smoke。
8. 再逐步补 validated_backend。

核心原则：

先保证每个模块不会乱说话；再保证每个模块能跑通；最后才追求每个模块高级分析自动化。
