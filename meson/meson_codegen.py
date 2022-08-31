#!/bin/false
# generate_meson_build.py gives the recipes we want to build to this file. This file then sorts them, makes the paths relative and as short as possible (e.g. abc/../abc is just abc), splits the recipes among different meson.build files and finally writes it out to disk.
# Grep for EXPLAIN_CODEGEN will help you understand it


import os
import re
import copy
import graphlib
from collections import defaultdict
from pathlib import Path
import typing as T
from dataclasses import dataclass

# make sure that it will not create files outside of the project root
dryrun = False
if dryrun:
    print("##################### WARNING: DRYRUNNING ################################")


def remove_prefix(line, search):
    assert line.startswith(search), line + " -----  " + search
    line = line[len(search) :]
    return line.lstrip()


def remove_suffix(line, search):
    assert line.endswith(search), line + " -----  " + search
    line = line[: -len(search)]
    return line.rstrip()


# Template is essentially a wrapper around a string (Template.temp is a string), but with '<PATH>/some/path</PATH>' instead of '/some/path', which allows us to do things like: Replace all absolute paths with equivalent relative paths
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


# A Node represents one recipe that we need to put in some meson.build file.
@dataclass
class Node:
    # The opposite of ddeps
    provides: str
    # template.temp is the the recipe as a string, but with '<PATH>/some/path</PATH>' instead of '/some/path'
    template: Template
    # Direkt Dependencies of this recipe
    ddeps: list[str]
    # Path of the meson.build file to put this recipe in. E.g.
    # ('applications', 'solvers', 'DNS', 'dnsFoam')
    outpath: tuple[str]
    # Will be printed in some warnings/error messages
    debuginfo: str


