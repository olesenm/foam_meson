#!/usr/bin/env python3
import sys
from os import path, listdir, walk
import os
from pathlib import Path

source_root = Path(sys.argv[1])
build_root = Path(sys.argv[2])


for subdir in source_root.rglob("Make"):
    if not path.isdir(subdir):
        continue
    subdir = subdir.parent
    outdir = build_root / subdir.relative_to(source_root)
    outdir.mkdir(parents=True, exist_ok=True)
    for fp in subdir.rglob("*.[CH]"):
        outfile = outdir / fp.name
        if outfile.is_symlink():
            if outfile.readlink() != fp:
                outfile.unlink()
                outfile.symlink_to(fp)
        else:
            outfile.symlink_to(fp)

Path(build_root / "fake.h").touch()  # To make sure this script is not rerun nedlessly

# srcroot=$1
# recdir=$2
# targetdir=$PWD${recdir#"$srcroot"}

# for el in $(find "$recdir" -name '*.[CH]' ! -path '*lnInclude*'); do
#     # We use ${el##*/} instead of $(basename ${el}), because the latter is slower
#     target="$targetdir/${el##*/}"
#     if [ ! -e "$target" ]; then
#         ln -s "$el" "$target"
#     fi
# done

# # rootdir=$1
# # shift
# # for el in "$@"; do
# #     echo "$el"
# #     if [ ! -f "$el" ]; then
# #         ln -s "$rootdir/$el" "$el"
# #     fi
# # done
