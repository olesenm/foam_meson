//! This crate optimizes the following graph-theory like problem:
//! This binary accepts json from stdin and outputs json to stdout. Example Usage:
//! ```shell
//! target/release/grouped_topo_sort << EOM
//! [
//!     {
//!         "provides": "foo",
//!         "ddeps": ["bar", "other"],
//!         "ideal_path": ["top", "midShared", "bottom"]
//!     },
//!     {
//!         "provides": "bar",
//!         "ddeps": [],
//!         "ideal_path": ["top", "midShared"]
//!     },
//!     {
//!         "provides": "other",
//!         "ddeps": ["bar"],
//!         "ideal_path": ["top", "midOther"]
//!     }
//! ]
//! EOM
//! ```
//! The array of these elements describes a directed graph and a tree:
//! The directed graph has an edge from "foo" to "bar", and an edge from "foo" to "other".
//! The tree has a leaf called "foo", whose parent is "bottomC", whose parent is "midK", whose parent is "topB".
//! Note that "topB", "midK" and "bottomC" are neither nodes nor edges in the directed graph. If there is a "provides": "topB" somewhere, this name-clash is purely incidental, means nothing and is ignored.
//! Note that this program is only an approximation: The output will always be correctly sorted, but there might exist another solution with fewer hoists. Everything that is an approximation instead of an exact solution is marked with #APPROX
//! In this source, the act of hoisting nodes so that the directory can be sorted is called "fixing" this directory.
//!
//! Todo: we only move nodes upwards, never sideways. Why? Probably because its to complicated

// #![allow(dead_code)]
// #![allow(unused_macros)]
// #![allow(unused_variables)]
// #![allow(unused_imports)]

#![allow(clippy::ptr_arg)]

use petgraph::algo::has_path_connecting;
use petgraph::algo::toposort;
use petgraph::graph::Graph;
// todo https://docs.rs/petgraph/latest/petgraph/#graph-types
use itertools::Itertools;
use petgraph::prelude::*;
use petgraph::visit::Walker;
use serde::Serialize;
use std::collections::HashMap;
use std::hash::Hash; // Todo: Is BTreeMap faster?

pub mod fixer;
pub mod front_end_input;
mod hoists;
use hoists::*;

// todo: merge mygraph and bettergraph
pub type DepGraph<'a> = BetterGraph<&'a TargetName, Node<'a>, ()>;
type DirGraph<'o, 'a> = MyGraph<'a, DirOrSingle<'o>, ()>;

#[derive(Debug, Clone)]
pub struct Node<'a> {
    provides: &'a TargetName,
    path: &'a [DirName],
}

type EquivNode<'a> = Node<'a>; // todo

type NodeIndex = petgraph::stable_graph::NodeIndex<petgraph::stable_graph::DefaultIx>;

#[derive(Debug, Serialize, PartialEq, Eq)]
/// Indicates that `target` will not be build in its ideal path, but in `actual_path`.
pub struct Hoist<'a> {
    target: &'a TargetName,
    actual_path: Vec<DirName>,
}

#[derive(Debug)]
pub struct Tree<'a> {
    subdirs: HashMap<&'a DirName, Tree<'a>>,
    targets: Vec<&'a TargetName>,
}
impl<'a> Tree<'a> {
    fn new() -> Self {
        Self {
            subdirs: HashMap::new(),
            targets: Vec::new(),
        }
    }
    fn get_subtree_from_prefix<'b>(&'b self, prefix: &[&'a DirName]) -> &'b Tree<'a> {
        prefix
            .iter()
            .fold(self, |acc, x| acc.subdirs.get(x).unwrap())
    }