class BuildDesc:
    def __init__(self, root):
        self.root = root
        self.elements = {}
        self.rdeps = {}
        self.custom_prefixes = {}

    # This method will write some meson.build files to disk. They are broken and
    # will not build, but reading them and this function will make understanding the rest of this
    # file easier. Enable this by setting EXPLAIN_CODEGEN = True in generate_meson_build.py
    def explainatory_helper(self):
        os.system("find '" + str(self.root) + "' -name meson.build -delete ")

        for (path, prefix) in self.custom_prefixes.items():
            with open(path, "a") as ofile:
                ofile.write(prefix)

        for (key, el) in self.elements.items():
            recipe = el.template.temp.replace("<PATH>", "").replace("</PATH>", "")
            outpath = Path(self.root, *el.outpath, "meson.build")
            with open(outpath, "a") as ofile:
                ofile.write(recipe)

    def set_custom_prefix(self, path, custom):
        assert path.parts[-1] == "meson.build"
        assert path.is_absolute()
        self.custom_prefixes[path] = custom

    def add_node(self, node: Node):
        assert node.provides not in node.ddeps
        assert (
            node.provides not in self.elements
        ), "you cannot have multiple targets with the same name: " + str(node.provides)
        self.elements[node.provides] = node

    def starts_with(self, subgroup, outpath):
        depth = len(subgroup)
        if depth > len(outpath):
            return False
        for i in range(depth):
            if outpath[i] != subgroup[i]:
                return False
        return True

    def generalised_deps(self, subgroup, el):
        depth = len(subgroup)
        ret = set()
        for dep in el.ddeps:
            if dep not in self.elements:
                print(
                    f"ERROR: The following recipe depends on {dep} but there is no recipe that provides it:\n"
                    + "-" * 50
                    + "\n"
                    + el.template.temp
                    + "-" * 50
                    + "\n"
                    + el.debuginfo
                )
                exit(1)
            self.elements[dep]
            if not self.starts_with(subgroup, self.elements[dep].outpath):
                continue
            if len(self.elements[dep].outpath) == depth:
                ret.add(dep)
            else:
                ndir = self.elements[dep].outpath[depth]
                if depth >= len(el.outpath) or ndir != el.outpath[depth]:
                    ret.add(Path(ndir))
        return ret

    # Finds the reason why a directory depends directly on a file
    def get_dep_reason_1(self, subgroup, dir_source, file_target):
        depth = len(subgroup)
        mixed_deps = {}
        for (key, el) in self.elements.items():
            if not self.starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                continue
            if Path(el.outpath[depth]) != dir_source:
                continue
            if file_target in el.ddeps:
                return key
        raise ValueError

    # Finds the reason why a file depends directly on a directory
    def get_dep_reason_2(self, subgroup, file_source, dir_target):
        depth = len(subgroup)
        el = self.elements[file_source]
        for dep in el.ddeps:
            if not self.starts_with(subgroup, self.elements[dep].outpath):
                continue
            if len(self.elements[dep].outpath) == depth:
                continue
            ndir = self.elements[dep].outpath[depth]
            if depth >= len(el.outpath) or ndir != el.outpath[depth]:
                if Path(ndir) == dir_target:
                    return dep
        return None

    # Finds the reason why a directory depends directly on a directory
    def get_dep_reason_3(self, subgroup, dir_source, dir_target):
        depth = len(subgroup)
        mixed_deps = {}
        for (key, el) in self.elements.items():
            if not self.starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                continue
            if Path(el.outpath[depth]) != dir_source:
                continue

            ret = self.get_dep_reason_2(subgroup, key, dir_target)
            if ret is not None:
                return (key, ret)
        raise ValueError

    def writer_recursion(self, generated_files, subgroup):
        depth = len(subgroup)
        mixed_deps = {}
        for (key, el) in self.elements.items():
            if not self.starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                mixed_deps[key] = self.generalised_deps(subgroup, el)
            else:
                pkey = Path(el.outpath[depth])
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

            for i in range(len(cycle) - 1):
                print(" " * len("depends on: "), end="")
                if isinstance(cycle[i], Path) and isinstance(cycle[i + 1], str):
                    print(
                        self.get_dep_reason_1(subgroup, cycle[i], cycle[i + 1]),
                        end=" in ",
                    )
                elif isinstance(cycle[i], Path) and isinstance(cycle[i + 1], Path):
                    print(
                        self.get_dep_reason_3(subgroup, cycle[i], cycle[i + 1])[0],
                        end=" in ",
                    )

                print(cycle[i])

                print("depends on: ", end="")

                if isinstance(cycle[i], str) and isinstance(cycle[i + 1], Path):
                    print(
                        self.get_dep_reason_2(subgroup, cycle[i], cycle[i + 1]),
                        end=" in ",
                    )
                elif isinstance(cycle[i], Path) and isinstance(cycle[i + 1], Path):
                    print(
                        self.get_dep_reason_3(subgroup, cycle[i], cycle[i + 1])[1],
                        end=" in ",
                    )
                print(cycle[i + 1])
            exit(1)

        outpath = Path(self.root, *subgroup, "meson.build")
        generated_files[outpath] = []
        total = ""
        for el in order:
            if isinstance(el, Path):
                total += "subdir('" + str(el) + "')\n"
            else:
                total += (
                    "\n"
                    + self.elements[el].template.export_relative(
                        Path(self.root, *subgroup)
                    )
                    + "\n"
                )
                generated_files[outpath].append(el)

        if outpath in self.custom_prefixes:
            total = self.custom_prefixes[outpath] + "\n\n" + total

        self.writef(outpath, total)

        entries = set()
        for (key, el) in self.elements.items():
            if self.starts_with(subgroup, el.outpath):
                if len(subgroup) != len(el.outpath):
                    entries.add(el.outpath[len(subgroup)])

        for dir in entries:
            self.writer_recursion(generated_files, subgroup + [dir])

    # todo: verify that this will never write outside of the project directory
    def writeToFileSystem(self):
        generated_files = {}
        self.writer_recursion(generated_files, [])
        return generated_files

    def writef(self, path, data):
        if dryrun:
            return
        assert os.path.normpath(path).startswith(str(self.root) + "/")
        with open(path, "w") as ofile:
            ofile.write(data)


def largest_commons_prefix(paths):
    paths = [os.path.normpath(path) for path in paths]
    com = os.path.commonpath(paths)
    assert os.path.exists(com), com
    if os.path.isfile(com):
        com = os.path.dirname(com)
    return com
