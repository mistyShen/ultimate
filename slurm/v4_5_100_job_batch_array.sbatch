#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_5_100
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%A_%a.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%A_%a.err
#SBATCH --array=0-9
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
STAMP="${ULTIMATE_V45_100_JOB_STAMP:-${SLURM_ARRAY_JOB_ID:-$(date -u +%Y%m%dT%H%M%SZ)}}"
CHUNK_INDEX="${SLURM_ARRAY_TASK_ID:?Submit as a Slurm array with --array=0-9}"
TOTAL_CHUNKS=10
CHUNK_SIZE=10
SUMMARY_DIR="$PROJECT_ROOT/reports/v4_5_100_job_chunks/$STAMP"
CHUNK_SUMMARY="$SUMMARY_DIR/chunk_${CHUNK_INDEX}_summary.tsv"
CHUNK_SUMMARY_JSON="$SUMMARY_DIR/chunk_${CHUNK_INDEX}_summary.json"

if (( CHUNK_INDEX < 0 || CHUNK_INDEX >= TOTAL_CHUNKS )); then
  echo "Invalid V4.5 chunk index: $CHUNK_INDEX; expected 0-9" >&2
  exit 2
fi

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$SUMMARY_DIR"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$PROJECT_ROOT/tools/bin:$CORE_ENV/bin:$SCRNA_ENV/bin:$PATH"

module_for_index() {
  local global_index="$1"
  if (( global_index <= 20 )); then echo "rnaseq"
  elif (( global_index <= 35 )); then echo "scrna"
  elif (( global_index <= 50 )); then echo "proteomics"
  elif (( global_index <= 60 )); then echo "methylation"
  elif (( global_index <= 70 )); then echo "scatac"
  elif (( global_index <= 80 )); then echo "spatial"
  elif (( global_index <= 88 )); then echo "multiome"
  elif (( global_index <= 93 )); then echo "cite_seq"
  elif (( global_index <= 97 )); then echo "vdj"
  elif (( global_index <= 100 )); then echo "functional_state"
  else
    echo "Unsupported V4.5 global index: $global_index" >&2
    exit 3
  fi
}

env_for_module() {
  local module="$1"
  if [[ "$module" == "scrna" ]]; then
    echo "$SCRNA_ENV"
  else
    echo "$CORE_ENV"
  fi
}

generate_job() {
  local env_prefix="$1"
  local global_index="$2"
  local module="$3"
  local job_id="$4"
  local job_dir="$5"
  local run_dir="$6"
  "$env_prefix/bin/python" - "$PROJECT_ROOT" "$STAMP" "$CHUNK_INDEX" "$global_index" "$module" "$job_id" "$job_dir" "$run_dir" <<'PY'
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

root = Path(sys.argv[1])
stamp = sys.argv[2]
chunk_index = int(sys.argv[3])
global_index = int(sys.argv[4])
module = sys.argv[5]
job_id = sys.argv[6]
job_dir = Path(sys.argv[7])
run_dir = Path(sys.argv[8])

if job_dir.exists():
    raise SystemExit(f"Refusing to reuse existing V4.5 rehearsal job directory: {job_dir}")

for rel in ("config", "samples", "runs", "logs", "deliverables", "reproducible_code", "raw_links"):
    (job_dir / rel).mkdir(parents=True, exist_ok=True)

def write_tsv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(map(str, row)) + "\n")
    return path

