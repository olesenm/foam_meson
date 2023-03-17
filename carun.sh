#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
./meson/generate_meson_build.py
sudo podman cp for_openfoam_commit_hash_988ec18ecc.diff foam_debian:/root
