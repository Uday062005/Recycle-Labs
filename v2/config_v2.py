"""Minimal deployment config (the development config_v2.py holds local Aspen paths and is NOT part of this bundle)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent            # the bundle's v2 folder: data/ lives next to this file
COMPONENTS = ("PET", "HDPE", "PP")
