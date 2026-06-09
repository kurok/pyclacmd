"""Legacy shim so that ``pip install -e .`` works on older pip/setuptools
that do not yet support PEP 660 editable installs from pyproject alone.

All project metadata lives in ``pyproject.toml``.
"""
from setuptools import setup

setup()
