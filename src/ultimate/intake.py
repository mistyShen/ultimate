from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.constants import MODULE_ORDER, SUPPORTED_ORGANISMS
from ultimate.plot_style import available_styles
from ultimate.production_audit import run_production_audit
from ultimate.raw_qc import RAW_CONTRACTS


def prepare_intake_package(*, root: Path, output_dir: Path | None = None, refresh_audit: bool = False) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "intake_packages" / "latest").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_dir = root / "audits" / "production_readiness_latest"
    if refresh_audit or not (audit_dir / "production_audit.json").exists():
        audit_manifest = run_production_audit(root=root, output_dir=audit_dir)
    else:
        audit_manifest = json.loads((audit_dir / "production_audit.json").read_text(encoding="utf-8"))

    templates_dir = Path(__file__).resolve().parents[2] / "templates" / "intake"
    copied_templates = _copy_templates(templates_dir, output_dir)
    module_catalog = _write_module_catalog(output_dir)
    style_catalog = _write_style_catalog(output_dir)
    quickstart = _write_quickstart(output_dir, root, audit_manifest)
    quote_checklist = _write_quote_checklist(output_dir, audit_manifest)
    copied_audit = _copy_audit_files(audit_manifest, output_dir)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "output_dir": str(output_dir),
        "organisms": sorted(SUPPORTED_ORGANISMS),
        "production_summary": audit_manifest.get("summary", {}),
        "templates": copied_templates,
        "module_catalog": str(module_catalog),
        "style_catalog": str(style_catalog),
        "quickstart": str(quickstart),
        "quote_checklist": str(quote_checklist),
        "copied_audit_files": copied_audit,
    }
    manifest_path = output_dir / "intake_package_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _copy_templates(template_dir: Path, output_dir: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    if not template_dir.exists():
        return copied
    target = output_dir / "templates"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(template_dir.iterdir()):
        if path.is_file():
            dest = target / path.name
            shutil.copy2(path, dest)
            copied[path.name] = str(dest)
    return copied


def _write_module_catalog(output_dir: Path) -> Path:
    rows = []
    for module in MODULE_ORDER:
        contract = RAW_CONTRACTS[module]
        rows.append(
            {
                "module": module,
                "accepted_species": ",".join(sorted(SUPPORTED_ORGANISMS)),
                "accepted_raw_inputs": ",".join(contract.input_types),
                "required_sample_columns": ",".join(contract.required_columns),
                "standard_output": contract.output_kind,
                "default_open_toolchain": ",".join(contract.open_replacements),
            }
        )
    path = output_dir / "module_input_catalog.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _write_style_catalog(output_dir: Path) -> Path:
    rows = []
    for key, style in available_styles().items():
        rows.append(
            {
                "style_key": key,
                "style_cn": style["style_cn"],
                "style_id": style["style_id"],
                "primary": style["primary"],
                "case": style["case"],
                "control": style["control"],
                "accent": style["accent"],
                "recommended_use": _style_use_case(key),
            }
        )
    path = output_dir / "figure_style_catalog.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _style_use_case(style_key: str) -> str:
    return {
        "soft_color": "默认推荐；彩色但不刺眼，适合医学报告和论文初稿。",
        "clean_clinical": "更克制的蓝灰风格，适合正式临床队列交付。",
        "warm_academic": "暖彩学术风格，适合汇报和图文展示。",
        "nature_modern": "偏 Nature 系现代科研配色。",
        "lancet_clinical": "偏 Lancet 系红蓝临床强调。",
        "jama_clean": "偏 JAMA 系清爽克制。",
        "nejm_warm": "偏 NEJM 系暖色临床。",
        "okabe_ito": "色盲友好分类配色。",
        "colorbrewer_set2": "柔和多分类配色。",
        "viridis_teal": "连续值友好，适合空间/评分热度图。",
        "cividis_gold": "蓝金连续值友好，适合色觉无障碍。",
    }.get(style_key, "通用科研图配色。")


def _write_quickstart(output_dir: Path, root: Path, audit_manifest: dict[str, Any]) -> Path:
    path = output_dir / "README_intake_quickstart.md"
    text = "\n".join(
        [
            "# Ultimate 接单包快速使用",
            "",
            "## 适用范围",
            "",
            "- 物种：human, mouse",
            f"- 当前生产审计：`{audit_manifest.get('summary', {})}`",
            "- 正式 raw 或大样本任务走 Slurm；报价前 preflight、风格预览、小矩阵 smoke 可直接 CLI。",
            "",
            "## 标准流程",
            "",
            "```bash",
            "ultimate init-project --type <analysis_type> --output-dir <project_dir>",
            "ultimate preflight --config <project_dir>/config/project.yaml",
            "ultimate styles --style soft_color --output-dir <project_dir>/style_review",
            "hpc-sbatch /shared/shen/2026/ultimate/slurm/ultimate_run.sbatch <project_dir>/config/project.yaml",
            "```",
            "",
            "## 接单前必收信息",
            "",
            "- `templates/customer_project_intake.tsv`：客户项目信息和分析要求。",
            "- `module_input_catalog.tsv`：每个模块接受的输入类型和样本表字段。",
            "- `figure_style_catalog.tsv`：可选绘图风格和颜色。",
            "- `order_readiness_checklist.tsv`：每个模块的最低交付物和计算策略。",
            "",
            f"服务器平台根目录：`{root}`",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")
    return path


def _write_quote_checklist(output_dir: Path, audit_manifest: dict[str, Any]) -> Path:
    path = output_dir / "quote_preflight_checklist.md"
    lines = [
        "# 报价前检查清单",
        "",
        "- [ ] 物种确认：human 或 mouse。",
        "- [ ] 数据类型和模块确认：见 `module_input_catalog.tsv`。",
        "- [ ] 样本表列完整：sample_id/condition/input_path 或模块特殊列。",
        "- [ ] 分组、批次、配对、协变量和临床表已确认。",
        "- [ ] raw 文件路径存在且只读，不覆盖原始数据。",
        "- [ ] 参考资源路径确认：human=GRCh38, mouse=GRCm39，或客户自定义。",
        "- [ ] 授权工具路径确认：Cell Ranger/Space Ranger/CIBERSORT 如需使用必须由用户提供。",
        "- [ ] 风格确认：见 `figure_style_catalog.tsv`，默认 `soft_color`。",
        "- [ ] 交付格式确认：HTML/Markdown/PNG/PDF/SVG/RDS/RData/h5ad。",
        "- [ ] 运行策略确认：正式任务通过 Slurm，小型 preflight/style/smoke 可 CLI。",
        "",
        "## 当前平台审计",
        "",
        f"- summary: `{audit_manifest.get('summary', {})}`",
        f"- capability_matrix: `{audit_manifest.get('capability_matrix', 'not_recorded')}`",
        f"- order_readiness_checklist: `{audit_manifest.get('order_readiness_checklist', 'not_recorded')}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _copy_audit_files(audit_manifest: dict[str, Any], output_dir: Path) -> dict[str, str]:
    target = output_dir / "audit_snapshot"
    target.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for key in ("capability_matrix", "organism_support", "style_options", "dependency_report", "order_readiness_checklist", "next_steps", "manifest_path"):
        value = audit_manifest.get(key)
        if value and Path(value).exists():
            dest = target / Path(value).name
            shutil.copy2(value, dest)
            copied[key] = str(dest)
    return copied
