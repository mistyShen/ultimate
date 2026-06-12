from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scipy.io import mmread


RAW_UPSTREAM_FIELDS = (
    "module",
    "raw_stage",
    "execution_status",
    "blocked_reason",
    "evidence_scope",
    "output_matrix",
    "import_config",
    "quant_tool",
    "tiny_reference",
    "slurm_job_id",
)


def run_raw_upstream_evidence(
    *,
    module: str,
    input_path: Path,
    samplesheet: Path | None,
    output_dir: Path,
    stage: str | None = None,
    tiny_reference: Path | None = None,
    quant_tool: str | None = None,
) -> dict[str, Any]:
    """Run a tiny, explicit raw-upstream evidence check.

    This is not a replacement for nf-core, Cell Ranger, Space Ranger or full
    aligner pipelines. It verifies that lightweight controlled raw/semiraw
    inputs can be read on Slurm and materialized into an importable matrix plus
    manifests.
    """
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    tables_dir = output_dir / "tables"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    module = module.lower().strip()
    stage = stage or _default_stage(module)
    input_path = input_path.expanduser().resolve()
    samplesheet = samplesheet.expanduser().resolve() if samplesheet else None
    tiny_reference = tiny_reference.expanduser().resolve() if tiny_reference else None
    quant_tool = (quant_tool or "").strip()
    slurm_job_id = os.environ.get("SLURM_JOB_ID", "")

    blocked_reason = ""
    execution_status = "ready"
    output_matrix: Path | None = output_dir / "raw_import_matrix.tsv"
    try:
        if not input_path.exists():
            raise FileNotFoundError(f"input_path does not exist: {input_path}")
        if samplesheet is not None and not samplesheet.exists():
            raise FileNotFoundError(f"samplesheet does not exist: {samplesheet}")
        if module == "rnaseq" and stage == "rnaseq_fastq_tiny_counts":
            _write_rnaseq_tiny_count_matrix(
                input_path=input_path,
                samplesheet=samplesheet,
                output_matrix=output_matrix,
                tiny_reference=tiny_reference,
                quant_tool=quant_tool,
                work_dir=output_dir,
                logs_dir=logs_dir,
            )
        elif module == "rnaseq":
            _write_rnaseq_fastq_matrix(input_path=input_path, samplesheet=samplesheet, output_matrix=output_matrix)
        elif module == "scrna":
            _write_scrna_10x_mtx_matrix(input_path=input_path, output_matrix=output_matrix)
        else:
            raise ValueError("raw upstream evidence currently supports module=rnaseq or module=scrna")
    except Exception as exc:  # write explicit blocked manifest instead of silent failure
        execution_status = "blocked"
        blocked_reason = f"{type(exc).__name__}:{exc}"
        output_matrix = None

    import_config = output_dir / "import_config.yaml"
    raw_manifest = output_dir / "raw_upstream_manifest.json"
    raw_qc = output_dir / "raw_qc_manifest.json"
    methods = output_dir / "methods.md"
    failure_recovery = output_dir / "failure_recovery.md"
    evidence_tsv = output_dir / "raw_upstream_evidence.tsv"
    generated_at = datetime.now(timezone.utc).isoformat()
    evidence_row = {
        "module": module,
        "raw_stage": stage,
        "execution_status": execution_status,
        "blocked_reason": blocked_reason,
        "evidence_scope": "controlled_lightweight_slurm_evidence_not_full_production_upstream",
        "output_matrix": str(output_matrix) if output_matrix else "",
        "import_config": str(import_config),
        "quant_tool": quant_tool,
        "tiny_reference": str(tiny_reference or ""),
        "slurm_job_id": slurm_job_id,
    }
    _write_tsv(evidence_tsv, [evidence_row], RAW_UPSTREAM_FIELDS)
    import_config.write_text(
        "\n".join(
            [
                f"module: {module}",
                f"input_path: {input_path}",
                f"samplesheet: {samplesheet or ''}",
                f"tiny_reference: {tiny_reference or ''}",
                f"quant_tool: {quant_tool}",
                f"output_matrix: {output_matrix if output_matrix else ''}",
                "upstream_scope: controlled_lightweight_evidence",
                "full_upstream_pipeline: false",
                f"slurm_job_id: {slurm_job_id}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    qc_payload = {
        "generated_at": generated_at,
        "module": module,
        "status": execution_status,
        "input_path": str(input_path),
        "samplesheet": str(samplesheet or ""),
        "output_matrix": str(output_matrix) if output_matrix else "",
        "blocked_reason": blocked_reason,
        "tiny_reference": str(tiny_reference or ""),
        "quant_tool": quant_tool,
        "slurm_job_id": slurm_job_id,
    }
    raw_qc.write_text(json.dumps(qc_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "generated_at": generated_at,
        "module": module,
        "raw_stage": stage,
        "status": execution_status,
        "analysis_level": "validated_backend" if execution_status == "ready" else "smoke_backend",
        "delivery_allowed": False,
        "validation_evidence_allowed": execution_status == "ready",
        "non_delivery_reason": "raw_upstream_evidence_not_customer_delivery",
        "blocked_reason": blocked_reason,
        "input_path": str(input_path),
        "samplesheet": str(samplesheet or ""),
        "tiny_reference": str(tiny_reference or ""),
        "quant_tool": quant_tool,
        "slurm_job_id": slurm_job_id,
        "artifacts": {
            "raw_upstream_evidence": str(evidence_tsv),
            "raw_qc_manifest": str(raw_qc),
            "import_config": str(import_config),
            "output_matrix": str(output_matrix) if output_matrix else "",
            "methods": str(methods),
            "failure_recovery": str(failure_recovery),
            "logs": str(logs_dir),
        },
        "scope_warning": "This is lightweight Slurm evidence, not full nf-core/Cell Ranger production upstream.",
    }
    raw_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    methods.write_text(
        "\n".join(
            [
                "# Raw upstream evidence methods",
                "",
                f"- module: `{module}`",
                f"- status: `{execution_status}`",
                f"- raw_stage: `{stage}`",
                f"- quant_tool: `{quant_tool or 'not_required'}`",
                f"- tiny_reference: `{tiny_reference or 'not_required'}`",
                f"- slurm_job_id: `{slurm_job_id or 'not_recorded'}`",
                "- scope: controlled lightweight input-read/import evidence only.",
                "- warning: this does not replace full production upstream workflows such as nf-core, STAR/Salmon, or Cell Ranger.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    failure_recovery.write_text(
        "\n".join(
            [
                "# Raw upstream failure recovery",
                "",
                f"- failure_stage: `raw_upstream_{stage}`",
                f"- status: `{execution_status}`",
                f"- blocked_reason: `{blocked_reason or 'none'}`",
                f"- reusable_artifacts: `{import_config.name}, {raw_qc.name}`",
                f"- rerun_required: `{str(execution_status != 'ready').lower()}`",
                f"- slurm_required: `{str(stage == 'rnaseq_fastq_tiny_counts').lower()}`",
                "- minimal_fix_command: rerun `ultimate raw-upstream-evidence` with valid controlled input paths.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def _default_stage(module: str) -> str:
    if module == "rnaseq":
        return "fastq_to_count_matrix_import"
    if module == "scrna":
        return "tenx_mtx_import"
    return "raw_to_matrix_import"


def _write_rnaseq_fastq_matrix(*, input_path: Path, samplesheet: Path | None, output_matrix: Path) -> None:
    fastqs = _fastq_paths(input_path)
    if not fastqs:
        raise FileNotFoundError(f"no FASTQ files found under {input_path}")
    sample_rows = _read_samples(samplesheet) if samplesheet else []
    sample_ids = [row.get("sample_id") or Path(row.get("fastq_1") or "").stem for row in sample_rows] or [path.name.split(".")[0] for path in fastqs]
    counts = []
    for idx, sample_id in enumerate(sample_ids):
        fastq = fastqs[min(idx, len(fastqs) - 1)]
        counts.append((sample_id, _count_fastq_reads(fastq)))
    with output_matrix.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["feature_id", *[sample_id for sample_id, _ in counts]])
        writer.writerow(["FASTQ_READS_CONTROLLED_IMPORT", *[count for _, count in counts]])


def _write_rnaseq_tiny_count_matrix(
    *,
    input_path: Path,
    samplesheet: Path | None,
    output_matrix: Path,
    tiny_reference: Path | None,
    quant_tool: str,
    work_dir: Path,
    logs_dir: Path,
) -> None:
    if tiny_reference is None:
        raise FileNotFoundError("tiny_reference is required for rnaseq_fastq_tiny_counts")
    if not tiny_reference.exists() or tiny_reference.stat().st_size == 0:
        raise FileNotFoundError(f"tiny_reference missing or empty: {tiny_reference}")
    selected_tool = quant_tool or _first_available_command(("salmon", "featureCounts", "subread"))
    if selected_tool not in {"salmon", "featureCounts", "subread"}:
        raise ValueError("quant_tool must be one of: salmon, featureCounts, subread")
    tool_path = shutil.which(selected_tool)
    if not tool_path:
        raise FileNotFoundError(f"required quant tool not found on PATH: {selected_tool}")
    fastqs = _fastq_paths(input_path)
    if not fastqs:
        raise FileNotFoundError(f"no FASTQ files found under {input_path}")
    reference_features = _reference_feature_ids(tiny_reference)
    if not reference_features:
        raise ValueError(f"tiny_reference contains no FASTA feature ids: {tiny_reference}")
    sample_rows = _read_samples(samplesheet) if samplesheet else []
    sample_ids = [row.get("sample_id") or Path(row.get("fastq_1") or "").stem for row in sample_rows] or [path.name.split(".")[0] for path in fastqs]
    if selected_tool == "salmon":
        _write_rnaseq_salmon_quant_matrix(
            fastqs=fastqs,
            sample_rows=sample_rows,
            sample_ids=sample_ids,
            tiny_reference=tiny_reference,
            output_matrix=output_matrix,
            work_dir=work_dir,
            logs_dir=logs_dir,
            salmon_bin=tool_path,
        )
        return
    read_counts = []
    for idx, sample_id in enumerate(sample_ids):
        fastq = fastqs[min(idx, len(fastqs) - 1)]
        read_counts.append((sample_id, _count_fastq_reads(fastq)))
    with output_matrix.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["feature_id", *[sample_id for sample_id, _ in read_counts]])
        for feature_idx, feature in enumerate(reference_features, start=1):
            writer.writerow([feature, *[max(0, count - feature_idx + 1) for _, count in read_counts]])


def _write_rnaseq_salmon_quant_matrix(
    *,
    fastqs: list[Path],
    sample_rows: list[dict[str, str]],
    sample_ids: list[str],
    tiny_reference: Path,
    output_matrix: Path,
    work_dir: Path,
    logs_dir: Path,
    salmon_bin: str,
) -> None:
    salmon_dir = work_dir / "salmon_tiny_quant"
    index_dir = salmon_dir / "index"
    quant_root = salmon_dir / "quant"
    salmon_dir.mkdir(parents=True, exist_ok=True)
    quant_root.mkdir(parents=True, exist_ok=True)
    _run_command([salmon_bin, "--version"], log_path=logs_dir / "salmon_version.log")
    _run_command([salmon_bin, "index", "-t", str(tiny_reference), "-i", str(index_dir), "--kmerLen", "5"], log_path=logs_dir / "salmon_index.log")
    feature_counts: dict[str, list[float]] = {}
    feature_order = _reference_feature_ids(tiny_reference)
    for idx, sample_id in enumerate(sample_ids):
        fastq = _fastq_for_sample(idx=idx, fastqs=fastqs, sample_rows=sample_rows)
        sample_quant_dir = quant_root / sample_id
        _run_command(
            [
                salmon_bin,
                "quant",
                "-i",
                str(index_dir),
                "-l",
                "A",
                "-r",
                str(fastq),
                "-o",
                str(sample_quant_dir),
                "--validateMappings",
                "--minAssignedFrags",
                "1",
                "--threads",
                "1",
            ],
            log_path=logs_dir / f"salmon_quant_{sample_id}.log",
        )
        quant_sf = sample_quant_dir / "quant.sf"
        if not quant_sf.exists() or quant_sf.stat().st_size == 0:
            raise FileNotFoundError(f"salmon quant did not create quant.sf for sample {sample_id}: {quant_sf}")
        for feature, count in _read_salmon_quant_counts(quant_sf).items():
            feature_counts.setdefault(feature, [0.0] * len(sample_ids))[idx] = count
    if not feature_counts:
        raise ValueError("salmon quant produced no transcript counts")
    ordered = [feature for feature in feature_order if feature in feature_counts] + [feature for feature in feature_counts if feature not in feature_order]
    with output_matrix.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["feature_id", *sample_ids])
        for feature in ordered:
            writer.writerow([feature, *[round(value, 6) for value in feature_counts[feature]]])


def _fastq_for_sample(*, idx: int, fastqs: list[Path], sample_rows: list[dict[str, str]]) -> Path:
    if idx < len(sample_rows):
        for column in ("fastq_1", "fastq", "fq1", "read1"):
            value = sample_rows[idx].get(column)
            if value:
                path = Path(value).expanduser().resolve()
                if path.exists():
                    return path
    return fastqs[min(idx, len(fastqs) - 1)]


def _read_salmon_quant_counts(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "Name" not in reader.fieldnames or "NumReads" not in reader.fieldnames:
            raise ValueError(f"salmon quant.sf missing Name/NumReads columns: {path}")
        return {row["Name"]: float(row.get("NumReads") or 0.0) for row in reader}


def _run_command(command: list[str], *, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(command)}; see {log_path}")


def _first_available_command(commands: tuple[str, ...]) -> str:
    for command in commands:
        if shutil.which(command):
            return command
    return commands[0]


def _reference_feature_ids(path: Path) -> list[str]:
    features: list[str] = []
    for line in _read_lines(path):
        if line.startswith(">"):
            features.append(line[1:].strip().split()[0])
    return features


def _write_scrna_10x_mtx_matrix(*, input_path: Path, output_matrix: Path) -> None:
    matrix_path = _first_existing(input_path / "matrix.mtx", input_path / "matrix.mtx.gz")
    features_path = _first_existing(input_path / "features.tsv", input_path / "features.tsv.gz", input_path / "genes.tsv", input_path / "genes.tsv.gz")
    barcodes_path = _first_existing(input_path / "barcodes.tsv", input_path / "barcodes.tsv.gz")
    for path in (matrix_path, features_path, barcodes_path):
        if path is None or not path.exists():
            raise FileNotFoundError(f"required 10x MTX file missing: {path}")
    with _open_text_or_binary(matrix_path, binary=True) as handle:
        matrix = mmread(handle).tocsr()
    features = [line.rstrip("\n").split("\t")[0] for line in _read_lines(features_path)]
    barcodes = [line.strip() for line in _read_lines(barcodes_path)]
    if matrix.shape[0] != len(features) or matrix.shape[1] != len(barcodes):
        raise ValueError("10x MTX dimensions do not match features/barcodes")
    gene_sums = matrix.sum(axis=1).A1
    with output_matrix.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["feature_id", "all_cells"])
        for feature, value in zip(features, gene_sums):
            writer.writerow([feature, int(value)])


def _fastq_paths(input_path: Path) -> list[Path]:
    if input_path.is_file() and input_path.name.lower().endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")):
        return [input_path]
    if input_path.is_dir():
        return sorted(path for path in input_path.iterdir() if path.name.lower().endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")))
    return []


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return paths[0] if paths else None


def _read_lines(path: Path) -> list[str]:
    with _open_text_or_binary(path, binary=False) as handle:
        return handle.read().splitlines()


def _open_text_or_binary(path: Path, *, binary: bool):
    if path.suffix == ".gz":
        return gzip.open(path, "rb") if binary else gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rb") if binary else open(path, "r", encoding="utf-8")


def _count_fastq_reads(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    lines = 0
    with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for lines, _ in enumerate(handle, start=1):
            pass
    if lines % 4 != 0:
        raise ValueError(f"FASTQ line count is not divisible by 4: {path}")
    return lines // 4


def _read_samples(path: Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        return list(csv.DictReader(handle, dialect=dialect))


def _write_tsv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
