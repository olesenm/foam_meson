#!/bin/false
#--------------------------------*- python -*----------------------------------
#
# Copyright (C) 2023 Volker Weissmann
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Description
#   generate_meson_build.py gives the recipes we want to build to this
#   file. This file then sorts them, makes the paths relative and as
#   short as possible (e.g. abc/../abc is just abc), splits the recipes
#   among different meson.build files and finally writes it out to disk.
#
#   Grep for EXPLAIN_CODEGEN will help you understand it
#
#------------------------------------------------------------------------------
import os
import sys
import re
from pathlib import Path
import typing as T
import math
from .grouped_topo_sort import grouped_topo_sort

DRYRUN = False

if DRYRUN:
    print("##################### WARNING: DRYRUNNING ################################")


def remove_prefix(line, search):
    assert line.startswith(search), line + " -----  " + search
    line = line[len(search) :]
    return line.lstrip()


def remove_suffix(line, search):
    assert line.endswith(search), line + " -----  " + search
    line = line[: -len(search)]
    return line.rstrip()


# `a in build_reachable_dict(graph)[b]` is true exactly if there is a path form `a` to `b`.
def build_reachable_dict(graph):
    ret = {}
    for k1, v1 in graph.items():
        ret[k1] = set()
        for x in v1:
            ret[k1].add(x)
            if x in ret:
                ret[k1].update(ret[x])
        for v2 in ret.values():
            if k1 in v2:
                v2.update(ret[k1])
    return ret


# https://en.wikipedia.org/wiki/Floyd%E2%80%93Warshall_algorithm
def find_shortest_cycle(graph):
    dist = {k2: {k1: math.inf for k1 in graph} for k2 in graph}
    for u in graph:
        # dist[u][u] = 0
        for v in graph[u]:
            dist[u][v] = 1
    for k in graph:
        for i in graph:
            for j in graph:
                if dist[i][j] > dist[i][k] + dist[k][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]

    cycle = [min((dist[k][k], k) for k in graph)[1]]
    while cycle[0] != cycle[-1] or len(cycle) == 1:
        cycle.append(min((dist[k][cycle[0]], k) for k in graph[cycle[-1]])[1])
    return cycle


def starts_with(a, b):
    depth = len(a)
    if depth > len(b):
        return False
    for i in range(depth):
        if b[i] != a[i]:
            return False
    return True


class BugDetected(Exception):
    pass


