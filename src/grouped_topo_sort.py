#!/bin/false
from collections import defaultdict
import typing as T
from . import meson_codegen


# "grouped_topo_sort" sets el.outpath for all elements. Nearly always,
# el.outpath == el.ideal_path, but in some cases this is not true. In all cases
# meson_codegen.starts_with(el.outpath, el.ideal_path) will hold true.
# This outpath modification is tricky graph theory with heuristics, so do not
# attempt to understand it on your own. Seriously, Don't try.
def grouped_topo_sort(elements):
    for el in elements.values():
        el.outpath = el.ideal_path
    tree = build_tree(elements)
    tree.fix_outpaths()


def invert_graph(graph):
    ret = {}
    for k, ar in graph.items():
        if k not in ret:
            ret[k] = []
        for v in ar:
            if v in ret:
                ret[v].append(k)
            else:
                ret[v] = [k]
    return ret


# scc = Strongly connected component
def calc_nontrivial_sccs(graph):
    rd = meson_codegen.build_reachable_dict(graph)
    rev_rd = invert_graph(rd)

    sccs = []
    indices = {}
    curind = -1
    for k in graph:
        if k not in indices:
            curind += 1
            indices[k] = curind
            scc = set(rd[k]).intersection(rev_rd[k])
            if len(scc) > 1:  # hence "nontrivial" in the name of this function
                sccs.append(scc)
            for k2 in scc:
                indices[k2] = curind
    return sccs


class SiblingJump:
    def __init__(self, src, dest):
        self.src = src
        self.dest = dest

    def __repr__(self):
        return f"{self.src} is a sibling of {self.dest}"


class GraphJump:
    def __init__(self, src, dest):
        self.src = src
        self.dest = dest

    def __repr__(self):
        return f"There is a path from {self.src} to {self.dest}"


def find_group_cycles(subgraph, name_to_group, group_to_names):
    rd = meson_codegen.build_reachable_dict(subgraph)
    paths_matrix = {k2: {k1: [] for k1 in rd} for k2 in rd}

    steps = defaultdict(set)
    for k1, ar1 in rd.items():
        if len(group_to_names[name_to_group[k1]]) == 1:
            continue
        for v1 in ar1:
            if name_to_group[v1] == name_to_group[k1]:
                continue
            for v2 in rd[v1]:
                steps[k1].add(v2)

    while True:
        for names in group_to_names.values():
            for name1 in names:
                for name2 in names:
                    if name1 == name2:
                        continue
                    paths_matrix[name1][name2].append([SiblingJump(name1, name2)])
                    for a in paths_matrix:
                        for path in paths_matrix[a][name1]:
                            if not isinstance(path[-1], SiblingJump):
                                paths_matrix[a][name2].append(
                                    path.copy() + [SiblingJump(name1, name2)]
                                )
        for a in paths_matrix:
            for b in paths_matrix[a]:
                for c in steps[b]:
                    for path in paths_matrix[a][b]:
                        if isinstance(path[-1], SiblingJump):
                            paths_matrix[a][c].append(path.copy() + [GraphJump(b, c)])

        cycles = []
        for a in paths_matrix:
            for b in paths_matrix[a]:
                for path in paths_matrix[a][b]:
                    if len(path) > 1 and path[0].src == path[-1].dest:
                        cycles.append([x.src for x in path])
        if len(cycles) > 0:
            return cycles


class Tree:
    subtrees: T.Dict["str", "Tree"]

    def __init__(self, path, elements):
        self.subtrees = {}
        self.path = path
        self.elements = elements

    def is_in_tree(self, el):
        return meson_codegen.starts_with(self.path, el.outpath)

    def generate_dirgraph(self):
        dirgraph = {}
        for el in self.elements.values():
            if meson_codegen.starts_with(self.path, el.outpath):
                if len(el.outpath) == len(self.path):
                    src = SingleTarget(el.provides)
                else:
                    src = Directory(el.outpath[len(self.path)])
                if src not in dirgraph:
                    dirgraph[src] = set()
                for dep in el.ddeps:
                    if meson_codegen.starts_with(self.path, self.elements[dep].outpath):
                        if len(self.elements[dep].outpath) == len(self.path):
                            dest = SingleTarget(self.elements[dep].provides)
                        else:
                            dest = Directory(self.elements[dep].outpath[len(self.path)])
                        dirgraph[src].add(dest)
        return dirgraph

    def fix_outpaths(self):
        for st in self.subtrees.values():
            st.fix_outpaths()
        while True:
            dirgraph = self.generate_dirgraph()
            sccs = calc_nontrivial_sccs(dirgraph)
            if len(sccs) == 0:
                break
            for scc in sccs:
                interesting = [
                    el
                    for el in self.elements.values()
                    if any(self.subtrees[d.name].is_in_tree(el) for d in scc)
                ]
                subgraph = {}
                name_to_group = {}
                group_to_names = defaultdict(list)
                for el in interesting:
                    subgraph[el.provides] = {
                        x for x in el.ddeps if self.elements[x] in interesting
                    }
                    if len(el.outpath) == len(self.path):
                        group = SingleTarget(el.provides)
                    else:
                        group = Directory(el.outpath[len(self.path)])

                    name_to_group[el.provides] = group
                    group_to_names[group].append(el.provides)
                hoists_needed = find_group_cycles(
                    subgraph, name_to_group, group_to_names
                )
                hoists_chosen = minimum_hoists_needed_approx(hoists_needed)
                for name in hoists_chosen:
                    self.elements[name].outpath = tuple(self.path)


# Example:
# hoists_needed = [
#     ["a", "b", "c"],
#     ["c", "d", "e"],
#     ["d", "c", "b"],
#     ["a", "k", "z"],
#     ["e", "k", "j"],
# ]
# assert minimum_hoists_needed_approx(hoists_needed) == ["c", "k"]
# Why? Because every list in hoists_needed contains either "c" or "k" and len(["c", "k"]) is as small as possible.
# It is not guaranteed that the returned list actually as small as possible, as this is only a heuristic
def minimum_hoists_needed_approx(hoists_needed: T.List[T.List[str]]):
    names = {item for sublist in hoists_needed for item in sublist}
    chosen = []
    while True:
        num_occurences = {
            name: sum(x.count(name) for x in hoists_needed) for name in names
        }
        most_common_node = max(num_occurences, key=num_occurences.get)
        hoists_needed = [x for x in hoists_needed if most_common_node not in x]
        chosen.append(most_common_node)
        if len(hoists_needed) == 0:
            return chosen


class SingleTarget:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.name == other.name
        else:
            return False

    def __hash__(self):
        return hash((self.__class__.__name__, self.name))


class Directory:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.name == other.name
        else:
            return False

    def __hash__(self):
        return hash((self.__class__.__name__, self.name))


def build_tree(elements):
    tree = Tree([], elements)
    for key, value in elements.items():
        assert key == value.provides
        head = tree
        path = []
        for x in value.outpath:
            path.append(x)
            if x in head.subtrees:
                head = head.subtrees[x]
            else:
                head.subtrees[x] = Tree(path.copy(), elements)
                head = head.subtrees[x]
    return tree
