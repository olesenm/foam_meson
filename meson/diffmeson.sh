#!/bin/bash


find ~/Sync/git/openfoam -name meson.build -exec echo {}  \; -exec cat {} \; > new.txt
diff new.txt old.txt
