"""Locate the installable skill separately from repository-only tests."""
from pathlib import Path
import sys

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "kompass-3d-skill"
SCRIPTS_DIR = SKILL_DIR / "scripts"
PREPARE_DIR = SCRIPTS_DIR / "prepare"
sys.path[:0] = [str(SCRIPTS_DIR), str(PREPARE_DIR)]
