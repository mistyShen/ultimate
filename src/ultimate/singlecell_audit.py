from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Capability:
    key: str
    title_cn: str
    env_name: str
    alternate_env_paths: tuple[str, ...] = ()
    python_packages: tuple[str, ...] = ()
    r_packages: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    data_checks: tuple[str, ...] = ()
    licensed_tools: tuple[str, ...] = ()


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "scrna",
        "单细胞转录组 scRNA-seq",
        "ultimate-scrna",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scrna-r",
            "/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311",
            "/share/home/nshen/miniconda3/envs/nsclc_sc",
        ),
        python_packages=("scanpy", "anndata", "scvi", "celltypist", "decoupler"),
        r_packages=("Seurat", "SingleR", "GSVA", "AUCell", "WGCNA", "clusterProfiler"),
        data_checks=("nsclc_h5ad",),
    ),
    Capability(
        "scatac",
        "单细胞 ATAC-seq",
        "ultimate-scatac-multiome",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scatac-py",
            "{root}/.conda/envs/ultimate-scatac-r",
            "{root}/.conda/envs/ultimate-genome-mtdna",
        ),
        python_packages=("snapatac2",),
        r_packages=("Signac", "Seurat", "chromVAR", "GenomicRanges"),
        commands=("macs2", "bedtools", "samtools"),
        data_checks=("public_scatac",),
        licensed_tools=("cellranger-atac",),
    ),
    Capability(
        "multiome",
        "单细胞多组学 Multiome",
        "ultimate-scatac-multiome",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scatac-py",
            "{root}/.conda/envs/ultimate-scatac-r",
            "/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311",
            "{root}/.conda/envs/ultimate-genome-mtdna",
        ),
        python_packages=("muon", "snapatac2"),
        r_packages=("Signac", "Seurat", "chromVAR"),
        commands=("macs2", "bedtools", "samtools"),
        data_checks=("public_multiome",),
        licensed_tools=("cellranger-arc",),
    ),
    Capability(
        "vdj",
        "单细胞免疫组库 VDJ/TCR/BCR",
        "ultimate-vdj",
        alternate_env_paths=("{root}/.conda/envs/ultimate-vdj-r",),
        python_packages=("scirpy", "dandelion"),
        r_packages=("scRepertoire", "immunarch"),
        data_checks=("public_vdj",),
    ),
    Capability(
        "scdna",
        "单细胞 DNA-seq / 基因组",
        "ultimate-genome-mtdna",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-core",
            "/share/home/nshen/miniconda3/envs/star_env",
            "/share/home/nshen/miniconda3/envs/scfusion_final",
        ),
        python_packages=("pandas", "matplotlib"),
        commands=("samtools", "bcftools", "bwa", "bedtools"),
        data_checks=("dna_bam_0518",),
    ),
    Capability(
        "mtdna",
        "单细胞线粒体基因组 / mtDNA",
        "ultimate-genome-mtdna",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-core",
            "/share/home/nshen/miniconda3/envs/star_env",
            "/share/home/nshen/miniconda3/envs/scfusion_final",
        ),
        python_packages=("pandas", "matplotlib"),
        commands=("samtools", "bcftools"),
        data_checks=("mtdna_0518",),
    ),
    Capability(
        "scepi",
        "单细胞表观遗传组",
        "ultimate-scatac-multiome",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scatac-py",
            "{root}/.conda/envs/ultimate-scatac-r",
            "{root}/.conda/envs/ultimate-genome-mtdna",
        ),
        python_packages=("snapatac2",),
        r_packages=("Signac", "chromVAR", "minfi", "GenomicRanges"),
        commands=("samtools", "bedtools", "macs2"),
        data_checks=("public_scatac",),
    ),
    Capability(
        "cite_seq",
        "单细胞蛋白组 / CITE-seq / REAP-seq",
        "ultimate-scrna",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scrna-r",
            "/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311",
        ),
        python_packages=("muon", "scanpy"),
        r_packages=("Seurat", "dsb"),
        data_checks=("public_cite_seq",),
    ),
    Capability(
        "spatial",
        "单细胞空间组学 / 空间转录组",
        "ultimate-spatial",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-spatial-py",
            "{root}/.conda/envs/ultimate-spatial-r",
            "/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311",
        ),
        python_packages=("squidpy", "spatialdata", "scanpy"),
        r_packages=("SpatialExperiment", "TENxVisiumData", "Seurat"),
        data_checks=("public_spatial",),
        licensed_tools=("spaceranger",),
    ),
    Capability(
        "functional_state",
        "单细胞代谢 / 功能状态",
        "ultimate-scrna",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scrna-r",
            "/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311",
        ),
        python_packages=("scanpy", "decoupler"),
        r_packages=("GSVA", "AUCell", "Seurat"),
        data_checks=("nsclc_h5ad",),
    ),
    Capability(
        "tumor_sc",
        "肿瘤单细胞常见专项",
        "ultimate-scrna",
        alternate_env_paths=(
            "{root}/.conda/envs/ultimate-scrna-r",
            "/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311",
        ),
        python_packages=("scanpy", "celltypist", "decoupler"),
        r_packages=("infercnv", "copykat", "Seurat", "survival"),
        data_checks=("nsclc_h5ad",),
    ),
    Capability(
        "clinical_assoc",
        "跨样本 / 临床关联分析",
        "ultimate-core",
        alternate_env_paths=("{root}/.conda/envs/ultimate-scrna-r",),
        python_packages=("pandas", "numpy", "matplotlib"),
        r_packages=("survival", "GSVA", "survminer"),
        data_checks=("public_geo_validation",),
    ),
    Capability(
        "method_tools",
        "方法学 / 工具类分析",
        "ultimate-core",
        alternate_env_paths=("{root}/.conda/envs/ultimate-scrna-r",),
        python_packages=("pandas", "numpy", "matplotlib", "jinja2"),
        r_packages=("Seurat", "SingleR"),
        commands=("snakemake",),
        data_checks=("ultimate_demo",),
        licensed_tools=("cellranger", "cellranger-atac", "spaceranger"),
    ),
)


