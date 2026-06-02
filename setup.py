from __future__ import annotations

from setuptools import find_packages, setup


setup(
    name="ultimate-bioinfo",
    version="0.1.0",
    description="CLI-first reproducible multi-omics bioinformatics workbench for HPC delivery.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    package_data={"ultimate": ["templates/*.j2"]},
    install_requires=[
        "click>=8.1",
        "jinja2>=3.1",
        "matplotlib>=3.8",
        "numpy>=1.26",
        "pandas>=2.2",
        "pyyaml>=6.0",
        "seaborn>=0.13",
    ],
    extras_require={"dev": ["pytest>=8.0"]},
    entry_points={"console_scripts": ["ultimate=ultimate.cli:main"]},
    python_requires=">=3.11",
)
