"""RouteLake: one dataset, two engines, one cost brain.

A zero-dependency reference implementation of a cost-aware lakehouse control
plane: contract-validated medallion pipeline, a workload router that picks
Snowflake or Databricks per workload, and billing-based anomaly detection.

Built by Analyst Rushi.
"""
from pathlib import Path

__version__ = "1.0.0"

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
CONTRACT_DIR = ROOT / "contracts"
SAMPLE_DIR = ROOT / "data" / "sample"
