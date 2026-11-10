"""Frozen console entry point; execute the shipped CLI with its real script path."""

# These imports also make PyInstaller collect the standard-library modules used
# by the dynamically executed CLI. Blender-only modules remain in shipped scripts.
import argparse
import ctypes
import fnmatch
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import time
import uuid
import urllib.parse
import xml.etree.ElementTree
from pathlib import Path


if __name__ == "__main__":
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / "msfs_universal.py"), run_name="__main__")
