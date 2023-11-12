#!/bin/sh
#------------------------------------------------------------------------------
#
# Copyright (C) 2023 Volker Weissmann
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Description
#     Check if you have a .C file that is not used anywhere
#
#------------------------------------------------------------------------------
cd "${0%/*}" || exit  # Run from this directory

set -e

cd ..
for i in $(find . -name '*.C' ! -path '*lnInclude*' | sed 's#.*/##'); do
 rg $i -q > /dev/null || echo "dead code:" $i
done

#------------------------------------------------------------------------------
