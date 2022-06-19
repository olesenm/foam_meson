#!/bin/false

import os
import re
import copy
import graphlib
from collections import defaultdict
from pathlib import Path

dryrun = False
if dryrun:
	print("##################### WARNING: DRYRUNNING ################################")

def remove_prefix(line, search):
	assert line.startswith(search), line + " -----  " + search
	line = line[len(search):]
	return line.lstrip()

def remove_suffix(line, search):
	assert line.endswith(search), line + " -----  " + search
	line = line[:-len(search)]
	return line.rstrip()

def writef(path, data):
	if dryrun:
		return
	with open(path, "w") as ofile:
		ofile.write(data)

class Node:
	def __init__(self, ddeps, template, ideal):
		self.ddeps = ddeps
		self.template = template
		self.ideal = ideal

class BuildDesc:
	def __init__(self, root):
		self.root = root
		self.elements = {}
		self.rdeps = {}
		self.custom_prefixes = {}

	def set_custom_prefix(self, path, custom):
		assert path.parts[-1] == "meson.build"
		assert path.is_absolute()
		self.custom_prefixes[path] = custom

	def add_template(self, provides, depends, template, ideal_path):
		ideal = os.path.normpath(ideal_path)
		ideal = remove_prefix(ideal, str(self.root))
		assert len(ideal) == 0 or ideal[0] == os.path.sep
		ideal = Path(ideal[1:]).parts
		assert provides not in depends
		assert provides not in self.elements, "you cannot have multiple targets with the same name: " + str(provides)
		self.elements[provides] = Node(depends, template, ideal)

	def starts_with(self, subgroup, ideal):
		depth = len(subgroup)
		if depth > len(ideal):
			return False
		for i in range(depth):
			if ideal[i] != subgroup[i]:
				return False
		return True

	def generalised_deps(self, subgroup, el):
		depth = len(subgroup)
		ret = set()
		for dep in el.ddeps:
			if not self.starts_with(subgroup, self.elements[dep].ideal):
				continue
			if len(self.elements[dep].ideal) == depth:
				ret.add(dep)
			else:
				ndir = self.elements[dep].ideal[depth]
				if depth >= len(el.ideal) or ndir != el.ideal[depth]:
					ret.add(Path(ndir))
		return ret

	# Finds the reason why a directory depends directly on a file
	def get_dep_reason_1(self, subgroup, dir_source, file_target):
		depth = len(subgroup)
		mixed_deps = {}
		for (key, el) in self.elements.items():
			if not self.starts_with(subgroup, el.ideal):
				continue
			if len(el.ideal) == depth:
				continue
			if Path(el.ideal[depth]) != dir_source:
				continue
			if file_target in el.ddeps:
				return key
		raise ValueError

	# Finds the reason why a file depends directly on a directory
	def get_dep_reason_2(self, subgroup, file_source, dir_target):
		depth = len(subgroup)
		el = self.elements[file_source]
		for dep in el.ddeps:
			if not self.starts_with(subgroup, self.elements[dep].ideal):
				continue
			if len(self.elements[dep].ideal) == depth:
				continue
			ndir = self.elements[dep].ideal[depth]
			if depth >= len(el.ideal) or ndir != el.ideal[depth]:
				if Path(ndir) == dir_target:
					return dep
		return None

	# Finds the reason why a directory depends directly on a directory
	def get_dep_reason_3(self, subgroup, dir_source, dir_target):
		depth = len(subgroup)
		mixed_deps = {}
		for (key, el) in self.elements.items():
			if not self.starts_with(subgroup, el.ideal):
				continue
			if len(el.ideal) == depth:
				continue
			if Path(el.ideal[depth]) != dir_source:
				continue

			ret = self.get_dep_reason_2(subgroup, key, dir_target)
			if ret is not None:
				return (key, ret)
		raise ValueError

	def writer_recursion(self, generated_files, subgroup):
		depth = len(subgroup)
		mixed_deps = {}
		for (key, el) in self.elements.items():
			if not self.starts_with(subgroup, el.ideal):
				continue
			if len(el.ideal) == depth:
				mixed_deps[key] = self.generalised_deps(subgroup, el)
			else:
				pkey = Path(el.ideal[depth])
				if pkey not in mixed_deps:
					mixed_deps[pkey] = set()
				mixed_deps[pkey].update(self.generalised_deps(subgroup, el))

		ts = graphlib.TopologicalSorter(mixed_deps)
		try:
			order = tuple(ts.static_order())
		except graphlib.CycleError as ex:
			print("UNABLE TO CODEGEN BECAUSE OF CYCLE IN: ", subgroup)
			cycle = ex.args[1]
			cycle.reverse()
			firstlineindent = 0
			indent = 0
			reason = None

			for i in range(len(cycle)-1):
				print(" "*len("depends on: "), end="")
				if isinstance(cycle[i], Path) and isinstance(cycle[i+1], str):
		 			print(self.get_dep_reason_1(subgroup, cycle[i], cycle[i+1]), end=" in ")
				elif isinstance(cycle[i], Path) and isinstance(cycle[i+1], Path):
			 		print(self.get_dep_reason_3(subgroup, cycle[i], cycle[i+1])[0], end=" in ")

				print(cycle[i])

				print("depends on: ", end="")

				if isinstance(cycle[i], str) and isinstance(cycle[i+1], Path):
		 			print(self.get_dep_reason_2(subgroup, cycle[i], cycle[i+1]), end=" in ")
				elif isinstance(cycle[i], Path) and isinstance(cycle[i+1], Path):
			 		print(self.get_dep_reason_3(subgroup, cycle[i], cycle[i+1])[1], end=" in ")
				print(cycle[i+1])
			exit(1)
		
		outpath = Path(self.root, *subgroup, "meson.build")
		generated_files[outpath] = []
		total = ""
		for el in order:
			if isinstance(el, Path):
				total += "subdir('" + str(el) + "')\n"
			else:
				total += "\n" + self.elements[el].template.export_relative(Path(self.root, *subgroup)) + "\n"
				generated_files[outpath].append(el)

		if outpath in self.custom_prefixes:
			total = self.custom_prefixes[outpath] + "\n\n" + total

		writef(outpath, total)

		entries = set()
		for (key, el) in self.elements.items():
			if self.starts_with(subgroup, el.ideal):
				if len(subgroup) != len(el.ideal):
					entries.add(el.ideal[len(subgroup)])

		for dir in entries:
			self.writer_recursion(generated_files, subgroup + [dir])

	def writeToFileSystem(self):
		generated_files = {}
		self.writer_recursion(generated_files, [])
		return generated_files


