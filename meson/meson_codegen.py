#!/bin/false
# generate_meson_build.py gives the recipes we want to build to this file. This file then sorts them, makes the paths relative and as short as possible (e.g. abc/../abc is just abc), splits the recipes among different meson.build files and finally writes it out to disk.
# Grep for EXPLAIN_CODEGEN will help you understand it

DRYRUN = False

import os
import re
import copy
import subprocess
import json
from collections import defaultdict
from pathlib import Path
import typing as T
import math

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
        for k2, v2 in ret.items():
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

    cycle = [min([(dist[k][k], k) for k in graph])[1]]
    while cycle[0] != cycle[-1] or len(cycle) == 1:
        cycle.append(min([(dist[k][cycle[0]], k) for k in graph[cycle[-1]]])[1])
    return cycle


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
            with open(path, "a") as ofile:
                ofile.write(prefix)

        for key, el in self.elements.items():
            recipe = el.template.temp.replace("<PATH>", "").replace("</PATH>", "")
            outpath = Path(self.root, *el.outpath, "meson.build")
            with open(outpath, "a") as ofile:
                ofile.write(recipe)

    # todo: documentation
    def set_outpaths(self):
        ar = []
        for key, value in self.elements.items():
            assert key == value.provides
            ar.append(
                {
                    "provides": value.provides,
                    "ddeps": value.ddeps,
                    "ideal_path": value.ideal_path,
                }
            )
        res = subprocess.check_output(
            "cd meson/grouped_topo_sort/ && cargo run --release",
            shell=True,
            universal_newlines=True,
            input=json.dumps(ar),
        )
        changes = json.loads(res)
        for target in self.elements:
            self.elements[target].outpath = self.elements[target].ideal_path
        for change in changes:
            target = self.elements[change["target"]]
            target.outpath = change["chosen_path"]

            ideal = "/".join(target.ideal_path) + "/meson.build"
            op = "/".join(target.outpath) + "/meson.build"
            print(
                f"We would like to put the target '{target.provides}' into '{ideal}', but due to some graph theory stuff that is impossible/hard so we put it into '{op}' instead."
            )
        print(f"{len(changes)} target(s) will not be in their preferred directory.")

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
        ar = list(self.elements.keys()) + list(set(broken_provides))
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
    def get_dep_reason_dir_file(self, subgroup, dir_source, file_target):
        depth = len(subgroup)
        for key, el in self.elements.items():
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
    def get_dep_reason_file_dir(self, subgroup, file_source, dir_target):
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
    def get_dep_reason_dir_dir(self, subgroup, dir_source, dir_target):
        depth = len(subgroup)
        for key, el in self.elements.items():
            if not self.starts_with(subgroup, el.outpath):
                continue
            if len(el.outpath) == depth:
                continue
            if Path(el.outpath[depth]) != dir_source:
                continue

            ret = self.get_dep_reason_file_dir(subgroup, key, dir_target)
            if ret is not None:
                return (key, ret)
        raise ValueError

    # Returns all path from src to target.
    def find_all_paths(self, src, target):
        queue = []
        queue.append((src, []))
        paths = []
        while len(queue) != 0:
            cur, path = queue.pop()
            if cur == target:
                paths.append(path)
            next = [
                (edge[1], path + [edge[1]]) for edge in self.edges if edge[0] == cur
            ]
            queue += next
        return paths

    def error_out_due_to_cycle(self, graph, subgroup):
        print(
            "You encountered a bug in this script. Sorry. Please report it here: https://codeberg.org/Volker_Weissmann/foam_meson/issues"
        )
        exit(1)
        cycle = find_shortest_cycle(graph)
        print("-" * 80)
        print(
            "We are unable to generate meson.build files due to some complicated graph theory stuff:"
        )
        topdir = os.path.join(self.root, *subgroup)
        print(
            f"In '{topdir}/meson.build' we want to put (among other things) the following {len(cycle)-1} lines:",
        )
        for i in range(len(cycle) - 1):
            print(f"    subdir('{cycle[i]}')")
        print(
            f"Due to some limitations of meson (https://github.com/mesonbuild/meson/issues/8178) we have to put these {len(cycle)-1} subdir calls in the correct order: The topological order of the dependency graph. But the dependency graph of these directories form a cycle, so no topological order exists."
        )
        for i in range(len(cycle) - 1):
            targetpair = self.get_dep_reason_dir_dir(subgroup, cycle[i], cycle[i + 1])
            dirpair = [
                os.path.join(
                    self.root, *(self.elements[target].ideal_path), "Make", "files"
                )
                for target in targetpair
            ]
            print("\n")
            for i in range(2):
                print(f"{dirpair[i]} contains the target '{targetpair[i]}'.")
            print(
                f"'{targetpair[0]}' depends on '{targetpair[1]}', so 'subdir('{cycle[0]}')' must be after 'subdir('{cycle[1]}')'."
            )
        print("\n")
        print(
            f"There is no way to fulfill all of these {len(cycle)-1} requirements simultaniously. Any of the possible {math.factorial(len(cycle)-1)} orders for the {len(cycle)-1} subdir calls is going to conflict with at least one of these requirements."
        )
        exit(1)

    # This topological_sort algorithm is deterministic and is biased to group subdirs together, to group targets together, to put subdirs before targets, and to make the result somewhat alphasorted.
    def topological_sort(self, graph, subgroup):
        iddeps = build_reachable_dict(graph)

        def iddep(a, b):
            return b in iddeps[a]

        not_placed_yet = set(graph.keys())
        ret = []
        while len(not_placed_yet) != 0:
            sumlen = 0
            for type in [Path, str]:
                next_batch = filter(lambda x: isinstance(x, type), not_placed_yet)
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
            if not self.starts_with(subgroup, el.outpath):
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
            if self.starts_with(subgroup, el.outpath):
                if len(subgroup) != len(el.outpath):
                    entries.add(el.outpath[len(subgroup)])

        for dir in entries:
            self.writer_recursion(files_written, subgroup + [dir])

    def writeToFileSystem(self, files_written):
        self.writer_recursion(files_written, [])

    def writef(self, files_written, path, data):
        assert path not in files_written
        files_written.add(path)
        if DRYRUN:
            return
        assert os.path.normpath(path).startswith(str(self.root) + "/")
        path.write_text(data)


def largest_commons_prefix(paths):
    paths = [os.path.normpath(path) for path in paths]
    com = os.path.commonpath(paths)
    assert os.path.exists(com), com
    if os.path.isfile(com):
        com = os.path.dirname(com)
    return com
