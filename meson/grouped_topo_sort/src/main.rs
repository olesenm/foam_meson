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

#![allow(dead_code)]
#![allow(unused_macros)]
#![allow(unused_variables)]
#![allow(unused_imports)]
use petgraph::algo::dijkstra;
use petgraph::algo::has_path_connecting;
use petgraph::algo::is_cyclic_directed;
use petgraph::algo::toposort;
use petgraph::dot::{Config, Dot};
use petgraph::graph::node_index;
use petgraph::graph::Graph;
// todo https://docs.rs/petgraph/latest/petgraph/#graph-types
use graphalgs::generate::EdgeNumberError;
use itertools::Itertools;
use permute::permutations_of;
use petgraph::prelude::*;
use petgraph::visit::IntoNodeIdentifiers;
use petgraph::visit::Visitable;
use petgraph::visit::Walker;
use petgraph::visit::{depth_first_search, DfsEvent};
use rand::prelude::*;
use rand::rngs::SmallRng;
use rand::{thread_rng, SeedableRng};
use serde::Deserialize;
use std::collections::hash_map::RandomState;
use std::collections::{HashMap, HashSet};
use std::hash::Hash; // Todo: Is BTreeMap faster?

mod fixer;
mod front_end_input;
mod hoists;
use fixer::*;
use hoists::*;

macro_rules! cast {
    ($target: expr, $pat: path) => {{
        if let $pat(a) = $target {
            // #1
            a
        } else {
            panic!("mismatch variant when cast to {}", stringify!($pat)); // #2
        }
    }};
}

type Context = i32;

pub type DepGraph<'a> = BetterGraph<&'a TargetName, Node<'a>, ()>;
pub type DirGraph<'a> = MyGraph<&'a DirName, ()>;

#[derive(Debug)]
struct FiniteValuesMap<'a> {
    possible_vals: Vec<(&'a str, Context)>,
}

impl<'a> FiniteValuesMap<'a> {
    fn new() -> Self {
        Self {
            possible_vals: Vec::new(),
        }
    }
    fn add(&mut self, possibile_val: &'a str, context: Context) {
        if !self.possible_vals.contains(&(possibile_val, context)) {
            self.possible_vals.push((possibile_val, context));
        }
    }
    fn to_id(&self, possibile_val: &'a str, context: Context) -> FinVal {
        FinVal(
            self.possible_vals
                .iter()
                .position(|&el| el.0 == possibile_val && el.1 == context)
                .unwrap()
                .try_into()
                .unwrap(),
        )
    }
    fn from_id(&self, fv: &FinVal) -> (&'a str, Context) {
        self.possible_vals[fv.0 as usize]
    }
}

// If you want to debug-print this type, do this:
// dbg!(fvm.from_id(finval));
#[derive(Debug)]
struct FinVal(i32);

#[derive(Debug, Clone)]
pub struct Node<'a> {
    provides: &'a TargetName,
    path: &'a [DirName],
}

type EquivNode<'a> = Node<'a>; // todo

// #[derive(Debug, Clone)]
// struct EquivNode<'a> {
//     provides: &'a TargetName,
//     path: &'a [DirName],
//     orig_path: &'a [DirName],
// }

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

#[derive(Debug, Default, Hash, Eq, PartialEq)]
pub struct TargetName(String);
impl std::fmt::Display for TargetName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

// todo: equality operator could compare pointers

#[derive(Debug, Hash, Eq, PartialEq)]
pub struct DirName(String);
impl std::fmt::Display for DirName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

fn is_in_group(deps: &DepGraph, node: NodeIndex, path: &[&DirName]) -> bool {
    let otherpath = deps.graph.node_weight(node).unwrap().path;
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
    for (_key, value) in &start.subdirs {
        if itaid_from_folder_to_folder(deps, value, dest) {
            return true;
        }
    }
    false
}

/// Returns all nodes of the graph, grouped together in different groups.
/// This function tries to spread the nodes out in to different groups as much as
/// possible (and actually finds the optimal solution), while still respecting
/// the following rule:
/// There are no two groups a and b, such that a has an element which has an
/// (indirect) dependency on an element in b AND b has an element which has an
/// (indirect) dependency on an element in a.
///
/// The order of the groups is arbitrary. (TODO: Topological sort)
///
/// Todo: could be replaced by https://docs.rs/graphalgs/latest/graphalgs/connect/scc/fn.condensation.html
fn group_cycles<T>(dir_graph: &Graph<T, ()>) -> Vec<Vec<NodeIndex>> {
    let n = dir_graph.node_count();
    let indices_we_use = (0..n).map(|x| NodeIndex::new(x)).collect::<Vec<_>>();
    let indices_we_should_use = dir_graph.node_indices().collect::<Vec<_>>();
    assert!(indices_we_use == indices_we_should_use);
    let mut matrix = vec![vec![None; n]; n];
    for x in 0..n {
        for y in 0..n {
            matrix[x][y] = Some(has_path_connecting(
                dir_graph,
                NodeIndex::new(x),
                NodeIndex::new(y),
                None,
            ));
        }
    }
    let matrix = matrix
        .iter()
        .map(|v| v.iter().map(|x| x.unwrap()).collect::<Vec<_>>())
        .collect::<Vec<_>>();
    let mut map = HashMap::<&Vec<bool>, Vec<NodeIndex>>::new();
    for x in 0..n {
        map.entry(&matrix[x])
            .or_insert(Vec::new())
            .push(NodeIndex::new(x));
    }
    map.into_iter().map(|(key, value)| value).collect()
}

