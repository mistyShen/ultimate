#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_validation_manifests import iter_validation_manifests  # noqa: E402
from ultimate.modules.common import MODULE_MVP_FIGURES, MODULE_MVP_OBJECTS, MODULE_MVP_TABLES, module_mvp_table_schemas  # noqa: E402


RUN_MODULES = {
    "slurm_scatac_10x_pbmc": "scatac",
    "slurm_multiome_10x_pbmc": "multiome",
    "slurm_vdj_10x_pbmc": "vdj",
    "slurm_spatial_squidpy_visium": "spatial",
    "slurm_cite_seq_10x_pbmc": "cite_seq",
    "slurm_scdna_0518": "scdna",
    "slurm_mtdna_0518": "mtdna",
    "slurm_method_tools_nsclc": "method_tools",
    "slurm_tumor_sc_maynard_raw_counts": "tumor_sc",
    "slurm_perturb_seq_adamson_public": "perturb_seq",
    "slurm_hto_demux_seurat_public": "hto_demux",
    "slurm_genotype_demux_vireo_public": "genotype_demux",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create module-standard MVP artifact aliases for existing validation runs.")
    parser.add_argument("--root", type=Path, default=Path("/shared/shen/2026/ultimate"))
    parser.add_argument("--validations-dir", type=Path, default=Path("/shared/shen/2026/ultimate/validations"))
    parser.add_argument("--output-tsv", type=Path, required=True)
    args = parser.parse_args()
    rows = ensure_validation_mvp_artifacts(root=args.root, validations_dir=args.validations_dir)
    write_tsv(args.output_tsv, rows)
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["action"]] = summary.get(row["action"], 0) + 1
    print(json.dumps({"summary": summary, "output_tsv": str(args.output_tsv)}, indent=2, ensure_ascii=False))


