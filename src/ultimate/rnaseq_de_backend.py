from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RNASEQ_DE_BACKEND_ID = "rnaseq.de.deseq2_edger"


def rnaseq_de_backend_requested(module_cfg: dict[str, Any]) -> bool:
    """Return whether the formal RNA-seq DE backend was explicitly requested."""

    de_cfg = module_cfg.get("de_backend") if isinstance(module_cfg.get("de_backend"), dict) else {}
    if de_cfg.get("enabled") is True:
        return True
    requested = module_cfg.get("backends") if isinstance(module_cfg.get("backends"), dict) else {}
    requested_keys = {str(key) for key, value in requested.items() if value not in {None, False, ""}}
    requested_values = {str(value) for value in requested.values() if value not in {None, False, ""}}
    tokens = {RNASEQ_DE_BACKEND_ID, "deseq2_edger", "DESeq2", "edgeR"}
    return bool(tokens.intersection(requested_values) or tokens.intersection(requested_keys))


def run_rnaseq_de_backend(
    *,
    counts_path: Path | str | None,
    samplesheet_path: Path | str | None,
    tables_dir: Path,
    figures_dir: Path,
    objects_dir: Path,
    design: dict[str, Any],
    analysis_level: str,
    module_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Run DESeq2/edgeR for raw-count RNA-seq input, or write explicit skip evidence."""

    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    objects_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _artifact_paths(tables_dir, figures_dir, objects_dir)
    backend_id = RNASEQ_DE_BACKEND_ID
    counts = Path(str(counts_path)).expanduser() if counts_path else None
    samples = Path(str(samplesheet_path)).expanduser() if samplesheet_path else None
    status = "skipped"
    reason = ""
    versions: dict[str, str] = {}

    if counts is None or not counts.exists():
        reason = f"missing_count_matrix:{counts or 'not_configured'}"
    elif samples is None or not samples.exists():
        reason = f"missing_samplesheet:{samples or 'not_configured'}"
    else:
        reason = _design_blocker(samples, design)
    if not reason:
        rscript = _resolve_rscript(module_cfg)
        if not rscript:
            reason = "dependency_missing:Rscript"
        else:
            versions = _r_package_versions(rscript)
            if not (versions.get("DESeq2") or versions.get("edgeR")):
                reason = "dependency_missing:DESeq2_or_edgeR"
            elif not versions.get("jsonlite"):
                reason = "dependency_missing:jsonlite"
            else:
                script_path = _backend_script_path(module_cfg)
                command = [
                    rscript,
                    str(script_path),
                    "--counts",
                    str(counts),
                    "--samples",
                    str(samples),
                    "--tables-dir",
                    str(tables_dir),
                    "--figures-dir",
                    str(figures_dir),
                    "--objects-dir",
                    str(objects_dir),
                    "--condition-column",
                    str(design.get("condition_column", "condition")),
                    "--control",
                    str(design.get("control", "control")),
                    "--case",
                    str(design.get("case", "treated")),
                    "--backend-id",
                    backend_id,
                    "--analysis-level",
                    analysis_level,
                ]
                try:
                    completed = subprocess.run(command, check=True, text=True, capture_output=True)
                    status = "ready"
                    _write_backend_log(tables_dir, command, completed.stdout, completed.stderr)
                except subprocess.CalledProcessError as exc:
                    reason = f"backend_failed:Rscript_exit_{exc.returncode}"
                    _write_backend_log(tables_dir, command, exc.stdout or "", exc.stderr or "")

    if status != "ready":
        _write_skip_outputs(
            artifacts=artifacts,
            backend_id=backend_id,
            analysis_level=analysis_level,
            status=status,
            reason=reason,
            counts_path=str(counts or ""),
            samplesheet_path=str(samples or ""),
            versions=versions,
        )

    manifest = _read_backend_manifest(artifacts["manifest"])
    manifest.setdefault("backend_id", backend_id)
    manifest.setdefault("status", status)
    manifest.setdefault("skip_reason", reason)
    manifest.setdefault("artifacts", {key: str(value) for key, value in artifacts.items()})
    manifest.setdefault("analysis_level", analysis_level)
    manifest.setdefault("interpretation_warning", "DESeq2/edgeR results require raw counts and biological replicate-aware design.")
    return {
        "backend_id": backend_id,
        "status": str(manifest.get("status") or status),
        "skip_reason": str(manifest.get("skip_reason") or reason),
        "analysis_level": analysis_level,
        "artifacts": {key: str(value) for key, value in artifacts.items()},
        "versions": versions,
    }


def _artifact_paths(tables_dir: Path, figures_dir: Path, objects_dir: Path) -> dict[str, Path]:
    return {
        "de_results": tables_dir / "de_results.tsv",
        "deseq2_edgeR_de_results": tables_dir / "deseq2_edgeR_de_results.tsv",
        "de_backend_status": tables_dir / "de_backend_status.tsv",
        "de_backend_versions": tables_dir / "de_backend_versions.tsv",
        "manifest": tables_dir / "de_backend_manifest.json",
        "volcano": figures_dir / "deseq2_edgeR_volcano.png",
        "top_gene_heatmap": figures_dir / "deseq2_edgeR_top_gene_heatmap.png",
        "rds": objects_dir / "rnaseq_de_backend.rds",
    }


def _design_blocker(samplesheet_path: Path, design: dict[str, Any]) -> str:
    samples = pd.read_csv(samplesheet_path, sep=None, engine="python")
    condition_column = str(design.get("condition_column", "condition"))
    control = str(design.get("control", "control"))
    case = str(design.get("case", "treated"))
    if "sample_id" not in samples.columns:
        return "samplesheet_missing_column:sample_id"
    if condition_column not in samples.columns:
        return f"samplesheet_missing_column:{condition_column}"
    counts = samples[condition_column].astype(str).value_counts().to_dict()
    if counts.get(control, 0) < 2 or counts.get(case, 0) < 2:
        return f"insufficient_biological_replicates:{control}={counts.get(control, 0)},{case}={counts.get(case, 0)}"
    return ""


def _resolve_rscript(module_cfg: dict[str, Any]) -> str:
    de_cfg = module_cfg.get("de_backend") if isinstance(module_cfg.get("de_backend"), dict) else {}
    configured = de_cfg.get("rscript") or de_cfg.get("rscript_path") or module_cfg.get("rscript_path")
    if configured:
        path = Path(str(configured)).expanduser()
        return str(path) if path.exists() else ""
    return shutil.which("Rscript") or ""


def _backend_script_path(module_cfg: dict[str, Any]) -> Path:
    de_cfg = module_cfg.get("de_backend") if isinstance(module_cfg.get("de_backend"), dict) else {}
    configured = de_cfg.get("script") or de_cfg.get("script_path")
    if configured:
        return Path(str(configured)).expanduser()
    return Path(__file__).resolve().parents[2] / "scripts" / "R" / "rnaseq_de_backend.R"


def _r_package_versions(rscript: str) -> dict[str, str]:
    expression = (
        'pkgs <- c("DESeq2","edgeR","limma","ggplot2","jsonlite"); '
        'for (p in pkgs) { '
        'if (requireNamespace(p, quietly=TRUE)) { '
        'cat(p, as.character(packageVersion(p)), sep="\\t"); cat("\\n") '
        '} }'
    )
    try:
        completed = subprocess.run([rscript, "-e", expression], check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return {}
    versions: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 2:
            versions[parts[0]] = parts[1]
    return versions


def _write_skip_outputs(
    *,
    artifacts: dict[str, Path],
    backend_id: str,
    analysis_level: str,
    status: str,
    reason: str,
    counts_path: str,
    samplesheet_path: str,
    versions: dict[str, str],
) -> None:
    row = {
        "backend_id": backend_id,
        "status": status,
        "analysis_level": analysis_level,
        "skip_reason": reason,
        "interpretation_warning": "No formal RNA-seq DE conclusion was generated.",
    }
    pd.DataFrame([row]).to_csv(artifacts["de_backend_status"], sep="\t", index=False)
    pd.DataFrame(
        [
            {
                "feature_id": "",
                "log2FoldChange": "",
                "pvalue": "",
                "padj": "",
                "backend_id": backend_id,
                "backend_status": status,
                "skip_reason": reason,
            }
        ]
    ).to_csv(artifacts["de_results"], sep="\t", index=False)
    pd.DataFrame(
        [
            {
                "feature_id": "",
                "log2FoldChange": "",
                "pvalue": "",
                "padj": "",
                "backend_id": backend_id,
                "backend_status": status,
                "skip_reason": reason,
            }
        ]
    ).to_csv(artifacts["deseq2_edgeR_de_results"], sep="\t", index=False)
    pd.DataFrame([{"package": key, "version": value} for key, value in versions.items()]).to_csv(
        artifacts["de_backend_versions"], sep="\t", index=False
    )
    manifest = {
        "backend_id": backend_id,
        "status": status,
        "analysis_level": analysis_level,
        "skip_reason": reason,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts_path": counts_path,
        "samplesheet_path": samplesheet_path,
        "artifacts": {key: str(value) for key, value in artifacts.items()},
        "versions": versions,
        "interpretation_warning": "DESeq2/edgeR was not executed; no formal differential expression conclusion should be reported.",
    }
    artifacts["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_placeholder_png(artifacts["volcano"], "RNA-seq DE backend skipped")
    _write_placeholder_png(artifacts["top_gene_heatmap"], "RNA-seq DE backend skipped")
    artifacts["rds"].write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _write_placeholder_png(path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    ax.text(0.5, 0.55, title, ha="center", va="center", fontsize=11)
    ax.text(0.5, 0.4, "See de_backend_status.tsv", ha="center", va="center", fontsize=9)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _write_backend_log(tables_dir: Path, command: list[str], stdout: str, stderr: str) -> None:
    log_path = tables_dir / "de_backend_rscript.log"
    log_path.write_text(
        "\n".join(
            [
                "command\t" + " ".join(command),
                "stdout",
                stdout,
                "stderr",
                stderr,
            ]
        ),
        encoding="utf-8",
    )


def _read_backend_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
