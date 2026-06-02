from __future__ import annotations

import json
from pathlib import Path

import click

from ultimate.config import load_config
from ultimate.constants import PROJECT_TYPES
from ultimate.demo import init_project
from ultimate.pipeline import run_pipeline_from_config
from ultimate.plot_style import available_styles, generate_style_review, set_active_style
from ultimate.preflight import run_preflight
from ultimate.production_audit import run_production_audit
from ultimate.report import build_report
from ultimate.singlecell_audit import run_singlecell_audit


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
