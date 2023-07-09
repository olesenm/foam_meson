#!/bin/sh
# Maintainer: Volker Weißmann (volker.weissmann@gmx.de)

set -euo pipefail
IFS=$'\n\t'

# If you see something like
# run_command(meson.source_root() + '/meson/rec_C.sh', 'some/path', check: true).stdout().strip().split('\n')
# in a meson.build file, this means: "all files from this directory (recursive)"
for i in $(find $1 -name '*.C' ! -path '*lnInclude*'); do
  echo $i
done
