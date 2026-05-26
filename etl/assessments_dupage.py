"""DuPage assessments are loaded as a side effect of characteristics_dupage.py
(both come from the same Downers Grove Township Excel). This module exists so the
Makefile can call a stable entry point.
"""
from .characteristics_dupage import load

if __name__ == "__main__":
    load()
