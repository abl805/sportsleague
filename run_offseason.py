"""
Advance a completed season by one offseason stage.

Usage:
    python run_offseason.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from league.offseason import advance_offseason_from_default_db


def main():
    try:
        advance_offseason_from_default_db(verbose=True)
    except RuntimeError as exc:
        print(f"\nCannot run offseason: {exc}\n")


if __name__ == "__main__":
    main()
