#!/bin/sh
#------------------------------------------------------------------------------
#
# Copyright (C) 2023 Volker Weissmann
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Description
#
# Maintainer: Volker Weißmann (volker.weissmann@gmx.de)
#------------------------------------------------------------------------------

set -eu
# If I set IFS=$'\n\t', this fails on debian for strange reasons

rootdir="$1"
workdir="$2"
lemonbin="$3"
input="$4"
output="$5"

dir="$(dirname -- $input)"
outdir="$(dirname -- $output)"
baseout=$(echo "$output" | cut -f 1 -d '.')

m4 -I"$dir" -I"$rootdir/src/OpenFOAM/include" $input > "$baseout.lyy"

"$lemonbin" -T"$rootdir/wmake/etc/lempar.c" -d"$outdir" -ecc -Dm4 "$baseout.lyy"

#------------------------------------------------------------------------------
