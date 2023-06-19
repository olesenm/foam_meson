#!/usr/bin/env python3
import os
from os import path
import sys
import subprocess
import heuristics


def from_this_directory():
    os.chdir(path.dirname(sys.argv[0]))


from_this_directory()
os.chdir("..")


for el in heuristics.broken_dirs() + heuristics.scanning_disabled():
    if not path.exists(el):
        print(f"Warning: Why is {el} marked as broken, even though it does not exist?")
        continue
    # wmake could exit with a non-zero exit-code if something needed for linking has not been build yet. So we disable all linking errors by adding "meson/shim" to $PATH
    out = subprocess.run(
        [
            "bash",
            "-c",
            f"source etc/bashrc; export PATH=\"$PWD/meson/shim:$PATH\"; cd '{el}' ; wmake",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if out.returncode == 0:
        print(
            f"Warning: Why is {el} marked as broken, even though compilation works fine?"
        )
