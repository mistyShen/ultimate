#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
from io import StringIO
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a GEO series matrix into Ultimate matrix/sample/config inputs.")
    parser.add_argument("--series-matrix", required=True, type=Path)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--max-per-group", type=int, default=12)
    parser.add_argument("--top-variable-features", type=int, default=500)
    args = parser.parse_args()

    manifest = prepare_geo_project(
        series_matrix=args.series_matrix,
        project_dir=args.project_dir,
        project_name=args.project_name,
        max_per_group=args.max_per_group,
        top_variable_features=args.top_variable_features,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def prepare_geo_project(
    *,
    series_matrix: Path,
    project_dir: Path,
    project_name: str | None,
    max_per_group: int,
    top_variable_features: int,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    data_dir = project_dir / "data"
    sample_dir = project_dir / "samples"
    config_dir = project_dir / "config"
    for directory in (data_dir, sample_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True)

    metadata, table = _read_geo_series_matrix(series_matrix)
    samples = _build_samples(metadata)
    selected_samples = _select_balanced_samples(samples, max_per_group=max_per_group)
    matrix = table.set_index("ID_REF")[selected_samples["sample_id"].tolist()]
    matrix = matrix.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    matrix = _select_top_variable(matrix, top_n=top_variable_features)
    matrix = matrix.reset_index().rename(columns={"ID_REF": "feature_id"})

    matrix_path = data_dir / "publicdb_matrix.tsv"
    samples_path = sample_dir / "samples.tsv"
    config_path = config_dir / "project.yaml"
    matrix.to_csv(matrix_path, sep="\t", index=False)
    selected_samples.to_csv(samples_path, sep="\t", index=False)

    resolved_project_name = project_name or project_dir.name
    config = _build_config(
        project_name=resolved_project_name,
        matrix_path="../data/publicdb_matrix.tsv",
        samples_path="../samples/samples.tsv",
    )
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)

    manifest = {
        "project_name": resolved_project_name,
        "series_matrix": str(series_matrix),
        "project_dir": str(project_dir),
        "config_path": str(config_path),
        "samples_path": str(samples_path),
        "matrix_path": str(matrix_path),
        "n_samples_total": int(samples.shape[0]),
        "n_samples_selected": int(selected_samples.shape[0]),
        "condition_counts": selected_samples["condition"].value_counts().to_dict(),
        "n_features_selected": int(matrix.shape[0]),
    }
    (project_dir / "geo_prepare_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _read_geo_series_matrix(path: Path) -> tuple[dict[str, list[list[str]]], pd.DataFrame]:
    metadata: dict[str, list[list[str]]] = {}
    table_lines: list[str] = []
    in_table = False
    with _open_text(path) as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line == "!series_matrix_table_begin":
                in_table = True
                continue
            if line == "!series_matrix_table_end":
                break
            if in_table:
                table_lines.append(raw_line)
                continue
            if line.startswith("!Sample_"):
                row = next(csv.reader([line], delimiter="\t"))
                metadata.setdefault(row[0], []).append(row[1:])
    if not table_lines:
        raise ValueError(f"No expression table found in {path}")
    table = pd.read_csv(
        StringIO("".join(table_lines)),
        sep="\t",
        low_memory=False,
    )
    table.columns = [str(column).strip().strip('"') for column in table.columns]
    if "ID_REF" not in table.columns:
        table = table.rename(columns={table.columns[0]: "ID_REF"})
    return metadata, table


def _build_samples(metadata: dict[str, list[list[str]]]) -> pd.DataFrame:
    accessions = _first(metadata, "!Sample_geo_accession")
    titles = _first(metadata, "!Sample_title")
    sources = _first(metadata, "!Sample_source_name_ch1")
    characteristics = metadata.get("!Sample_characteristics_ch1", [])
    rows: list[dict[str, Any]] = []
    for idx, accession in enumerate(accessions):
        source = _safe_get(sources, idx)
        title = _safe_get(titles, idx)
        condition = "normal" if "normal" in source.lower() or "normal" in title.lower() else "tumor"
        row = {
            "sample_id": accession,
            "condition": condition,
            "cohort_id": "GSE10072",
            "source_name": source,
            "title": title,
            "batch": "GEO",
            "donor": _donor_from_title(title),
        }
        for characteristic in characteristics:
            text = _safe_get(characteristic, idx)
            if ":" in text:
                key, value = text.split(":", 1)
                row[_normalize_column(key)] = value.strip()
        rows.append(row)
    return pd.DataFrame(rows)


def _first(metadata: dict[str, list[list[str]]], key: str) -> list[str]:
    values = metadata.get(key)
    if not values:
        return []
    return values[0]


def _safe_get(values: list[str], idx: int) -> str:
    return str(values[idx]).strip().strip('"') if idx < len(values) else ""


def _donor_from_title(title: str) -> str:
    if "_" in title:
        return title.rsplit("_", 1)[-1]
    return title


def _normalize_column(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("/", "_")


def _select_balanced_samples(samples: pd.DataFrame, *, max_per_group: int) -> pd.DataFrame:
    frames = []
    for _, group in samples.groupby("condition", sort=True):
        frames.append(group.head(max_per_group))
    if not frames:
        raise ValueError("No samples found in GEO metadata")
    return pd.concat(frames, ignore_index=True)


def _select_top_variable(matrix: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    if matrix.shape[0] <= top_n:
        return matrix
    variances = matrix.var(axis=1).sort_values(ascending=False)
    return matrix.loc[variances.head(top_n).index]


def _build_config(*, project_name: str, matrix_path: str, samples_path: str) -> dict[str, Any]:
    return {
        "project": {
            "name": project_name,
            "organism": "human",
            "output_dir": f"../runs/{project_name}",
            "server_root": "/shared/shen/2026/ultimate",
        },
        "samples": {"samplesheet": samples_path},
        "design": {
            "condition_column": "condition",
            "control": "normal",
            "case": "tumor",
            "batch_column": "batch",
            "comparisons": ["tumor_vs_normal"],
        },
        "resources": {
            "public_cache": "/shared/shen/2026/ultimate/cache/publicdb",
            "source_database": "GEO",
            "geo_accession": "GSE10072",
        },
        "modules": {
            "publicdb": {
                "enabled": True,
                "samplesheet": samples_path,
                "input_matrix": matrix_path,
                "cohort": "GSE10072",
                "open_immune_fallback": "ssGSEA_signature_score",
                "r_entrypoint": "scripts/R/publicdb.R",
            },
            "wgcna": {
                "enabled": True,
                "samplesheet": samples_path,
                "input_matrix": matrix_path,
                "r_entrypoint": "scripts/R/wgcna.R",
            },
            "single_gene": {
                "enabled": True,
                "gene": "TP53",
                "samplesheet": samples_path,
                "input_matrix": matrix_path,
                "r_entrypoint": "scripts/R/single_gene.R",
            },
        },
        "report": {
            "title": "GSE10072 公共数据验证报告",
            "language": "zh-CN",
            "figure_format": "png",
            "dpi": 160,
            "notes": "Public GEO validation dataset prepared from GSE10072 series matrix.",
        },
    }


if __name__ == "__main__":
    main()