fn find_group_of_element<T: std::cmp::PartialEq>(groups: &Vec<Vec<T>>, element: &T) -> usize {
    groups.iter().position(|x| x.contains(element)).unwrap()
}

/// Similar to a normal topological sort, with one difference: A normal topological sort errors out or loops forever if the graph contains cycles. This function will instead group all elements of the same cycle (and other interlocking cycles) together and put them into a single node. The modified graph contains no cycles an can thus be topologically sorted. Example:
/// Input:
/// a -> b
/// b -> c
/// c -> d
/// d -> e
/// d -> b
/// Output:
/// (a), (b, c, d), (e)
fn topo_sort_group_cycles<T>(dir_graph: &Graph<T, ()>) -> Vec<Vec<NodeIndex>> {
    let groups = group_cycles(dir_graph);
    let mut grouped_graph = Graph::<&[NodeIndex], ()>::new();
    for group in &groups {
        grouped_graph.add_node(group);
    }
    for el in dir_graph.edge_references() {
        let source = NodeIndex::new(find_group_of_element(&groups, &el.source()));
        let target = NodeIndex::new(find_group_of_element(&groups, &el.target()));
        if source != target {
            grouped_graph.update_edge(source, target, ());
        }
    }
    toposort(&grouped_graph, None)
        .unwrap()
        .iter()
        .map(|&x| grouped_graph.node_weight(x).unwrap().to_vec())
        .collect::<Vec<_>>()
}

// fn direct_equivalency(part: Graph<Node, ()>) -> Graph<EquivNode, ()> {
//     part.map(
//         |ni, n| EquivNode {
//             provides: n.provides,
//             path: n.path,
//             orig_path: n.path,
//         },
//         |_ei, &_e| _e,
//     )
// }

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

fn graph_print(equiv: &Graph<EquivNode, ()>) {
    let dict = equiv
        .node_indices()
        .map(|ni| equiv[ni].path.iter())
        .flatten()
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

// fn find_all_cycles<NW>(dirgraph: &Graph<NW, ()>) {
//     // todo: I think dirgraph being a MatrixGraph would be faster
//
//     // ways[a][b] are all possible ways to reach b from a, without visiting a node twice (todo: except if a == b)
//     let mut ways =
//         vec![vec![vec![Vec::<NodeIndex>::new()]; dirgraph.node_count()]; dirgraph.node_count()];
//     for ni in dirgraph.node_indices() {
//         for ea in dirgraph.edges_directed(ni, Outgoing) {
//             let tar = ea.target();
//             ways[ni.index()][tar.index()].push(vec![ni, tar])
//         }
//     }
//     for ni in dirgraph.node_indices() {
//         for ea in dirgraph.edges_directed(ni, Outgoing) {
//             let mid = ea.target();
//             for eb in dirgraph.edges_directed(mid, Outgoing) {
//                 let tar = eb.target();
//                 ways[ni.index().]
//             }
//         }
//     }
//     //dirgraph.has_edge();
// }

fn find_all_cycles<NW>(dirgraph: &Graph<NW, ()>) {}

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
    fn new() -> Self {
        Self {
            graph: Graph::<NW, EW>::new(),
            node_map: HashMap::<NW, NodeIndex>::new(),
        }
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
    println!(
        "We now run an algorithm with a time-complexity of O(n! n^2), with n = {}.",
        n
    );
    let steps = (1..n)
        .fold(1_usize, |acc, x| acc.checked_mul(x).unwrap())
        .checked_mul(n.checked_pow(2).unwrap())
        .unwrap();
    println!(" -> {} steps.", steps);
}

fn main() {
    let mut owner = Vec::new();
    let file = std::fs::File::open("../../data.json").unwrap();
    let reader = std::io::BufReader::new(file);
    let (deps, tree) = front_end_input::parse(&mut owner, reader); // std::io::stdin()
    fixer::find_and_fix_problematic_subgraph(&deps, &tree, vec![]);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_cycles() {
        let mut dir_graph = Graph::<&str, ()>::new();
        let mut node_index_map: HashMap<&str, NodeIndex> = HashMap::new();
        for key in ["a", "b", "c", "d", "e", "f"] {
            node_index_map.insert(key, dir_graph.add_node(key));
        }
        for (key1, key2) in [
            ("a", "b"),
            ("b", "c"),
            ("c", "d"),
            ("d", "b"),
            ("d", "e"),
            ("d", "f"),
            ("f", "b"),
        ] {
            dir_graph.update_edge(node_index_map[key1], node_index_map[key2], ());
        }
        let groups = group_cycles(&dir_graph);
        assert!(groups.len() == 3);
        assert!(groups.contains(&vec![node_index_map["a"]]));
        assert!(groups.contains(&vec![
            node_index_map["b"],
            node_index_map["c"],
            node_index_map["d"],
            node_index_map["f"]
        ]));
        assert!(groups.contains(&vec![node_index_map["e"]]));
    }

    #[test]
    fn test_everything() {
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
        let file = std::fs::File::open("../../data.json").unwrap();
        let reader = std::io::BufReader::new(file);
        let mut owner = Vec::new();
        let (deps, tree) = front_end_input::parse(&mut owner, reader);
        fixer::find_and_fix_problematic_subgraph(&deps, &tree, vec![]);
    }
}
