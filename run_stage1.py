#!/usr/bin/env python3
"""One-command Stage 1 pipeline: validate, aggregate, fetch weather, train/backtest."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STEPS = [
    "scripts/inspect_turbine_data.py",
    "scripts/build_hourly_dataset.py",
    "scripts/join_weather_data.py",
    "scripts/train_stage1.py",
]

for script in STEPS:
    print(f"\n>>> {script}", flush=True)
    subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=True)
