from __future__ import annotations

import json
from pathlib import Path

import click

from ultimate.config import load_config
from ultimate.constants import PROJECT_TYPES
from ultimate.demo import init_project
from ultimate.intake import prepare_intake_package
from ultimate.pipeline import run_pipeline_from_config
from ultimate.plot_style import available_styles, generate_style_review, set_active_style
from ultimate.preflight import run_preflight
from ultimate.production_audit import run_production_audit
from ultimate.report import build_report
from ultimate.scrna_smoke import create_demo_inputs, run_scrna_validation
from ultimate.singlecell_audit import run_singlecell_audit
from ultimate.tool_registry import available_tool_batches, run_audit_tools, run_prune_tools, run_trial_tools


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
def run_command(config_path: Path) -> None:
    manifest = run_pipeline_from_config(config_path)
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
@click.option("--batch", type=click.Choice(available_tool_batches()), required=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=None)
@click.option("--project-root", type=click.Path(path_type=Path), default=None, help="Directory containing envs/*.yml. Defaults to --root.")
@click.option("--install/--no-install", default=False, show_default=True, help="Run the batch mamba install before smoke checks.")
def trial_tools_command(root: Path, batch: str, output_dir: Path | None, project_root: Path | None, install: bool) -> None:
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
    """Create tiny h5ad/10x h5/10x mtx inputs for scRNA smoke validation."""
    manifest = create_demo_inputs(output_dir, n_cells=n_cells, n_genes=n_genes, seed=seed)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@main.command("validate-scrna")
@click.option("--input-path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--input-type", type=click.Choice(["h5ad", "10x_h5", "10x_mtx"]), required=True)
@click.option("--output-dir", type=click.Path(path_type=Path), required=True)
@click.option("--samplesheet", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--max-cells", type=int, default=3000, show_default=True)
@click.option("--random-seed", type=int, default=7, show_default=True)
def validate_scrna_command(input_path: Path, input_type: str, output_dir: Path, samplesheet: Path | None, max_cells: int, random_seed: int) -> None:
    """Run the scRNA MVP smoke pipeline on h5ad, 10x H5, or 10x MTX input."""
    manifest = run_scrna_validation(
        input_path=input_path,
        input_type=input_type,
        output_dir=output_dir,
        samplesheet=samplesheet,
        max_cells=max_cells,
        random_seed=random_seed,
    )
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
