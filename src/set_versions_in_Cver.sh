#!/usr/bin/env bash
# Maintainer: Volker Weißmann (volker.weissmann@gmx.de)

root_path="$1"
input="$2"
output="$3"
shift
shift
source "$root_path/etc/bashrc"

set -euo pipefail
IFS=$'\n\t'

"$root_path/wmake/scripts/wmake-build-info" -update -filter "$input" > "$output"
