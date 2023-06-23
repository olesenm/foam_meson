#!/bin/sh
# Check if you have a .C file that is not used anywhere

# Run from this directory
cd ${0%/*} || exit 1

set -e

cd ..
for i in $(find . -name '*.C' ! -path '*lnInclude*' | sed 's#.*/##'); do
 rg $i -q > /dev/null || echo "dead code:" $i
done
