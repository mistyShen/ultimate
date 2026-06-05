from __future__ import annotations

import json
from pathlib import Path

import click

from ultimate.approval_gate import load_production_approval
from ultimate.config import load_config
from ultimate.constants import PROJECT_TYPES
from ultimate.demo import init_project
from ultimate.job import prepare_job
from ultimate.pipeline import run_pipeline_from_config
from ultimate.plot_style import available_styles, generate_style_review, set_active_style
from ultimate.preflight import run_preflight
from ultimate.production_audit import run_production_audit
from ultimate.report import build_report
from ultimate.reproducibility import export_reproducible_package
from ultimate.singlecell_audit import run_singlecell_audit
from ultimate.triage import run_triage
from ultimate.validation_index import build_validation_index


@click.group()
def main() -> None:
    """Ultimate multi-omics bioinformatics command line interface."""


@main.command("init-project")
@click.option("--type", "project_type", type=click.Choice(PROJECT_TYPES), required=True)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory where the project template should be created.",
)
@click.option("--demo-data/--no-demo-data", default=False, show_default=True)
def init_project_command(project_type: str, output_dir: Path, demo_data: bool) -> None:
    manifest = init_project(project_type, output_dir, demo_data=demo_data)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("prepare-job")
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True, dir_okay=False), required=True)
@click.option("--job-id", required=True, help="Stable job id under <root>/jobs/<job_id>.")
@click.option("--root", type=click.Path(path_type=Path), default=Path("/shared/shen/2026/ultimate"), show_default=True)
@click.option("--samplesheet", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.option("--analysis-request", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.option("--run-mode", type=click.Choice(["production", "interactive"]), default="production", show_default=True)
def prepare_job_command(
    config_path: Path,
    job_id: str,
    root: Path,
    samplesheet: Path | None,
    analysis_request: Path | None,
    run_mode: str,
) -> None:
    try:
        manifest = prepare_job(
            config_path=config_path,
            job_id=job_id,
            root=root,
            samplesheet=samplesheet,
            analysis_request=analysis_request,
            run_mode=run_mode,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("preflight")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
)
def preflight_command(config_path: Path) -> None:
    loaded = load_config(config_path)
    manifest = run_preflight(loaded.raw, write=True)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
)
@click.option("--production-approval", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None, help="Approved JSON gate file required when the unified run requests production_backend.")
def run_command(config_path: Path, production_approval: Path | None) -> None:
    try:
        manifest = run_pipeline_from_config(config_path, production_approval_path=production_approval)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("triage")
@click.option("--request", "request_path", type=click.Path(path_type=Path, exists=True, dir_okay=False), required=True)
@click.option("--output-dir", type=click.Path(path_type=Path), required=True)
def triage_command(request_path: Path, output_dir: Path) -> None:
    """Assess technical readiness without running analysis or creating production artifacts."""
    manifest = run_triage(request_path=request_path, output_dir=output_dir)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("report")
@click.option(
    "--run-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
)
def report_command(run_dir: Path) -> None:
    manifest = build_report(run_dir)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("export-repro")
@click.option(
    "--run-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
    help="Run directory containing run_manifest.json.",
)
@click.option("--checksum-max-mb", type=int, default=256, show_default=True, help="Maximum file size to hash for input checksums.")
def export_repro_command(run_dir: Path, checksum_max_mb: int) -> None:
    manifest = export_reproducible_package(run_dir, checksum_max_bytes=checksum_max_mb * 1024 * 1024)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("audit-singlecell")
@click.option(
    "--root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where audit artifacts should be written. Defaults to <root>/audits/singlecell.",
)
def audit_singlecell_command(root: Path, output_dir: Path | None) -> None:
    manifest = run_singlecell_audit(root=root, output_dir=output_dir)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("validation-index")
@click.option(
    "--root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
)
@click.option(
    "--validations-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Directory containing <run>/run_manifest.json files. Defaults to <root>/validations.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where validation index artifacts should be written. Defaults to <root>/reports/validation_index.",
)
def validation_index_command(root: Path, validations_dir: Path | None, output_dir: Path | None) -> None:
    manifest = build_validation_index(root=root, validations_dir=validations_dir, output_dir=output_dir)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("audit-production")
@click.option(
    "--root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where production-readiness audit artifacts should be written.",
)
def audit_production_command(root: Path, output_dir: Path | None) -> None:
    manifest = run_production_audit(root=root, output_dir=output_dir)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("audit-modules")
@click.option(
    "--root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Project root to audit. Defaults to the installed ultimate package.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Where module standardization artifacts should be written.",
)
def audit_modules_command(root: Path | None, output_dir: Path) -> None:
    from datetime import datetime, timezone

    import pandas as pd

    from ultimate.module_standardization import build_module_standardization_rows

    output_dir.mkdir(parents=True, exist_ok=True)
    modules_root = root / "src" / "ultimate" / "modules" if root else None
    rows = build_module_standardization_rows(modules_root=modules_root)
    matrix_path = output_dir / "module_standardization_matrix.tsv"
    pd.DataFrame(rows).to_csv(matrix_path, sep="\t", index=False)
    summary = {
        "ready": sum(1 for row in rows if row["overall_status"] == "ready"),
        "partial": sum(1 for row in rows if row["overall_status"] != "ready"),
    }
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()) if root else "",
        "output_dir": str(output_dir.resolve()),
        "module_count": len(rows),
        "summary": summary,
        "module_standardization_matrix": str(matrix_path.resolve()),
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest["manifest_path"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("audit-tools")
@click.option(
    "--root",
    type=click.Path(path_type=Path),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
    help="Ultimate project root on shared storage.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where tool audit artifacts should be written. Defaults to <root>/audits/tools.",
)
def audit_tools_command(root: Path, output_dir: Path | None) -> None:
    from ultimate.tool_registry import run_audit_tools

    manifest = run_audit_tools(root=root, output_dir=output_dir)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("trial-tools")
@click.option(
    "--root",
    type=click.Path(path_type=Path),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
    help="Ultimate project root on shared storage.",
)
@click.option("--batch", required=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=None)
@click.option("--project-root", type=click.Path(path_type=Path), default=None, help="Directory containing envs/*.yml. Defaults to --root.")
@click.option("--install/--no-install", default=False, show_default=True, help="Run the batch mamba install before smoke checks.")
def trial_tools_command(root: Path, batch: str, output_dir: Path | None, project_root: Path | None, install: bool) -> None:
    from ultimate.tool_registry import available_tool_batches, run_trial_tools

    if batch not in available_tool_batches():
        raise click.BadParameter(f"Unsupported batch {batch!r}; expected one of {available_tool_batches()}")
    manifest = run_trial_tools(root=root, batch=batch, output_dir=output_dir, install=install, project_root=project_root)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("prune-tools")
@click.option(
    "--root",
    type=click.Path(path_type=Path),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
    help="Ultimate project root on shared storage.",
)
@click.option("--output-dir", type=click.Path(path_type=Path), default=None)
@click.option("--yes", is_flag=True, help="Actually run safe cache cleanup commands. Without this, only writes a prune plan.")
def prune_tools_command(root: Path, output_dir: Path | None, yes: bool) -> None:
    from ultimate.tool_registry import run_prune_tools

    manifest = run_prune_tools(root=root, output_dir=output_dir, yes=yes)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("prepare-intake")
@click.option(
    "--root",
    type=click.Path(path_type=Path),
    default=Path("/shared/shen/2026/ultimate"),
    show_default=True,
    help="Ultimate project root on shared storage.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the customer intake package should be written. Defaults to <root>/intake_packages/latest.",
)
@click.option("--refresh-audit/--no-refresh-audit", default=False, show_default=True)
def prepare_intake_command(root: Path, output_dir: Path | None, refresh_audit: bool) -> None:
    from ultimate.intake import prepare_intake_package

    manifest = prepare_intake_package(root=root, output_dir=output_dir, refresh_audit=refresh_audit)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("styles")
@click.option("--style", "style_key", default="soft_color", show_default=True, help="Style key to render.")
@click.option("--all", "render_all", is_flag=True, help="Render review figures for every registered style.")
@click.option("--output-dir", type=click.Path(path_type=Path), default=None, help="Optional review output directory.")
def styles_command(style_key: str, render_all: bool, output_dir: Path | None) -> None:
    styles = available_styles()
    if output_dir is None:
        click.echo(json.dumps(styles, indent=2, ensure_ascii=False))
        return
    if render_all:
        manifests = {}
        output_dir.mkdir(parents=True, exist_ok=True)
        for key in styles:
            tokens = set_active_style(key)
            manifests[key] = generate_style_review(output_dir / key, style=tokens)
        click.echo(json.dumps({"selected": "all", "available": list(styles), "manifests": manifests}, indent=2, ensure_ascii=False))
        return
    tokens = set_active_style(style_key)
    manifest = generate_style_review(output_dir, style=tokens)
    click.echo(json.dumps({"selected": style_key, "available": list(styles), **manifest}, indent=2, ensure_ascii=False))


@main.command("create-scrna-demo-inputs")
@click.option("--output-dir", type=click.Path(path_type=Path), required=True)
@click.option("--n-cells", type=int, default=120, show_default=True)
@click.option("--n-genes", type=int, default=90, show_default=True)
@click.option("--seed", type=int, default=17, show_default=True)
def create_scrna_demo_inputs_command(output_dir: Path, n_cells: int, n_genes: int, seed: int) -> None:
    """Create tiny h5ad/10x h5/10x mtx inputs for non-deliverable scRNA MVP checks."""
    from ultimate.scrna_smoke import create_demo_inputs

    manifest = create_demo_inputs(output_dir, n_cells=n_cells, n_genes=n_genes, seed=seed)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("validate-scrna")
@click.option("--input-path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--input-type", type=click.Choice(["h5ad", "10x_h5", "10x_mtx"]), required=True)
@click.option("--output-dir", type=click.Path(path_type=Path), required=True)
@click.option("--samplesheet", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--max-cells", type=int, default=3000, show_default=True)
@click.option("--random-seed", type=int, default=7, show_default=True)
@click.option("--analysis-level", type=click.Choice(["demo_result", "smoke_backend", "validated_backend", "production_backend"]), default=None)
@click.option("--public-dataset", is_flag=True, help="Mark a real public dataset validation run; never use with generated demo inputs.")
@click.option("--dataset-label", default=None, help="Optional dataset label recorded in the manifest.")
@click.option("--production-approval", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None, help="Approved JSON gate file required for production_backend.")
def validate_scrna_command(
    input_path: Path,
    input_type: str,
    output_dir: Path,
    samplesheet: Path | None,
    max_cells: int,
    random_seed: int,
    analysis_level: str | None,
    public_dataset: bool,
    dataset_label: str | None,
    production_approval: Path | None,
) -> None:
    """Run the scRNA MVP validation path on h5ad, 10x H5, or 10x MTX input."""
    from ultimate.scrna_smoke import run_scrna_validation

    try:
        approval = load_production_approval(
            production_approval,
            analysis_level=analysis_level,
            input_path=input_path,
            output_dir=output_dir,
        )
        manifest = run_scrna_validation(
            input_path=input_path,
            input_type=input_type,
            output_dir=output_dir,
            samplesheet=samplesheet,
            max_cells=max_cells,
            random_seed=random_seed,
            analysis_level=analysis_level,
            public_dataset=public_dataset,
            dataset_label=dataset_label,
            production_approval=approval,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
