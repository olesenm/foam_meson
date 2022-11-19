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

// #![allow(dead_code)]
// #![allow(unused_macros)]
// #![allow(unused_variables)]
// #![allow(unused_imports)]

#![allow(clippy::ptr_arg)]

use petgraph::algo::has_path_connecting;
use petgraph::graph::Graph;
// todo https://docs.rs/petgraph/latest/petgraph/#graph-types
use itertools::Itertools;
use petgraph::prelude::*;
use petgraph::visit::Walker;
use serde::Serialize;
use std::collections::HashMap;
use std::hash::Hash; // Todo: Is BTreeMap faster?

mod fixer;
mod front_end_input;
mod hoists;
use hoists::*;

// todo: merge mygraph and bettergraph
pub type DepGraph<'a> = BetterGraph<&'a TargetName, Node<'a>, ()>;
pub type DirGraph<'a> = MyGraph<&'a DirName, ()>;

#[derive(Debug, Clone)]
pub struct Node<'a> {
    provides: &'a TargetName,
    ideal_path: &'a [DirName],
}

type EquivNode<'a> = Node<'a>; // todo

type NodeIndex = petgraph::stable_graph::NodeIndex<petgraph::stable_graph::DefaultIx>;

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
}

#[derive(Debug, Serialize, Default, Hash, Eq, PartialEq)]
pub struct TargetName(String);
impl std::fmt::Display for TargetName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

// todo: equality operator could compare pointers

#[derive(Debug, Serialize, Hash, Eq, PartialEq)]
pub struct DirName(String);
impl std::fmt::Display for DirName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

fn is_in_group(deps: &DepGraph, node: NodeIndex, path: &[&DirName]) -> bool {
    let otherpath = deps.graph.node_weight(node).unwrap().ideal_path;
    for i in 0..path.len() {
        if path[i] != &otherpath[i] {
            return false;
        }
    }
    true
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
        .flat_map(|ni| equiv[ni].ideal_path.iter())
        .collect::<Vec<_>>();
    for el in equiv.edge_references() {
        println!(
            "{: >2} {: <8} -> {: >2} {: <8}",
            el.source().index(),
            shorten(&dict, equiv[el.source()].ideal_path),
            el.target().index(),
            shorten(&dict, equiv[el.target()].ideal_path)
        );
    }
}

pub struct MyGraph<NW: Eq + Hash + Copy, EW> {
    graph: Graph<NW, EW>,
    node_map: HashMap<NW, NodeIndex>,
}

impl<NW: Eq + Hash + Copy, EW> MyGraph<NW, EW> {
    fn add_node(&mut self, node: NW) {
        assert!(!self.node_map.contains_key(&node));
        let ni = self.graph.add_node(node);
        self.node_map.insert(node, ni);
    }
    fn from_nodes(nodes: &[NW]) -> Self {
        let mut this = Self {
            graph: Graph::<NW, EW>::new(),
            node_map: HashMap::<NW, NodeIndex>::new(),
        };
        for node in nodes {
            this.add_node(*node);
        }
        this
    }
    fn add_edge(&mut self, source: NW, target: NW, weight: EW) {
        self.graph
            .add_edge(self.node_map[&source], self.node_map[&target], weight);
    }
}

pub struct BetterGraph<K: Eq + Hash, NW, EW> {
    graph: Graph<NW, EW>,
    node_map: HashMap<K, NodeIndex>,
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
    fn add_edge(&mut self, source: K, target: K, weight: EW) {
        self.graph
            .add_edge(self.node_map[&source], self.node_map[&target], weight);
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

fn main() {
    let mut owner = Vec::new();
    let file = std::fs::File::open("../../data.json").unwrap();
    let reader = std::io::BufReader::new(file);
    let (deps, tree) = front_end_input::parse(&mut owner, reader); // std::io::stdin()
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
        let (deps, tree) = front_end_input::parse(&mut owner, reader);
        let mut hoists_needed = Vec::new();
        fixer::find_all_hoists_needed(&mut hoists_needed, &deps, &tree, vec![]);
        let expected_result = r#"[
  {
    "target": "foo",
    "actual_path": [
      "top"
    ]
  }
]"#;
        let actual_result = serde_json::to_string_pretty(&hoists_needed).unwrap();
        assert!(actual_result == expected_result);
        // todo...
    }
}