def run_singlecell_audit(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "singlecell").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    dependency_rows: list[dict[str, Any]] = []
    for capability in CAPABILITIES:
        checks = _check_capability(root, capability)
        rows.append(_capability_row(capability, checks))
        dependency_rows.extend(_dependency_rows(capability, checks))

    capability_path = output_dir / "capability_matrix.tsv"
    dependency_path = output_dir / "dependency_report.tsv"
    manifest_path = output_dir / "audit_manifest.json"
    html_path = output_dir / "report.html"
    markdown_path = output_dir / "report.md"
    _write_tsv(capability_path, rows)
    _write_tsv(dependency_path, dependency_rows)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "capability_matrix": str(capability_path),
        "dependency_report": str(dependency_path),
        "report_html": str(html_path),
        "report_md": str(markdown_path),
        "summary": _summarize(rows),
        "capabilities": rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_reports(html_path=html_path, markdown_path=markdown_path, rows=rows, manifest=manifest)
    return manifest


def _check_capability(root: Path, capability: Capability) -> dict[str, Any]:
    env_paths = _env_paths(root, capability)
    python_paths = [env_path / "bin" / "python" for env_path in env_paths]
    rscript_paths = [env_path / "bin" / "Rscript" for env_path in env_paths]
    bin_dirs = [env_path / "bin" for env_path in env_paths]
    checks = {
        "env_path": str(env_paths[0]),
        "env_paths": [str(path) for path in env_paths],
        "env_exists": any(env_path.exists() for env_path in env_paths),
        "reusable_envs": [str(path) for path in env_paths[1:] if path.exists()],
        "python_packages": _check_python_packages(python_paths, capability.python_packages),
        "r_packages": _check_r_packages(rscript_paths, capability.r_packages),
        "commands": _check_commands(bin_dirs, capability.commands),
        "data": _check_data(root, capability.data_checks),
        "licensed_tools": {tool: _command_available(tool, bin_dirs) for tool in capability.licensed_tools},
    }
    return checks


def _env_paths(root: Path, capability: Capability) -> list[Path]:
    primary = root / ".conda" / "envs" / capability.env_name
    env_paths = [primary]
    for env_path in capability.alternate_env_paths:
        env_paths.append(Path(env_path.format(root=root)))
    return env_paths


def _check_python_packages(python_paths: list[Path], packages: tuple[str, ...]) -> dict[str, bool]:
    if not packages:
        return {}
    found = {pkg: False for pkg in packages}
    code = "import importlib.util\nfor p in %r:\n print(p, bool(importlib.util.find_spec(p)), sep='\\t')" % (list(packages),)
    for python_path in python_paths:
        if not python_path.exists():
            continue
        completed = subprocess.run([str(python_path), "-c", code], text=True, capture_output=True, check=False)
        for line in completed.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[1] == "True":
                found[parts[0]] = True
    return found


def _check_r_packages(rscript_paths: list[Path], packages: tuple[str, ...]) -> dict[str, bool]:
    if not packages:
        return {}
    found = {pkg: False for pkg in packages}
    code = "pkgs <- c(%s); inst <- rownames(installed.packages()); cat(paste(pkgs, pkgs %%in%% inst, sep='\\t'), sep='\\n')" % (
        ",".join(json.dumps(pkg) for pkg in packages)
    )
    for rscript_path in rscript_paths:
        if not rscript_path.exists():
            continue
        completed = subprocess.run([str(rscript_path), "-e", code], text=True, capture_output=True, check=False)
        for line in completed.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[1] == "TRUE":
                found[parts[0]] = True
    return found


def _check_commands(bin_dirs: list[Path], commands: tuple[str, ...]) -> dict[str, bool]:
    return {command: _command_available(command, bin_dirs) for command in commands}


def _command_available(command: str, bin_dirs: list[Path]) -> bool:
    return any((bin_dir / command).exists() for bin_dir in bin_dirs) or shutil.which(command) is not None