    // Should probably be removed in favor of `get_subtree_from_prefix`, but I'm too lazy
    #[allow(dead_code)]
    fn get_subtree_from_prefix_2<'b>(&'b self, prefix: &[DirName]) -> &'b Tree<'a> {
        prefix
            .iter()
            .fold(self, |acc, x| acc.subdirs.get(x).unwrap())
    }
    // prefix should probably be `&[&DirName]` instead of `&[DirName]`, but I'm to lazy to change that.
    fn get_mut_subtree_from_prefix<'b>(&'b mut self, prefix: &[DirName]) -> &'b mut Tree<'a> {
        prefix
            .iter()
            .fold(self, |acc, x| acc.subdirs.get_mut(x).unwrap())
    }
    fn walk_subtrees_recursively<F>(&self, mut func: F)
    where
        F: FnMut(&Vec<&DirName>, &Tree) -> (),
    {
        let mut stack = Vec::new();
        stack.push(Vec::new());
        while let Some(prefix) = stack.pop() {
            let subtree = self.get_subtree_from_prefix(&prefix);
            func(&prefix, subtree);
            stack.extend(subtree.subdirs.keys().map(|k| {
                let mut combined = prefix.clone();
                combined.push(k);
                combined
            }));
        }
    }
}

fn path_begins_with(path: &[DirName], prefix: &[DirName]) -> bool {
    if path.len() < prefix.len() {
        return false;
    }
    for i in 0..prefix.len() {
        if path[i] != prefix[i] {
            return false;
        }
    }
    true
}

fn path_begins_with_2(path: &[DirName], prefix: &[&DirName]) -> bool {
    if path.len() < prefix.len() {
        return false;
    }
    for i in 0..prefix.len() {
        if path[i] != *prefix[i] {
            return false;
        }
    }
    true
}

#[derive(Debug, Serialize, Default, Hash, Eq, PartialEq)]
pub struct TargetName(String);
impl std::fmt::Display for TargetName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

// todo: equality operator could compare pointers

#[derive(Debug, Serialize, Hash, Eq, PartialEq, Clone)]
pub struct DirName(String);
impl std::fmt::Display for DirName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

fn is_in_group(deps: &DepGraph, node: NodeIndex, path: &[&DirName]) -> bool {
    let otherpath = deps.graph.node_weight(node).unwrap().path;
    path_begins_with_2(otherpath, path)
}

// itaid = is there any indirect dependency

fn itaid_from_node_to_folder(deps: &DepGraph, start: NodeIndex, path: &[&DirName]) -> bool {
    let dfs = Dfs::new(&deps.graph, start);
    dfs.iter(&deps.graph).any(|x| is_in_group(deps, x, path))
}

fn itaid_from_folder_to_folder(deps: &DepGraph, start: &Tree, dest: &[&DirName]) -> bool {
    for el in &start.targets {
        if itaid_from_node_to_folder(deps, deps.get_node_index(*el), dest) {
            return true;
        }
    }
    for value in start.subdirs.values() {
        if itaid_from_folder_to_folder(deps, value, dest) {
            return true;
        }
    }
    false
}

/// The returned graph contains an edge from DirOrSingle::Dir(a) to DirOrSingle::Dir(b), exactly if deps contains an
/// edge from
/// prefix[0]/prefix[1]/.../prefix[prefix.len()-1]/a/foo/bar/node1
/// to
/// prefix[0]/prefix[1]/.../prefix[prefix.len()-1]/b/something/node2
fn gen_dir_graph<'a, 'o: 'a>(
    owner: &'a mut Vec<DirOrSingle<'o>>,
    deps: &'a DepGraph<'o>,
    tree: &Tree<'o>,
    prefix: &'a Vec<&'o DirName>,
) -> DirGraph<'o, 'a> {
    let subtree = tree.get_subtree_from_prefix(prefix);

    let dirs = subtree.subdirs.keys().map(|x| DirOrSingle::Dir(x));
    let singles = subtree.targets.iter().map(|x| DirOrSingle::Single(x));

    owner.extend(dirs.chain(singles));

    let mut local = DirGraph::new();
    for node in owner.iter() {
        local.add_node(node);
    }

    for edge in deps.graph.edge_references() {
        let points = [edge.source(), edge.target()]
            .iter()
            .map(|&ni| {
                let node = &deps.graph[ni];
                let path = node.path;
                if !path_begins_with_2(path, prefix) {
                    None
                } else if path.len() == prefix.len() {
                    Some(DirOrSingle::Single(node.provides))
                } else {
                    Some(DirOrSingle::Dir(&path[prefix.len()]))
                }
            })
            .collect::<Vec<_>>();
        if let Some(source) = &points[0] {
            if let Some(target) = &points[1] {
                if source != target {
                    dbg!(&source, &target, edge.source(), edge.target());
                    local.add_edge(&source, &target, ());
                }
            }
        }
    }
    local
}

