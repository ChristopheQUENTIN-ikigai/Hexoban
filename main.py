#!/usr/bin/env python3
"""Hexoban (Hexagonal Sokoban) — run: python main.py"""
import sys
import os

# Ensure the project root is on sys.path and is the working directory,
# regardless of where the script is launched from.
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.chdir(_project_root)

from src.game import main

if __name__ == "__main__":
    main()