def _check_data(root: Path, checks: tuple[str, ...]) -> dict[str, bool]:
    paths = {
        "nsclc_h5ad": Path("/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Lambrechts_all_harmonized.h5ad"),
        "dna_bam_0518": Path("/shared/shen/2026/0518/analysis_dna/bam/A_121/A_121.sorted.bam"),
        "mtdna_0518": Path("/shared/shen/2026/0518/analysis_mtDNA/singlecell_mgatk_like/variants/high_confidence_informative_variants.tsv"),
        "public_geo_validation": root / "projects" / "public_validation_geo" / "runs" / "public_validation_geo" / "run_manifest.json",
        "ultimate_demo": root / "projects" / "core_env_demo" / "runs" / "core_env_demo" / "run_manifest.json",
        "public_scatac": root / "public_data" / "scatac" / "manifest.json",
        "public_multiome": root / "public_data" / "multiome" / "manifest.json",
        "public_vdj": root / "public_data" / "vdj" / "manifest.json",
        "public_spatial": root / "public_data" / "spatial" / "manifest.json",
        "public_cite_seq": root / "public_data" / "cite_seq" / "manifest.json",
    }
    return {check: _data_check_passed(paths.get(check, root / check)) for check in checks}


def _data_check_passed(path: Path) -> bool:
    if not path.exists():
        return False
    if path.name == "manifest.json":
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        validation_status = str(manifest.get("validation_status", "")).lower()
        download_status = str(manifest.get("download_status", "")).lower()
        return validation_status in {"ready", "validated"} or download_status in {"ready", "validated"}
    return True


def _capability_row(capability: Capability, checks: dict[str, Any]) -> dict[str, Any]:
    py_missing = [k for k, v in checks["python_packages"].items() if not v]
    r_missing = [k for k, v in checks["r_packages"].items() if not v]
    command_missing = [k for k, v in checks["commands"].items() if not v]
    data_missing = [k for k, v in checks["data"].items() if not v]
    licensed_missing = [k for k, v in checks["licensed_tools"].items() if not v]
    missing = py_missing + r_missing + command_missing
    if not missing and not data_missing:
        status = "ready"
    elif not missing and data_missing:
        status = "partial:data_required"
    elif missing and not data_missing:
        status = "partial:dependency_required"
    else:
        status = "missing"
    if licensed_missing and status == "ready":
        status = "partial:licensed_optional_missing"
    return {
        "capability": capability.key,
        "title_cn": capability.title_cn,
        "env_name": capability.env_name,
        "status": status,
        "python_missing": ",".join(py_missing),
        "r_missing": ",".join(r_missing),
        "command_missing": ",".join(command_missing),
        "data_missing": ",".join(data_missing),
        "licensed_optional_missing": ",".join(licensed_missing),
        "env_exists": str(checks["env_exists"]),
        "reusable_envs": ";".join(checks["reusable_envs"]),
    }


def _dependency_rows(capability: Capability, checks: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for kind in ("python_packages", "r_packages", "commands", "data", "licensed_tools"):
        for name, available in checks[kind].items():
            rows.append(
                {
                    "capability": capability.key,
                    "title_cn": capability.title_cn,
                    "dependency_type": kind,
                    "name": name,
                    "available": str(bool(available)),
                    "env_name": capability.env_name,
                    "env_path": checks["env_path"],
                }
            )
    return rows


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        summary[status] = summary.get(status, 0) + 1
    return summary


def _write_reports(*, html_path: Path, markdown_path: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    md_lines = [
        "# Ultimate 单细胞能力审计报告",
        "",
        f"生成时间：{manifest['generated_at']}",
        f"根目录：`{manifest['root']}`",
        "",
        "| 功能 | 状态 | 缺失依赖 | 缺失数据 | 授权工具 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        deps = ",".join(filter(None, [row["python_missing"], row["r_missing"], row["command_missing"]]))
        md_lines.append(
            f"| {row['title_cn']} | `{row['status']}` | {deps or '-'} | {row['data_missing'] or '-'} | {row['licensed_optional_missing'] or '-'} |"
        )
    markdown_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    html_rows = "\n".join(
        "<tr>"
        f"<td>{row['title_cn']}</td><td><code>{row['status']}</code></td>"
        f"<td>{row['python_missing'] or '-'}</td><td>{row['r_missing'] or '-'}</td>"
        f"<td>{row['command_missing'] or '-'}</td><td>{row['data_missing'] or '-'}</td>"
        f"<td>{row['licensed_optional_missing'] or '-'}</td>"
        "</tr>"
        for row in rows
    )
    html_path.write_text(
        f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Ultimate 单细胞能力审计</title>
<style>body{{font-family:sans-serif;margin:32px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:6px}}th{{background:#f6f8fa}}</style>
</head><body><h1>Ultimate 单细胞能力审计报告</h1><p>生成时间：{manifest['generated_at']}</p>
<table><thead><tr><th>功能</th><th>状态</th><th>缺 Python</th><th>缺 R</th><th>缺命令</th><th>缺数据</th><th>授权工具</th></tr></thead>
<tbody>{html_rows}</tbody></table></body></html>""",
        encoding="utf-8",
    )
