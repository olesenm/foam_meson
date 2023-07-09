#!/usr/bin/env python3
# Maintainer: Volker Weißmann (volker.weissmann@gmx.de)

import sys
from os import path, listdir, walk
import os
from pathlib import Path

source_root = Path(sys.argv[1])
build_root = Path(sys.argv[2])


def create_symlinks_for_dir(subdir):
    outdir = build_root / subdir.relative_to(source_root)
    outdir.mkdir(parents=True, exist_ok=True)
    for fp in subdir.rglob("*.[CHh]"):
        if "lnInclude" in fp.parts:
            continue
        if (
            fp.name
            # Todo: explain that this lyy-m4 stuff, perhaps build this list dynamically
            in [  # ugly name collisions. I hope this does not result in any problems.
                "fieldExprLemonParser.h",
                "patchExprLemonParser.h",
                "volumeExprLemonParser.h",
            ]
        ):
            continue
        outfile = outdir / fp.name
        # Todo: document that this depends on the order of the inode numbers
        if outfile.is_symlink():
            if os.readlink(outfile) != str(fp):
                outfile.unlink()
                outfile.symlink_to(fp)
        else:
            outfile.symlink_to(fp)


for subdir in source_root.rglob("Make"):
    if not path.isdir(subdir):
        continue
    subdir = subdir.parent
    create_symlinks_for_dir(subdir)

for (
    el
) in [  # These are the only directories found using `rg wmakeLnInclude` that do not have a `Make`` subdirectory
    "src/TurbulenceModels/phaseCompressible",
    "src/TurbulenceModels/phaseIncompressible",
]:
    create_symlinks_for_dir(source_root / el)

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