def write_matrix(path: Path, first_col: str, features: list[str], sample_ids: list[str], *, seed: int, beta: bool = False) -> Path:
    rng = random.Random(seed)
    rows: list[list[object]] = []
    for feature_idx, feature in enumerate(features, start=1):
        values: list[str] = []
        for sample_idx, _sample_id in enumerate(sample_ids):
            if beta:
                value = 0.2 + rng.random() * 0.18
                if feature_idx <= max(3, len(features) // 10) and sample_idx >= len(sample_ids) // 2:
                    value = min(0.95, value + 0.32 + rng.random() * 0.10)
                values.append(f"{value:.4f}")
            elif module == "proteomics":
                value = rng.uniform(8.0, 10.5)
                if feature_idx <= max(5, len(features) // 10) and sample_idx >= len(sample_ids) // 2:
                    value += rng.uniform(0.35, 0.85)
                values.append(f"{value:.4f}")
            else:
                baseline = rng.randint(12, 90)
                effect = rng.randint(6, 24) if feature_idx <= max(5, len(features) // 10) and sample_idx >= len(sample_ids) // 2 else 0
                values.append(str(baseline + effect))
        rows.append([feature, *values])
    return write_tsv(path, [first_col, *sample_ids], rows)

def write_samples(path: Path, sample_ids: list[str], input_path: Path, *, n_control: int | None = None) -> Path:
    if n_control is None:
        n_control = max(1, len(sample_ids) // 2)
    rows = []
    for idx, sample_id in enumerate(sample_ids):
        condition = "control" if idx < n_control else "case"
        batch = f"B{(idx % 3) + 1}"
        rows.append([sample_id, condition, batch, input_path])
    return write_tsv(path, ["sample_id", "condition", "batch", "input_path"], rows)

def base_config(samplesheet: Path, module_cfg: dict, *, title: str, design: bool = True) -> dict:
    config = {
        "project": {
            "name": job_id,
            "job_id": job_id,
            "organism": "human",
            "output_dir": str(run_dir),
            "server_root": str(root),
            "run_mode": "production",
            "analysis_level": "production_backend",
            "delivery_scope": "internal_rehearsal",
            "delivery_mode": "customer_delivery_rehearsal",
            "customer_delivery_actual": False,
            "is_demo": False,
        },
        "analysis_request": str(job_dir / "config" / "analysis_request.md"),
        "samples": {"samplesheet": str(samplesheet)},
        "modules": {module: module_cfg},
        "report": {
            "title": title,
            "style": "morandi_clinical",
            "figure_options": {"legend_position": "outside_right", "show_grid": True},
        },
    }
    if design:
        config["design"] = {"condition_column": "condition", "batch_column": "batch", "control": "control", "case": "case"}
    return config

def common_module_cfg(input_type: str) -> dict:
    return {
        "enabled": True,
        "preset": "standard",
        "analysis_level": "production_backend",
        "is_demo": False,
        "raw": {"enabled": False, "input_type": input_type},
    }

rng_seed = 450000 + global_index
samples_dir = job_dir / "samples"
samplesheet = samples_dir / "samples.tsv"
analysis_note = (
    f"V4.5 controlled {module} rehearsal job {global_index}. "
    "No raw customer data is copied; no heavy upstream workflow is executed. "
    "Computational results require human review and are not mechanism proof.\n"
)
(job_dir / "config" / "analysis_request.md").write_text(analysis_note, encoding="utf-8")

if module == "rnaseq":
    sample_ids = [f"R{global_index:03d}_S{i:02d}" for i in range(1, 13)]
    matrix = write_matrix(samples_dir / "rnaseq_counts.tsv", "feature_id", [f"GENE_{i:04d}" for i in range(1, 161)], sample_ids, seed=rng_seed)
    write_samples(samplesheet, sample_ids, matrix)
    cfg = common_module_cfg("count_matrix")
    cfg["input_matrix"] = str(matrix)
    config = base_config(samplesheet, cfg, title="V4.5 RNA-seq controlled 100-job rehearsal")
elif module == "proteomics":
    sample_ids = [f"P{global_index:03d}_S{i:02d}" for i in range(1, 11)]
    matrix = write_matrix(samples_dir / "proteomics_abundance.tsv", "feature_id", [f"PROT_{i:04d}" for i in range(1, 121)], sample_ids, seed=rng_seed)
    write_samples(samplesheet, sample_ids, matrix)
    cfg = common_module_cfg("abundance_table")
    cfg["input_matrix"] = str(matrix)
    cfg["abundance_table"] = str(matrix)
    config = base_config(samplesheet, cfg, title="V4.5 proteomics controlled 100-job rehearsal")
elif module == "methylation":
    sample_ids = [f"M{global_index:03d}_S{i:02d}" for i in range(1, 9)]
    matrix = write_matrix(samples_dir / "methylation_beta.tsv", "feature_id", [f"cg{i:06d}" for i in range(1, 101)], sample_ids, seed=rng_seed, beta=True)
    write_samples(samplesheet, sample_ids, matrix)
    cfg = common_module_cfg("beta_matrix")
    cfg["input_matrix"] = str(matrix)
    config = base_config(samplesheet, cfg, title="V4.5 methylation beta-matrix controlled rehearsal")
elif module == "functional_state":
    sample_ids = [f"F{global_index:03d}_S{i:02d}" for i in range(1, 9)]
    matrix = write_matrix(samples_dir / "functional_expression.tsv", "feature_id", [f"GENE_{i:04d}" for i in range(1, 121)], sample_ids, seed=rng_seed)
    write_samples(samplesheet, sample_ids, matrix)
    cfg = common_module_cfg("matrix")
    cfg["input_matrix"] = str(matrix)
    config = base_config(samplesheet, cfg, title="V4.5 functional-state signature controlled rehearsal")
elif module == "scatac":
    cells = [f"ATAC{global_index:03d}_C{i:02d}" for i in range(1, 13)]
    matrix = write_matrix(samples_dir / "peak_counts.tsv", "peak_id", [f"chr1:{1000+i*120}-{1080+i*120}" for i in range(1, 81)], cells, seed=rng_seed)
    write_samples(samplesheet, ["ATAC_SAMPLE_1"], matrix, n_control=1)
    cfg = common_module_cfg("peak_matrix")
    cfg["peak_matrix"] = str(matrix)
    config = base_config(samplesheet, cfg, title="V4.5 scATAC peak-matrix controlled rehearsal", design=False)
elif module == "spatial":
    spots = [f"SPOT{i:02d}" for i in range(1, 17)]
    matrix = write_matrix(samples_dir / "spatial_counts.tsv", "feature_id", [f"Gene{i:03d}" for i in range(1, 81)], spots, seed=rng_seed)
    coord_rows = [[spot, idx % 4, idx // 4, idx % 4, idx // 4, 1] for idx, spot in enumerate(spots)]
    coords = write_tsv(samples_dir / "spatial_coordinates.tsv", ["spot_id", "pxl_col", "pxl_row", "array_col", "array_row", "in_tissue"], coord_rows)
    write_samples(samplesheet, ["SPATIAL_SAMPLE_1"], matrix, n_control=1)
    cfg = common_module_cfg("spatial_h5ad")
    cfg["expression_matrix"] = str(matrix)
    cfg["coordinates"] = str(coords)
    config = base_config(samplesheet, cfg, title="V4.5 spatial matrix controlled rehearsal", design=False)
elif module == "multiome":
    cells = [f"MULTI{global_index:03d}_C{i:02d}" for i in range(1, 11)]
    rna = write_matrix(samples_dir / "multiome_rna.tsv", "feature_id", [f"GENE_{i:04d}" for i in range(1, 91)], cells, seed=rng_seed)
    atac = write_matrix(samples_dir / "multiome_atac.tsv", "feature_id", [f"chr2:{2000+i*90}-{2060+i*90}" for i in range(1, 71)], cells, seed=rng_seed + 1)
    write_samples(samplesheet, ["MULTI_SAMPLE_1"], rna, n_control=1)
    cfg = common_module_cfg("rna_atac_matrix")
    cfg["rna_matrix"] = str(rna)
    cfg["atac_matrix"] = str(atac)
    config = base_config(samplesheet, cfg, title="V4.5 multiome paired-matrix controlled rehearsal", design=False)
elif module == "cite_seq":
    cells = [f"CITE{global_index:03d}_C{i:02d}" for i in range(1, 11)]
    rna = write_matrix(samples_dir / "cite_rna.tsv", "feature_id", ["CD3D", "MS4A1", "LYZ", "NKG7", "MKI67", "PPBP"], cells, seed=rng_seed)
    adt = write_matrix(samples_dir / "cite_adt.tsv", "feature_id", ["CD3_TotalSeqB", "CD19_TotalSeqB", "CD14_TotalSeqB", "CD56_TotalSeqB"], cells, seed=rng_seed + 1)
    write_samples(samplesheet, ["CITE_SAMPLE_1"], rna, n_control=1)
    cfg = common_module_cfg("rna_adt_matrix")
    cfg["rna_matrix"] = str(rna)
    cfg["adt_matrix"] = str(adt)
    cfg["antibody_panel"] = "controlled_validation_panel"
    config = base_config(samplesheet, cfg, title="V4.5 CITE-seq controlled rehearsal", design=False)
elif module == "vdj":
    vdj_dir = samples_dir / "vdj_tables"
    vdj_dir.mkdir(parents=True, exist_ok=True)
    contigs = vdj_dir / "filtered_contig_annotations.csv"
    contigs.write_text(
        "contig_id,barcode,is_cell,productive,chain,reads,umis,raw_clonotype_id,v_gene,j_gene,cdr3\n"
        f"c1,VDJ{global_index:03d}_cell_a,True,True,TRA,100,12,clonotype1,TRAV1-2,TRAJ33,CAVRDSNYQLIW\n"
        f"c2,VDJ{global_index:03d}_cell_a,True,True,TRB,120,15,clonotype1,TRBV6-5,TRBJ2-7,CASSLGQETQYF\n"
        f"c3,VDJ{global_index:03d}_cell_b,True,True,TRB,80,9,clonotype2,TRBV7-9,TRBJ1-2,CASSPPSGGYNEQFF\n",
        encoding="utf-8",
    )
    clonotypes = vdj_dir / "clonotypes.csv"
    clonotypes.write_text(
        "clonotype_id,frequency,cdr3s_aa\n"
        "clonotype1,1,TRA:CAVRDSNYQLIW;TRB:CASSLGQETQYF\n"
        "clonotype2,1,TRB:CASSPPSGGYNEQFF\n",
        encoding="utf-8",
    )
    write_samples(samplesheet, ["VDJ_SAMPLE_1", "VDJ_SAMPLE_2"], vdj_dir)
    cfg = common_module_cfg("cellranger_vdj_out")
    cfg["input_dir"] = str(vdj_dir)
    config = base_config(samplesheet, cfg, title="V4.5 VDJ controlled table rehearsal")
elif module == "scrna":
    import pandas as pd
    from ultimate.scrna_smoke import create_demo_inputs

    payload = create_demo_inputs(samples_dir / "scrna_10x_source", n_cells=96, n_genes=120, seed=rng_seed)
    controlled_mtx = samples_dir / "scrna_10x_matrix"
    Path(payload["tenx_mtx"]).rename(controlled_mtx)
    payload["tenx_mtx"] = str(controlled_mtx)
    sheet = pd.read_csv(payload["samplesheet"], sep="\t")
    sample_labels = ["S1", "S2", "S3", "S4"]
    sheet["sample_id"] = [sample_labels[idx % 4] for idx in range(len(sheet))]
    sheet["condition"] = sheet["sample_id"].map({"S1": "control", "S2": "control", "S3": "case", "S4": "case"})
    sheet["batch"] = sheet["sample_id"].map({"S1": "B1", "S2": "B1", "S3": "B2", "S4": "B2"})
    sheet["input_path"] = str(controlled_mtx)
    sheet.to_csv(samplesheet, sep="\t", index=False)
    (samples_dir / "scrna_controlled_inputs.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    cfg = common_module_cfg("10x_mtx")
    cfg["tenx_mtx"] = str(controlled_mtx)
    cfg["samplesheet"] = str(samplesheet)
    cfg["max_cells"] = 96
    config = base_config(samplesheet, cfg, title="V4.5 scRNA controlled 10x rehearsal")
else:
    raise SystemExit(f"Unsupported V4.5 module: {module}")

(job_dir / "config" / "project.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

approval = {
    "approved": True,
    "approved_by": "ultimate_v4_5_100_job_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": job_id,
    "input_path": str((job_dir / "config" / "project.yaml").resolve()),
    "output_dir": str(run_dir.resolve()),
    "delivery_scope": "internal_rehearsal",
    "delivery_mode": "customer_delivery_rehearsal",
    "customer_delivery_actual": False,
    "reason": "Controlled V4.5 100-job Slurm array rehearsal; no raw data is copied and no heavy upstream workflow is executed.",
}
(job_dir / "config" / "production_approval.json").write_text(json.dumps(approval, indent=2, ensure_ascii=False), encoding="utf-8")

job_manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "job_id": job_id,
    "job_dir": str(job_dir),
    "module": module,
    "preset": "standard",
    "global_index": global_index,
    "chunk_index": chunk_index,
    "suite_stamp": stamp,
    "run_mode": "production",
    "analysis_level": "production_backend",
    "delivery_scope": "internal_rehearsal",
    "delivery_mode": "customer_delivery_rehearsal",
    "controlled_rehearsal": True,
    "customer_delivery_actual": False,
    "copies_raw_data": False,
    "runs_heavy_upstream": False,
}
(job_dir / "job_manifest.json").write_text(json.dumps(job_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

(job_dir / "raw_links" / "raw_upstream_evidence.tsv").write_text(
    "module\texecution_status\tinput_policy\theavy_upstream\tstatus_note\n"
    f"{module}\tready\tcontrolled_lightweight_generated\tno\tNo raw customer data was copied; raw FASTQ/BAM upstream execution is intentionally out of scope for this V4.5 rehearsal.\n",
    encoding="utf-8",
)

print(json.dumps({"job_id": job_id, "module": module, "job_dir": str(job_dir), "run_dir": str(run_dir)}))
PY
}

run_stage() {
  local stage="$1"
  local log_path="$2"
  shift 2
  set +e
  "$@" >"$log_path" 2>&1
  local status=$?
  set -e
  echo "$status"
  if [[ "$status" -ne 0 ]]; then
    echo "Stage failed ($stage, exit=$status): $log_path" >&2
  fi
}

write_summary_header() {
  cat > "$CHUNK_SUMMARY" <<'TSV'
chunk_index	global_index	job_id	module	run_exit	customer_package_exit	delivery_check_exit	overall_status	job_dir
TSV
}

append_summary_row() {
  local global_index="$1"
  local job_id="$2"
  local module="$3"
  local run_exit="$4"
  local package_exit="$5"
  local delivery_exit="$6"
  local overall_status="$7"
  local job_dir="$8"
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$CHUNK_INDEX" "$global_index" "$job_id" "$module" "$run_exit" "$package_exit" "$delivery_exit" "$overall_status" "$job_dir" >> "$CHUNK_SUMMARY"
}

finalize_chunk_json() {
  "$CORE_ENV/bin/python" - "$CHUNK_SUMMARY" "$CHUNK_SUMMARY_JSON" "$STAMP" "$CHUNK_INDEX" <<'PY'
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

summary = Path(sys.argv[1])
rows = list(csv.DictReader(summary.open("r", encoding="utf-8"), delimiter="\t"))
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "suite_stamp": sys.argv[3],
    "chunk_index": int(sys.argv[4]),
    "job_count": len(rows),
    "ready": sum(1 for row in rows if row.get("overall_status") == "ready"),
    "blocked": sum(1 for row in rows if row.get("overall_status") == "blocked"),
    "failed": sum(1 for row in rows if row.get("overall_status") == "failed"),
    "rows": rows,
}
Path(sys.argv[2]).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

write_summary_header

for offset in $(seq 0 $((CHUNK_SIZE - 1))); do
  global_index=$((CHUNK_INDEX * CHUNK_SIZE + offset + 1))
  module="$(module_for_index "$global_index")"
  env_prefix="$(env_for_module "$module")"
  job_id=$(printf "v4_5_100_job_%03d_%s_%s" "$global_index" "$module" "$STAMP")
  job_dir="$PROJECT_ROOT/jobs/$job_id"
  run_dir="$job_dir/runs/$job_id"

  generate_job "$env_prefix" "$global_index" "$module" "$job_id" "$job_dir" "$run_dir" >"$job_dir.generator.json"

  run_exit="$(run_stage ultimate_run "$job_dir/logs/v4_5_ultimate_run.log" env ULTIMATE_ENV="$env_prefix" bash "$PROJECT_ROOT/slurm/ultimate_run.sbatch" "$job_dir/config/project.yaml" "$job_dir/config/production_approval.json")"
  package_exit="not_run"
  delivery_exit="not_run"
  overall_status="failed"

  if [[ "$run_exit" == "0" ]]; then
    package_exit="$(run_stage customer_package "$job_dir/logs/v4_5_customer_package.log" "$env_prefix/bin/python" -m ultimate.cli customer-package --run-dir "$job_dir")"
    if [[ "$package_exit" == "0" ]]; then
      delivery_exit="$(run_stage delivery_check "$job_dir/logs/v4_5_delivery_check.log" "$env_prefix/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir")"
      if [[ "$delivery_exit" == "0" ]]; then
        overall_status="ready"
      else
        overall_status="blocked"
      fi
    else
      overall_status="blocked"
    fi
  fi

  append_summary_row "$global_index" "$job_id" "$module" "$run_exit" "$package_exit" "$delivery_exit" "$overall_status" "$job_dir"
done

finalize_chunk_json