class Template:
	regex = re.compile("<PATH>(.*?)</PATH>")
	def export_relative(self, dir):
		def file_matcher(mobj):
			path = mobj.group(1)
			assert os.path.isabs(path)
			path = os.path.relpath(path, str(dir))
			return path
		return self.regex.sub(file_matcher, self.temp)

	def __init__(self, temp):
		self.temp = temp

	def make_absolute(self, dir):
		def file_matcher(mobj):
			path = mobj.group(1)
			if not os.path.isabs(path):
				abs = dir / path
				assert os.path.exists(abs), abs
				path = str(abs)
			assert os.path.isabs(path)
			return "<PATH>" + path + "</PATH>"
		self.temp = self.regex.sub(file_matcher, self.temp)

	def assert_absolute(self):
		for path in self.regex.findall(self.temp):
			assert os.path.isabs(path)

	def cleanup(self):
		def file_matcher(mobj):
			path = mobj.group(1)
			path = os.path.normpath(path)
			return "<PATH>" + path + "</PATH>"
		self.temp = self.regex.sub(file_matcher, self.temp)

def largest_commons_prefix(paths):
	paths = [os.path.normpath(path) for path in paths]
	com = os.path.commonpath(paths)
	assert os.path.exists(com), com
	if os.path.isfile(com):
		com = os.path.dirname(com)
	return com