fn shorten(dict: &Vec<&DirName>, long: &[DirName]) -> String {
    // long.iter()
    //     .map(|x| {
    //         char::from_u32('a' as u32 + dict.iter().position(|y| y == &x.as_str()).unwrap() as u32)
    //             .unwrap()
    //     })
    //     .join(" ")
    long.iter()
        .map(|x| format!("{: <2}", dict.iter().position(|y| y == &x).unwrap(),))
        .join(" ")
}

#[allow(dead_code)]
fn graph_print(equiv: &Graph<EquivNode, ()>) {
    let dict = equiv
        .node_indices()
        .flat_map(|ni| equiv[ni].path.iter())
        .collect::<Vec<_>>();
    for el in equiv.edge_references() {
        println!(
            "{: >2} {: <8} -> {: >2} {: <8}",
            el.source().index(),
            shorten(&dict, equiv[el.source()].path),
            el.target().index(),
            shorten(&dict, equiv[el.target()].path)
        );
    }
}

pub struct MyGraph<'a, NW: Eq + Hash, EW> {
    graph: Graph<&'a NW, EW>,
    node_map: HashMap<&'a NW, NodeIndex>,
}

impl<'a, NW: Eq + Hash, EW> MyGraph<'a, NW, EW> {
    fn add_node(&mut self, node: &'a NW) {
        assert!(!self.node_map.contains_key(&node));
        let ni = self.graph.add_node(node);
        self.node_map.insert(node, ni);
    }
    fn new() -> Self {
        Self {
            graph: Graph::<&NW, EW>::new(),
            node_map: HashMap::<&NW, NodeIndex>::new(),
        }
    }
    fn from_nodes(nodes: &[&'a NW]) -> Self {
        let mut this = Self::new();
        for node in nodes {
            this.add_node(*node);
        }
        this
    }
    fn add_edge(&mut self, source: &NW, target: &NW, weight: EW) {
        self.graph
            .add_edge(self.node_map[&source], self.node_map[&target], weight);
    }
}

pub struct BetterGraph<K: Eq + Hash, NW, EW> {
    pub graph: Graph<NW, EW>,
    pub node_map: HashMap<K, NodeIndex>,
}

impl<K: Eq + Hash, NW, EW> BetterGraph<K, NW, EW> {
    fn get_node_index(&self, key: K) -> NodeIndex {
        self.node_map[&key]
    }
    fn add_node(&mut self, node: NW, key: K) {
        assert!(!self.node_map.contains_key(&key));
        let ni = self.graph.add_node(node);
        self.node_map.insert(key, ni);
    }
    fn new() -> Self {
        Self {
            graph: Graph::<NW, EW>::new(),
            node_map: HashMap::<K, NodeIndex>::new(),
        }
    }
    fn update_edge(&mut self, source: K, target: K, weight: EW) {
        self.graph
            .update_edge(self.node_map[&source], self.node_map[&target], weight);
    }
}

fn print_time_complexity_note(n: usize) {
    eprintln!(
        "We now run an algorithm with a time-complexity of O(n! n^2), with n = {}.",
        n
    );
    let steps = (1..n)
        .fold(1_usize, |acc, x| acc.checked_mul(x).unwrap())
        .checked_mul(n.checked_pow(2).unwrap())
        .unwrap();
    eprintln!(" -> {} steps.", steps);
}

/// `deps` and `tree` contains some redundant information. This function asserts that this redundant information matches.
fn verify_tree_graph(deps: &DepGraph, tree: &Tree) {
    if !cfg!(debug_assertions) {
        return;
    }
    let mut count = 0;
    tree.walk_subtrees_recursively(|prefix, subtree| {
        for target in &subtree.targets {
            let path = deps.graph[deps.get_node_index(target)].path;
            // If rust wouldn't be so shitty, the next two lines would be `debug_assert_eq!(path, prefix)`
            debug_assert_eq!(path.len(), prefix.len());
            debug_assert!(path.iter().zip(prefix.iter()).all(|(a, &b)| a == b));
            count += 1;
        }
    });
    debug_assert_eq!(count, deps.graph.node_count());
}

pub fn execute_hoists<'o>(deps: &mut DepGraph<'o>, tree: &mut Tree<'o>, hoists: &'o Vec<Hoist>) {
    verify_tree_graph(&deps, &tree);
    for hoist in hoists {
        let ni = deps.get_node_index(hoist.target);

        let old_path = deps.graph[ni].path;
        let subtree = tree.get_mut_subtree_from_prefix(old_path);
        assert!(subtree.targets.contains(&hoist.target));
        subtree.targets.retain(|&x| x != hoist.target);

        let subtree = tree.get_mut_subtree_from_prefix(&hoist.actual_path);
        subtree.targets.push(hoist.target);

        deps.graph[ni].path = hoist.actual_path.as_slice();
    }
    verify_tree_graph(&deps, &tree);
}

