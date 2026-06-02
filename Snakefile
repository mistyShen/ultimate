configfile: "config/project.yaml"

rule all:
    input:
        lambda wildcards: config["project"]["output_dir"] + "/run_manifest.json"

rule ultimate_run:
    output:
        config["project"]["output_dir"] + "/run_manifest.json"
    shell:
        "ultimate run --config config/project.yaml"
