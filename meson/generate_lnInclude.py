#!/usr/bin/env python3

# This script will recursively walk the current PWD and search for folders
# called "Make". If It finds one, it creates a folder called "lnInclude" next to
# it and puts symlinks to every C/C++ source file inside this lnInclude folder.
# Example:
# Before
# ```
# $ tree
# .
# └── mydir
#     ├── a.H
#     ├── Make
#     └── sub
#         └── b.H
# $ /path/to/generate_lnInclude.py
# $ tree
# .
# └── mydir
#     ├── a.H
#     ├── lnInclude
#     │   ├── a.H -> ../a.H
#     │   └── b.H -> ../sub/b.H
#     ├── Make
#     └── sub
#         └── b.H
# ```

# Why do we need this script?
# If some file contains the line
# #include "b.H"
# we need to make sure this file is found. I see 3 ways to do this:
# 1. Add the -I/path/to/mydir/sub compiler flag
# 2. Create the lnInclude symlinks as explained above and add the -I/path/to/mydir/lnInclude compiler flag
# 3. Create these lnInclude symlinks in the build directory and add the -I/path/to/buildir/something compiler flag.
#
# The problem with 1. is that it results in really, really long compilation
# commands, since we do need both -I/path/to/mydir/sub and -I/path/to/mydir/
# because we do not know wheter a.H or b.H will be included. The compilation
# commands get so long that the build fails with:
# c++: fatal error: cannot execute ‘/usr/lib/gcc/x86_64-pc-linux-gnu/10.2.0/cc1plus’: execv: Argument list too long
# You can enable 1. by setting USING_LNINCLUDE = False in generate_meson_build.py.
#
# Since build artifacts in the source tree are bad practice, 3. would be
# somewhat nicer than 2. . But the advantage of 2. is that we use the same
#    lnInclude folders as wmake does, making comparing them and debugging
#    differences somewhat easier. Also, I'm to lazy to implement 3. .
#
# The wmake/wmakeLnInclude contains the code that generates the symlinks if you
# use wmake instead of meson.


# Tip: Use this to remove all the lnInclude directories:
# find -name lnInclude -exec rm -r {} \;

from os import path, listdir, walk, symlink, unlink, readlink
import os
import pprint
import pathlib

source_file_endings = ["hpp", "cpp", "H", "C", "h", "C"]

# Generates the list of symlinks that should exist.
def gen_symlink_list(input, output):
    symlinks = []
    for entries in walk(input, topdown=False):
        flag = False
        if entries[0] == output:
            continue
        if "lnInclude" in pathlib.Path(entries[0]).parts:
            continue
        for fp in entries[2]:
            if "." in fp and fp.split(".")[-1] in source_file_endings:
                symlink_to = path.relpath(path.join(entries[0], fp), start=output)
                symlink_from = path.join(output, fp)
                symlinks.append((symlink_from, symlink_to))
    return symlinks


# Checks whether the list of symlinks contains something like
# (lnInclude/a.C, subFolder/a.C)
# (lnInclude/a.C, otherSubFolder/a.C)
# Which would be a problem since we cannot create two different symlinks at the
# same path. If no such conflicts are found, an empty dictionary is returned.
def symlink_list_conflicts(symlinks):
    froms = [el[0] for el in symlinks]
    fromset = set(froms)
    # This early return gives us a small performance boost
    if len(froms) == len(fromset):
        return {}

    ret = {}
    for symlink_from in fromset:
        ar = [el[1] for el in symlinks if el[0] == symlink_from]
        assert len(ar) >= 1
        if len(ar) > 1:
            ret[symlink_from] = ar
    return ret


def create_symlinks(symlinks):
    for (symlink_from, symlink_to) in symlinks:
        if os.path.exists(symlink_from):
            assert readlink(symlink_from) == symlink_to
        else:
            symlink(symlink_to, symlink_from)


def gen_lnInclude(topdir):
    for entries in walk(topdir, topdown=False):
        if "Make" in entries[1]:
            assert not entries[0].endswith("lnInclude")
            output = path.join(entries[0], "lnInclude")
            symlinks = gen_symlink_list(entries[0], output)
            conflicts = symlink_list_conflicts(symlinks)
            if len(conflicts) == 0:
                if not os.path.exists(output):
                    os.mkdir(output)
                create_symlinks(symlinks)
            else:
                print(f"Warning: Unable to generate {output} due to conflicts:")
                for (symlink_from, ar) in conflicts.items():
                    print(
                        f"\tTo which one of the following files should the symlink at {symlink_from} point to?"
                    )
                    for symlink_to in ar:
                        print("\t\t", symlink_to)


gen_lnInclude(".")
