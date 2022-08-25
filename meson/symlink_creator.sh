#!/bin/sh
set -e

srcroot=$1
recdir=$2
targetdir=$PWD${recdir#"$srcroot"}

for el in $(find "$recdir" -name '*.[CH]' ! -path '*lnInclude*'); do
    # We use ${el##*/} instead of $(basename ${el}), because the latter is slower
    target="$targetdir/${el##*/}"
    if [ ! -e "$target" ]; then
        ln -s "$el" "$target"
    fi
done

# rootdir=$1
# shift
# for el in "$@"; do
#     echo "$el"
#     if [ ! -f "$el" ]; then
#         ln -s "$rootdir/$el" "$el"
#     fi
# done
