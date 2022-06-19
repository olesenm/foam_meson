#!/usr/bin/env python3

from os import path, listdir, walk, symlink, unlink, readlink
import os

source_file_endings = ["hpp", "cpp", "H", "C", "h", "C"]
def gen_symlinks(input, output):
	for entries in walk(input, topdown=False):
		flag = False
		if entries[0] == output:
			continue
		for fp in entries[2]:
			if fp.split(".")[-1] in source_file_endings:
				tot = path.join(entries[0], fp)
				target = path.join(output, fp)
				tot = path.relpath(tot, start=output)
				if path.islink(target) and not path.exists(path.join(output, readlink(target))):
					os.unlink(target)
				if not path.exists(target) and not path.islink(target):
					symlink(tot, target)
				assert path.exists(path.join(output, readlink(target)))

def scan_path(dirpath):
	for entries in walk(".", topdown=False):
		#if "Make" in entries[1]:
		if not entries[0].endswith("lnInclude"):
			output = path.join(entries[0], "lnInclude")
			if not os.path.exists(output):
				os.mkdir(output)
			gen_symlinks(entries[0], output)
		# for dp in entries[1]:
		# 	if dp == "lnInclude":
		# 		gen_symlinks(entries[0], path.join(entries[0], dp))

scan_path(".")