#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


VDJ_DOWNLOADS = {
    "filtered_contig_annotations.csv": (
        "https://cf.10xgenomics.com/samples/cell-vdj/3.1.0/"
        "vdj_nextgem_hs_pbmc3/vdj_nextgem_hs_pbmc3_b_filtered_contig_annotations.csv"
    ),
    "clonotypes.csv": (
        "https://cf.10xgenomics.com/samples/cell-vdj/3.1.0/"
        "vdj_nextgem_hs_pbmc3/vdj_nextgem_hs_pbmc3_b_clonotypes.csv"
    ),
}


CITE_SEQ_DOWNLOADS = {
    "pbmc_10k_protein_v3_filtered_feature_bc_matrix.h5": (
        "https://cf.10xgenomics.com/samples/cell-exp/3.0.0/"
        "pbmc_10k_protein_v3/pbmc_10k_protein_v3_filtered_feature_bc_matrix.h5"
    ),
}

SCATAC_DOWNLOADS = {
    "10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5": (
        "https://cf.10xgenomics.com/samples/cell-atac/2.1.0/"
        "10k_pbmc_ATACv2_nextgem_Chromium_Controller/"
        "10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5"
    ),
    "10k_pbmc_ATACv2_nextgem_Chromium_Controller_summary.csv": (
        "https://cf.10xgenomics.com/samples/cell-atac/2.1.0/"
        "10k_pbmc_ATACv2_nextgem_Chromium_Controller/"
        "10k_pbmc_ATACv2_nextgem_Chromium_Controller_summary.csv"
    ),
}

MULTIOME_DOWNLOADS = {
    "10k_PBMC_Multiome_nextgem_Chromium_Controller_filtered_feature_bc_matrix.h5": (
        "https://cf.10xgenomics.com/samples/cell-arc/2.0.0/"
        "10k_PBMC_Multiome_nextgem_Chromium_Controller/"
        "10k_PBMC_Multiome_nextgem_Chromium_Controller_filtered_feature_bc_matrix.h5"
    ),
    "10k_PBMC_Multiome_nextgem_Chromium_Controller_summary.csv": (
        "https://cf.10xgenomics.com/samples/cell-arc/2.0.0/"
        "10k_PBMC_Multiome_nextgem_Chromium_Controller/"
        "10k_PBMC_Multiome_nextgem_Chromium_Controller_summary.csv"
    ),
}


PUBLIC_DATASETS = {
    "scatac": {
        "title": "10x PBMC scATAC public tutorial data",
        "status": "manifest_only",
        "required_inputs": ["filtered_peak_bc_matrix.h5", "summary.csv"],
        "optional_inputs": ["fragments.tsv.gz", "fragments.tsv.gz.tbi", "peaks.bed"],
        "source_note": "用于 scATAC matrix-level smoke test；peak calling、FRiP/TSS 和 fragments 级分析可补充 10x fragments 后运行。",
    },
    "multiome": {
        "title": "10x Human PBMC Multiome ATAC + Gene Expression",
        "status": "manifest_only",
        "required_inputs": ["filtered_feature_bc_matrix.h5", "summary.csv"],
        "optional_inputs": ["atac_fragments.tsv.gz", "atac_fragments.tsv.gz.tbi"],
        "source_note": "用于 RNA+ATAC joint matrix smoke test；peak-gene linkage/fragments 级分析可补充 10x fragments 后运行。",
    },
    "vdj": {
        "title": "10x Cell Ranger VDJ contig/clonotype outputs",
        "status": "manifest_only",
        "required_inputs": ["filtered_contig_annotations.csv", "clonotypes.csv"],
        "source_note": "用于 scirpy/scRepertoire clonotype/diversity/VJ usage smoke test。",
    },
    "spatial": {
        "title": "10x Visium public spatial expression data",
        "status": "manifest_only",
        "required_inputs": ["filtered_feature_bc_matrix.h5", "spatial/tissue_positions*.csv", "spatial/scalefactors_json.json"],
        "optional_inputs": ["tissue_hires_image.png 或 squidpy cached image"],
        "source_note": "可用 10x Visium 或 Bioconductor TENxVisiumData；图像数据较大，建议 Slurm 单独下载。",
    },
    "cite_seq": {
        "title": "Public CITE-seq / ADT feature-barcode matrix",
        "status": "manifest_only",
        "required_inputs": ["filtered_feature_bc_matrix.h5 或 mtx + ADT features"],
        "source_note": "用于 ADT QC、DSB/CLR normalization、RNA+protein WNN smoke test。",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare public single-cell data manifest placeholders.")
    parser.add_argument("--root", type=Path, default=Path("/shared/shen/2026/ultimate"))
    parser.add_argument("--mode", choices=["manifest", "download"], default="manifest")
    args = parser.parse_args()
    root = args.root.resolve()
    generated = []
    for key, payload in PUBLIC_DATASETS.items():
        out_dir = root / "public_data" / key
        out_dir.mkdir(parents=True, exist_ok=True)
        download_result = None
        if args.mode == "download" and key == "scatac":
            download_result = _download_files(out_dir, SCATAC_DOWNLOADS, "10x PBMC scATAC filtered peak matrix and summary")
        if args.mode == "download" and key == "multiome":
            download_result = _download_files(out_dir, MULTIOME_DOWNLOADS, "10x PBMC Multiome filtered feature matrix and summary")
        if args.mode == "download" and key == "vdj":
            download_result = _download_files(out_dir, VDJ_DOWNLOADS, "10x VDJ filtered contig and clonotype tables")
        if args.mode == "download" and key == "cite_seq":
            download_result = _download_files(out_dir, CITE_SEQ_DOWNLOADS, "10x CITE-seq filtered feature-barcode matrix")
        validation_status = "ready" if download_result and download_result["status"] == "ready" else "requires_download"
        download_status = "ready" if validation_status == "ready" else payload["status"]
        reason = (
            f"{download_result['description']} downloaded."
            if validation_status == "ready"
            else "当前作业只写入公共数据契约；大文件下载与解析由后续模态 smoke job 执行。"
        )
        if download_result and download_result["status"] != "ready":
            reason = download_result["reason"]
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset_key": key,
            "download_status": download_status,
            "title": payload["title"],
            "required_inputs": payload["required_inputs"],
            "optional_inputs": payload.get("optional_inputs", []),
            "source_note": payload["source_note"],
            "validation_status": validation_status,
            "reason": reason,
        }
        if download_result:
            manifest["download_result"] = download_result
        path = out_dir / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        generated.append(str(path))
    print(json.dumps({"generated": generated}, indent=2, ensure_ascii=False))


def _download_files(out_dir: Path, downloads: dict[str, str], description: str) -> dict:
    downloaded = {}
    errors = {}
    for filename, url in downloads.items():
        target = out_dir / filename
        try:
            if target.exists() and target.stat().st_size > 0:
                downloaded[filename] = {"path": str(target), "bytes": target.stat().st_size, "cached": True}
                continue
            request = urllib.request.Request(url, headers={"User-Agent": "curl/8.0 ultimate-bioinfo-validation"})
            with urllib.request.urlopen(request, timeout=90) as response, target.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            downloaded[filename] = {"path": str(target), "bytes": target.stat().st_size, "cached": False}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors[filename] = f"{type(exc).__name__}: {exc}"
    if errors:
        return {
            "status": "network_or_download_failed",
            "description": description,
            "downloaded": downloaded,
            "errors": errors,
            "reason": "未能下载公开数据文件；常见原因是 DNS/外网受限。",
        }
    return {"status": "ready", "description": description, "downloaded": downloaded, "errors": {}}


if __name__ == "__main__":
    main()
