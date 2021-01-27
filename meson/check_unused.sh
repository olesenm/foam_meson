#!/bin/sh

# Run from this directory
cd ${0%/*} || exit 1

set -e

cd ..
for i in $(find . -name '*.C' ! -path '*lnInclude*' | sed 's#.*/##'); do
 rg $i -q > /dev/null || echo "dead code:" $i
done