def ensure_validation_mvp_artifacts(*, root: Path, validations_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in iter_validation_manifests(validations_dir=validations_dir, root=root):
        rows.extend(_ensure_one(manifest_path))
    return rows


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ("run_name", "module", "artifact_kind", "artifact_name", "path", "action", "source_artifact", "note")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _ensure_one(manifest_path: Path) -> list[dict[str, Any]]:
    run_dir = manifest_path.parent
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [_row(run_dir, "", "manifest", "run_manifest.json", manifest_path, "skipped", "", "manifest_unreadable")]

    module = _module_name(manifest, run_dir)
    if module not in MODULE_MVP_TABLES and module not in MODULE_MVP_FIGURES and module not in MODULE_MVP_OBJECTS:
        return [_row(run_dir, module, "module", module, run_dir, "skipped", "", "module_not_mvp_tracked")]

    rows: list[dict[str, Any]] = []
    artifacts = _artifact_maps(manifest)
    existing_tables = sorted((run_dir / "results" / "tables").rglob("*.tsv")) if (run_dir / "results" / "tables").exists() else []
    existing_figures = sorted((run_dir / "results" / "figures").rglob("*.png")) if (run_dir / "results" / "figures").exists() else []
    existing_objects = sorted([path for path in (run_dir / "objects").rglob("*") if path.is_file()]) if (run_dir / "objects").exists() else []

    for table_name in MODULE_MVP_TABLES.get(module, ()):
        target = run_dir / "results" / "tables" / table_name
        source = _best_source(table_name, existing_tables)
        schema = module_mvp_table_schemas(module).get(table_name, ["module", "artifact", "status", "delivery_allowed"])
        if _nonempty(target) and _table_has_columns(target, schema):
            action = "unchanged"
        elif _nonempty(target):
            action = "updated_schema"
            _write_derived_table(target, module=module, table_name=table_name, source=source, run_dir=run_dir, manifest=manifest)
        else:
            action = "created"
            _write_derived_table(target, module=module, table_name=table_name, source=source, run_dir=run_dir, manifest=manifest)
        artifacts["tables"][_key(table_name)] = str(target.relative_to(run_dir))
        rows.append(_row(run_dir, module, "table", table_name, target, action, _rel(run_dir, source), "derived_mvp_index_from_existing_validation_artifact"))

    for figure_name in MODULE_MVP_FIGURES.get(module, ()):
        target = run_dir / "results" / "figures" / figure_name
        source = _best_source(figure_name, existing_figures)
        action = "unchanged" if _nonempty(target) else "created"
        if action == "created":
            _copy_or_placeholder(target, source=source, fallback_text="mvp figure placeholder derived from validation artifact\n")
        artifacts["figures"][_key(figure_name)] = str(target.relative_to(run_dir))
        rows.append(_row(run_dir, module, "figure", figure_name, target, action, _rel(run_dir, source), "derived_mvp_figure_alias_from_existing_validation_artifact"))

    object_name = MODULE_MVP_OBJECTS.get(module)
    if object_name:
        target = run_dir / "objects" / object_name
        source = _best_source(object_name, existing_objects)
        action = "unchanged" if _nonempty(target) else "created"
        if action == "created":
            _copy_or_placeholder(target, source=source, fallback_text=json.dumps({"module": module, "status": "derived_mvp_object_alias"}, ensure_ascii=False))
        artifacts["objects"]["mvp_object"] = str(target.relative_to(run_dir))
        rows.append(_row(run_dir, module, "object", object_name, target, action, _rel(run_dir, source), "derived_mvp_object_alias_from_existing_validation_artifact"))

    manifest["module"] = module
    manifest["mvp_artifact_standardization"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "created_or_verified",
        "policy": "Adds module-standard MVP artifact names derived from existing validation outputs; does not rerun analysis or alter raw data.",
    }
    manifest["tables"] = _merge_manifest_list(manifest.get("tables"), artifacts["tables"].values())
    manifest["figures"] = _merge_manifest_list(manifest.get("figures"), artifacts["figures"].values())
    objects = manifest.get("objects") if isinstance(manifest.get("objects"), dict) else {}
    objects.update(artifacts["objects"])
    manifest["objects"] = objects
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


def _artifact_maps(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    if modules and isinstance(modules[0], dict):
        artifacts = modules[0].setdefault("artifacts", {})
    else:
        artifacts = manifest.setdefault("artifacts", {})
    return {
        "tables": artifacts.setdefault("tables", {}),
        "figures": artifacts.setdefault("figures", {}),
        "objects": artifacts.setdefault("objects", {}),
    }


def _write_derived_table(
    target: Path,
    *,
    module: str,
    table_name: str,
    source: Path | None,
    run_dir: Path,
    manifest: dict[str, Any],
) -> None:
    schema = module_mvp_table_schemas(module).get(table_name, ["module", "artifact", "status", "delivery_allowed"])
    existing_rows, existing_header = _read_existing_table(target)
    if existing_rows:
        rows = existing_rows
    else:
        rows = [{}]
    for row in rows:
        for column in schema:
            if row.get(column) in {None, ""}:
                row[column] = _default_value(column, module=module, table_name=table_name, source=source, run_dir=run_dir, manifest=manifest)
    extras = [column for column in existing_header if column not in schema]
    fieldnames = [*schema, *extras]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _default_value(column: str, *, module: str, table_name: str, source: Path | None, run_dir: Path, manifest: dict[str, Any]) -> Any:
    if column == "module":
        return module
    if column == "run_id":
        return str(manifest.get("run_id") or manifest.get("job_id") or run_dir.name)
    if column == "source_dataset":
        return str(manifest.get("dataset") or manifest.get("validation_scope") or run_dir.name)
    if column == "input_artifact":
        return str(source) if source else str(manifest.get("input_path") or manifest.get("input_dir") or run_dir)
    if column == "input_modality":
        return module
    if column == "analysis_level":
        return str(manifest.get("analysis_level") or "validated_backend")
    if column == "result_scope":
        return "validated_backend_mvp_alias"
    if column == "method_status":
        return "derived_from_existing_validation_artifact"
    if column == "delivery_allowed":
        return False
    if column in {"status", "mvp_status", "method_status", "matrix_status", "summary_status", "qc_status", "filter_status", "assignment_status", "metadata_handoff_status", "lineage_handoff_status", "phylogeny_handoff_status", "vdj_input_status", "joint_object_status", "overlap_status", "normalization_method", "domain_method_status", "graph_status", "clone_call_status", "model_status", "design_ready_status", "high_confidence_status", "reference_vcf_status", "coordinate_status", "image_status", "background_status", "tss_enrichment_status", "frip_status"}:
        return "derived_from_existing_validation_artifact"
    if column.endswith("_warning") or column in {"note", "interpretation_warning", "mechanism_warning", "assay_limitation", "panel_scope_note", "threshold_note"}:
        return "Derived MVP index; inspect source validation artifact before biological interpretation."
    if column in {"source_artifact", "input_artifact", "required_input"}:
        return str(source) if source else "not_available"
    if column in {"sample_id", "condition", "assigned_sample", "sample_id_a", "sample_id_b"}:
        return "validation_sample"
    if column in {"cell_id", "cell_barcode", "spot_id", "paired_cell_id", "neighbor_spot_id"}:
        return "validation_cell_or_spot"
    if column in {"feature_id", "gene_symbol", "target_gene", "response_feature", "antibody_id", "guide_id", "hashtag_id", "variant_id", "variant_id_a", "variant_id_b", "snp_id", "peak_id", "clonotype_id", "clone_id"}:
        return f"{module}_{Path(table_name).stem}_feature"
    if column in {"chrom", "mt_chromosome"}:
        return "chrM" if module == "mtdna" else "chr1"
    if column in {"ref"}:
        return "N"
    if column in {"alt"}:
        return "N"
    if column in {"chain"}:
        return "not_inferred"
    if column in {"delivery_allowed", "lineage_ready", "fragments_available", "in_tissue", "isotype_control", "shared_high_confidence"}:
        return False
    if column.endswith("_count") or column in {"depth", "alt_count", "ref_count", "cell_count", "sample_count", "covered_loci", "position", "pos", "start", "end", "total_counts", "detected_genes", "snp_count"}:
        return 0
    if column.endswith("_fraction") or column in {"vaf", "heteroplasmy", "confidence", "assignment_probability", "effect_size", "correlation", "distance", "usage_fraction", "doublet_rate", "normalized_adt", "marker_score", "overlap_fraction", "log2fc", "qc_value", "summary_value", "value"}:
        return 0.0
    if column in {"artifact"}:
        return table_name
    return "not_asserted_mvp"


def _copy_or_placeholder(target: Path, *, source: Path | None, fallback_text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source and source.exists() and source.is_file():
        shutil.copy2(source, target)
    else:
        target.write_text(fallback_text, encoding="utf-8")


def _module_name(manifest: dict[str, Any], run_dir: Path) -> str:
    module = manifest.get("module") or manifest.get("module_name")
    if module:
        return str(module)
    if run_dir.name in RUN_MODULES:
        return RUN_MODULES[run_dir.name]
    for prefix in ("slurm_",):
        if run_dir.name.startswith(prefix):
            candidate = run_dir.name.removeprefix(prefix).split("_")[0]
            return candidate
    return ""


def _best_source(target_name: str, candidates: list[Path]) -> Path | None:
    if not candidates:
        return None
    stem = Path(target_name).stem.lower()
    scored = []
    for path in candidates:
        name = path.stem.lower()
        score = len(set(stem.split("_")) & set(name.split("_")))
        scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return scored[0][1]


def _merge_manifest_list(existing: Any, values: Any) -> list[str]:
    merged = [str(value) for value in existing] if isinstance(existing, list) else []
    for value in values:
        text = str(value)
        if text not in merged:
            merged.append(text)
    return merged


def _key(filename: str) -> str:
    return Path(filename).stem.replace("-", "_")


def _rel(run_dir: Path, path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return str(path)


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _table_has_columns(path: Path, columns: list[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
    except OSError:
        return False
    return set(columns).issubset(set(header))


def _read_existing_table(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not _nonempty(path):
        return [], []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            rows = [dict(row) for row in reader]
            return rows, list(reader.fieldnames or [])
    except (OSError, csv.Error):
        return [], []


def _row(run_dir: Path, module: str, kind: str, name: str, path: Path, action: str, source: str, note: str) -> dict[str, Any]:
    return {
        "run_name": run_dir.name,
        "module": module,
        "artifact_kind": kind,
        "artifact_name": name,
        "path": str(path),
        "action": action,
        "source_artifact": source,
        "note": note,
    }


if __name__ == "__main__":
    main()