# Template is essentially a wrapper around a string (Template.temp is a string), but with '<PATH>/some/path</PATH>' instead of '/some/path', which allows us to do things like: Replace all absolute paths with equivalent relative paths
class Template:
    regex = re.compile("<PATH>(.*?)</PATH>")

    def export_relative(self, direct):
        def file_matcher(mobj):
            path = mobj.group(1)
            assert os.path.isabs(path)
            path = os.path.relpath(path, str(direct))
            return path

        return self.regex.sub(file_matcher, self.temp)

    def __init__(self, temp):
        self.temp = temp

    def make_absolute(self, direct):
        def file_matcher(mobj):
            path = mobj.group(1)
            if not os.path.isabs(path):
                abspath = direct / path
                assert os.path.exists(abspath), abspath
                path = str(abspath)
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
class Node:
    # The opposite of ddeps
    provides: str
    # template.temp is the the recipe as a string, but with '<PATH>/some/path</PATH>' instead of '/some/path'
    template: Template
    # Direkt Dependencies of this recipe
    ddeps: T.List[str]
    # Ideal path of the meson.build file to put this recipe in. E.g.
    # ('applications', 'solvers', 'DNS', 'dnsFoam')
    ideal_path: T.Tuple[str]
    # Will be printed in some warnings/error messages
    debuginfo: str

    def __init__(self, provides, template, ddeps, ideal_path, debuginfo):
        self.provides = provides
        self.template = template
        self.ddeps = ddeps
        self.ideal_path = ideal_path
        self.debuginfo = debuginfo


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

        for path, prefix in self.custom_prefixes.items():
            with open(path, "a", encoding="utf-8") as ofile:
                ofile.write(prefix)

        for el in self.elements.values():
            recipe = el.template.temp.replace("<PATH>", "").replace("</PATH>", "")
            outpath = Path(self.root, *el.outpath, "meson.build")
            with open(outpath, "a", encoding="utf-8") as ofile:
                ofile.write(recipe)

    # todo: documentation
    def set_outpaths(self):
        grouped_topo_sort(self.elements)
        count = 0
        for target in self.elements.values():
            if target.ideal_path != target.outpath:
                count += 1
                ideal = "/".join(target.ideal_path) + "/meson.build"
                op = "/".join(target.outpath) + "/meson.build"
                print(
                    f"We would like to put the target '{target.provides}' into '{ideal}', but due to some graph theory stuff this is impossible/hard so we put it into '{op}' instead."
                )
        print(f"{count} target(s) will not be in their preferred directory.")

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

    def remove_what_depends_on(self, broken_provides: T.List[str]):
        for el in broken_provides:
            assert el not in self.elements
        broken_provides = set(broken_provides)
        while True:
            oldlen = len(broken_provides)
            broken_provides.update(
                [
                    k
                    for k, v in self.elements.items()
                    if not set(v.ddeps).isdisjoint(broken_provides)
                ]
            )
            if len(broken_provides) == oldlen:
                break
        self.elements = {
            k: v for k, v in self.elements.items() if k not in broken_provides
        }

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
                sys.exit(1)
            if not starts_with(subgroup, self.elements[dep].outpath):
                continue
            if len(self.elements[dep].outpath) == depth:
                ret.add(dep)
            else:
                ndir = self.elements[dep].outpath[depth]
                if depth >= len(el.outpath) or ndir != el.outpath[depth]:
                    ret.add(Path(ndir))
        return ret

    # Finds the reason why a directory depends directly on a file
    def get_dep_reason_dir_file(self, subgroup, dir_source, file_target):
        depth = len(subgroup)
        for key, el in self.elements.items():
            if not starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                continue
            if Path(el.outpath[depth]) != dir_source:
                continue
            if file_target in el.ddeps:
                return key
        raise ValueError

    # Finds the reason why a file depends directly on a directory
    def get_dep_reason_file_dir(self, subgroup, file_source, dir_target):
        depth = len(subgroup)
        el = self.elements[file_source]
        for dep in el.ddeps:
            if not starts_with(subgroup, self.elements[dep].outpath):
                continue
            if len(self.elements[dep].outpath) == depth:
                continue
            ndir = self.elements[dep].outpath[depth]
            if depth >= len(el.outpath) or ndir != el.outpath[depth]:
                if Path(ndir) == dir_target:
                    return dep
        return None

    # Finds the reason why a directory depends directly on a directory
    def get_dep_reason_dir_dir(self, subgroup, dir_source, dir_target):
        depth = len(subgroup)
        for key, el in self.elements.items():
            if not starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                continue
            if Path(el.outpath[depth]) != dir_source:
                continue

            ret = self.get_dep_reason_file_dir(subgroup, key, dir_target)
            if ret is not None:
                return (key, ret)
        raise ValueError

    def error_out_due_to_cycle(self, graph, subgroup):
        raise BugDetected("grouped_topo_sort is wrong")

    # This topological_sort algorithm is deterministic and is biased to group subdirs (i.e. values of type Path) together, to group targets (i.e. values of type str) together, to put subdirs before targets, and to make the result somewhat alphasorted.
    def topological_sort(self, graph, subgroup):
        iddeps = build_reachable_dict(graph)
        not_placed_yet = set(graph.keys())
        ret = []
        while len(not_placed_yet) != 0:
            sumlen = 0
            for eltype in [Path, str]:
                next_batch = filter(lambda x: isinstance(x, eltype), not_placed_yet)
                next_batch = list(next_batch)
                next_batch = filter(lambda x: iddeps[x].issubset(ret), next_batch)
                next_batch = list(sorted(next_batch))
                ret += next_batch
                not_placed_yet -= set(next_batch)
                sumlen += len(next_batch)
            if sumlen == 0:
                self.error_out_due_to_cycle(graph, subgroup)

        return ret

    def writer_recursion(self, files_written, subgroup):
        depth = len(subgroup)
        mixed_deps = {}
        for key, el in self.elements.items():
            if not starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                mixed_deps[key] = self.generalised_deps(subgroup, el)
            else:
                pkey = Path(el.outpath[depth])
                if pkey not in mixed_deps:
                    mixed_deps[pkey] = set()
                mixed_deps[pkey].update(self.generalised_deps(subgroup, el))

        order = self.topological_sort(mixed_deps, subgroup)

        outpath = Path(self.root, *subgroup, "meson.build")
        total = ""
        state = "empty"
        for el in order:
            if isinstance(el, Path):
                if state == "target":
                    total += "\n"
                state = "subdir"
                total += "subdir('" + str(el) + "')\n"
            else:
                if state != "empty":
                    total += "\n"
                state = "target"
                total += self.elements[el].template.export_relative(
                    Path(self.root, *subgroup)
                )

        if outpath in self.custom_prefixes:
            total = self.custom_prefixes[outpath] + "\n\n" + total

        self.writef(files_written, outpath, total)

        entries = set()
        for key, el in self.elements.items():
            if starts_with(subgroup, el.outpath):
                if len(subgroup) != len(el.outpath):
                    entries.add(el.outpath[len(subgroup)])

        for direct in entries:
            self.writer_recursion(files_written, subgroup + [direct])

    def writeToFileSystem(self, files_written):
        self.writer_recursion(files_written, [])

    def writef(self, files_written, path, data):
        assert path not in files_written
        files_written.add(path)
        if DRYRUN:
            return
        assert os.path.normpath(path).startswith(str(self.root) + "/")
        path.write_text(
            "# This file was generated by https://codeberg.org/Volker_Weissmann/foam_meson\n\n"
            + data
        )


def largest_commons_prefix(paths):
    paths = [os.path.normpath(path) for path in paths]
    com = os.path.commonpath(paths)
    assert os.path.exists(com), com
    if os.path.isfile(com):
        com = os.path.dirname(com)
    return com

#------------------------------------------------------------------------------
