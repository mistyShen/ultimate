# mtdna handoff template

本目录记录 `mtdna` 模块的外部成熟工具 handoff 约定。第一阶段只生成配置、样本表、输入输出契约和复现命令，不把未接入的高级工具写成 fully automatic。

## 必须记录

- input contract
- tool or workflow version
- command plan
- expected inputs
- expected outputs
- Slurm submission policy
- license or user-provided path requirement
- known limitations

## 交付规则

`demo_result` 和 `smoke_backend` 不能交付；`validated_backend` 只代表公开或内部验证证据；`production_backend` 必须通过 approval gate。
