from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ultimate.constants import MODULE_ORDER, MODULE_SPECS, PROJECT_TYPES, SUPPORTED_ORGANISMS


@dataclass(frozen=True)
class LoadedConfig:
    path: Path
    base_dir: Path
    raw: dict[str, Any]


def load_config(config_path: Path) -> LoadedConfig:
    config_path = config_path.resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"Config must be a mapping: {config_path}")
    normalized = normalize_config(raw, config_path.parent)
    return LoadedConfig(path=config_path, base_dir=config_path.parent, raw=normalized)


def normalize_config(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    normalized = deepcopy(config)
    project = normalized.setdefault("project", {})
    project.setdefault("name", "ultimate_project")
    project.setdefault("organism", "human")
    project.setdefault("output_dir", "../runs/ultimate_project")
    project.setdefault("server_root", "/shared/shen/2026/ultimate")
    project.setdefault("run_mode", "interactive")

    organism = str(project["organism"]).lower()
    if organism not in SUPPORTED_ORGANISMS:
        raise ValueError(f"Unsupported organism {organism!r}; expected one of {sorted(SUPPORTED_ORGANISMS)}")
    project["organism"] = organism
    project["output_dir"] = str(resolve_path(base_dir, project["output_dir"]))

    normalized.setdefault("design", {})
    normalized.setdefault("resources", {})
    report = normalized.setdefault("report", {})
    report.setdefault("style", "soft_color")
    report.setdefault("layout", "clinical_report")
    report.setdefault("figure_format", "png")
    report.setdefault("dpi", 180)
    normalized.setdefault("samples", {})
    normalized.setdefault("modules", {})

    analysis_request = normalized.get("analysis_request") or project.get("analysis_request")
    if isinstance(analysis_request, (str, Path)):
        normalized["analysis_request"] = str(resolve_path(base_dir, analysis_request))
    elif isinstance(analysis_request, dict):
        normalized["analysis_request"] = analysis_request

    for module_name in list(normalized["modules"]):
        if module_name not in MODULE_SPECS:
            raise ValueError(f"Unsupported module {module_name!r}; expected one of {list(MODULE_SPECS)}")

    for module_name in MODULE_ORDER:
        module_cfg = normalized["modules"].setdefault(module_name, {"enabled": False})
        module_cfg.setdefault("enabled", False)
        for path_key in ("input_matrix", "samplesheet", "input_path", "clinical_table", "signature_matrix", "validated_run_dir", "validation_run_dir"):
            if module_cfg.get(path_key):
                module_cfg[path_key] = str(resolve_path(base_dir, module_cfg[path_key]))
        validation_cfg = module_cfg.get("validation")
        if isinstance(validation_cfg, dict) and validation_cfg.get("run_dir"):
            validation_cfg["run_dir"] = str(resolve_path(base_dir, validation_cfg["run_dir"]))
        raw_cfg = module_cfg.get("raw")
        if isinstance(raw_cfg, dict):
            for path_key in (
                "samplesheet",
                "output_matrix",
                "output_object",
                "input_path",
                "fastq_1",
                "fastq_2",
                "fastq_dir",
                "bcl_dir",
                "fragments",
                "peak_matrix",
                "matrix_path",
                "matrix_dir",
                "feature_matrix",
                "count_matrix",
                "idat_dir",
                "visium_dir",
                "spatial_dir",
                "spatialdata_zarr",
                "sopa_project",
                "cellranger_out",
                "cellranger_atac_out",
                "cellranger_arc_out",
                "cellranger_vdj_out",
                "spaceranger_out",
                "airr_table",
                "clonotypes",
                "contig_annotations",
                "guide_counts",
                "guide_assignments",
                "hashtag_counts",
                "adt_counts",
                "bam",
                "vcf",
                "barcode_file",
                "variant_table",
                "cnv_table",
                "demux_result",
                "reference",
                "gtf",
                "genome_dir",
                "clinical_table",
                "signature_matrix",
            ):
                if raw_cfg.get(path_key):
                    raw_cfg[path_key] = str(resolve_path(base_dir, raw_cfg[path_key]))

    samples = normalized.get("samples") or {}
    if isinstance(samples, dict) and samples.get("samplesheet"):
        samples["samplesheet"] = str(resolve_path(base_dir, samples["samplesheet"]))
    return normalized


def resolve_path(base_dir: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base_dir / candidate).resolve()


def output_dir(config: dict[str, Any]) -> Path:
    return Path(config["project"]["output_dir"])


def enabled_modules(config: dict[str, Any]) -> list[str]:
    modules = config.get("modules") or {}
    return [name for name in MODULE_ORDER if bool((modules.get(name) or {}).get("enabled", False))]


def dump_yaml(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return path


def load_samples(config: dict[str, Any]) -> pd.DataFrame:
    samples = config.get("samples") or {}
    if isinstance(samples, dict) and samples.get("samplesheet"):
        return pd.read_csv(samples["samplesheet"], sep=None, engine="python")
    if isinstance(samples, dict) and isinstance(samples.get("items"), list):
        return pd.DataFrame(samples["items"])
    if isinstance(samples, list):
        return pd.DataFrame(samples)
    return pd.DataFrame()


def load_analysis_request(config: dict[str, Any]) -> dict[str, Any]:
    request = config.get("analysis_request")
    if isinstance(request, dict):
        return request
    if not request:
        return {}
    path = Path(str(request))
    if not path.exists():
        return {"source": str(path), "status": "missing"}
    if path.suffix.lower() in {".yaml", ".yml"}:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {"source": str(path), "content": data}
    if path.suffix.lower() == ".json":
        import json

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {"source": str(path), "content": data}
    return {"source": str(path), "format": path.suffix.lstrip(".") or "text", "notes": path.read_text(encoding="utf-8")}


def validate_project_type(project_type: str) -> str:
    if project_type not in PROJECT_TYPES:
        raise ValueError(f"Unsupported project type {project_type!r}; expected one of {PROJECT_TYPES}")
    return project_type