#[derive(Debug, Hash, PartialEq, Eq)]
enum DirOrSingle<'a> {
    Dir(&'a DirName),
    Single(&'a TargetName),
}

pub fn assert_toposort_possible(deps: &DepGraph, tree: &Tree) {
    tree.walk_subtrees_recursively(|prefix, _subtree| {
        let mut owner = Vec::new();
        let local = gen_dir_graph(&mut owner, deps, tree, prefix);

        dbg!(prefix);
        dbg!(&local.graph);
        dbg!(toposort(&local.graph, None));
        assert!(toposort(&local.graph, None).is_ok());
    });
}

pub fn my_main() {
    let mut owner = Vec::new();
    let file = std::fs::File::open("../../data.json").unwrap();
    let reader = std::io::BufReader::new(file);
    let (deps, tree) = front_end_input::parse(&mut owner, reader); // std::io::stdin()
    verify_tree_graph(&deps, &tree);
    let mut hoists_needed = Vec::new();
    fixer::find_all_hoists_needed(&mut hoists_needed, &deps, &tree, vec![]);
    println!("{}", serde_json::to_string_pretty(&hoists_needed).unwrap());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_end_to_end() {
        let reader = std::io::BufReader::new(
            r#"
            [
                {
                    "provides": "foo",
                    "ddeps": ["bar", "other"],
                    "ideal_path": ["top", "midShared", "bottom"]
                },
                {
                    "provides": "bar",
                    "ddeps": [],
                    "ideal_path": ["top", "midShared"]
                },
                {
                    "provides": "other",
                    "ddeps": ["bar"],
                    "ideal_path": ["top", "midOther"]
                }
            ]
        "#
            .as_bytes(),
        );
        let mut owner = Vec::new();
        let (mut deps, mut tree) = front_end_input::parse(&mut owner, reader);
        let mut hoists = Vec::new();
        fixer::find_all_hoists_needed(&mut hoists, &deps, &tree, vec![]);
        let expected_result = r#"[
  {
    "target": "foo",
    "actual_path": [
      "top"
    ]
  }
]"#;
        let actual_result = serde_json::to_string_pretty(&hoists).unwrap();
        assert!(actual_result == expected_result);
        execute_hoists(&mut deps, &mut tree, &hoists);
        assert_toposort_possible(&deps, &tree);
    }
}
