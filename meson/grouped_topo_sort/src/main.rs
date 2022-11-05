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

mod hoists;
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

type ImportedData = HashMap<String, Target>;

#[derive(Debug, Deserialize)]
struct Target {
    provides: String,
    ddeps: Vec<String>,
    outpath: Vec<String>,
}

type Context = i32;

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

#[derive(Debug, Default, Clone)]
struct Node<'a> {
    provides: &'a str,
    path: &'a [String],
}

#[derive(Debug, Default, Clone)]
struct EquivNode<'a> {
    provides: &'a str,
    path: &'a [String],
    orig_path: &'a [String],
}

type NodeIndex = petgraph::stable_graph::NodeIndex<petgraph::stable_graph::DefaultIx>;

#[derive(Debug)]
struct Tree<'a> {
    subdirs: HashMap<&'a str, Tree<'a>>,
    targets: Vec<NodeIndex>,
}
impl<'a> Tree<'a> {
    fn new() -> Self {
        Self {
            subdirs: HashMap::new(),
            targets: Vec::new(),
        }
    }
}

fn is_in_group(deps: &Graph<Node, ()>, node: NodeIndex, path: &[String]) -> bool {
    let otherpath = deps.node_weight(node).unwrap().path;
    for i in 0..path.len() {
        if path[i] != otherpath[i] {
            return false;
        }
    }
    true
}

// itaid = is there any indirect dependency

fn itaid_from_node_to_folder(deps: &Graph<Node, ()>, start: NodeIndex, path: &[String]) -> bool {
    let dfs = Dfs::new(deps, start);
    dfs.iter(deps).any(|x| is_in_group(deps, x, path))
}

fn itaid_from_folder_to_folder(deps: &Graph<Node, ()>, start: &Tree, dest: &[String]) -> bool {
    for el in &start.targets {
        if itaid_from_node_to_folder(deps, *el, dest) {
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
}

fn direct_equivalency(part: Graph<Node, ()>) -> Graph<EquivNode, ()> {
    part.map(
        |ni, n| EquivNode {
            provides: n.provides,
            path: n.path,
            orig_path: n.path,
        },
        |_ei, &_e| _e,
    )
}

fn hoist_singles_upward(equiv: &mut Graph<EquivNode, ()>) {
    let mut stale = false;
    while !stale {
        stale = true;
        for ni in equiv.node_indices() {
            if equiv
                .node_indices()
                .filter(|&x| &equiv[x].path == &equiv[ni].path)
                .count()
                == 1
            {
                equiv[ni].path = &equiv[ni].path[..equiv[ni].path.len() - 1];
                stale = false;
            }
        }
    }
}

fn kill_common_prefix(equiv: &mut Graph<EquivNode, ()>) {
    loop {
        if equiv[NodeIndex::new(0)].path.len() == 0 {
            return;
        }
        let attempt = &equiv[NodeIndex::new(0)].path[0];
        if equiv
            .node_indices()
            .all(|x| equiv[x].path.first() == Some(attempt))
        {
            for ni in equiv.node_indices() {
                equiv[ni].path = &equiv[ni].path[1..equiv[ni].path.len()]
            }
        } else {
            return;
        }
    }
}

fn remove_top_elements(equiv: &mut Graph<EquivNode, ()>) {
    let mut to_be_added = Vec::new();
    for ni in equiv.node_indices() {
        if equiv[ni].path.len() == 0 {
            for incoming in equiv.edges_directed(ni, Incoming) {
                for outgoing in equiv.edges_directed(ni, Outgoing) {
                    to_be_added.push((incoming.source(), outgoing.target(), ()))
                }
            }
        }
    }
    for (a, b, weight) in to_be_added {
        equiv.update_edge(a, b, weight);
    }
    equiv.retain_nodes(|frozen, ni| frozen[ni].path.len() != 0);
}

fn shorten(dict: &Vec<&String>, long: &[String]) -> String {
    // long.iter()
    //     .map(|x| {
    //         char::from_u32('a' as u32 + dict.iter().position(|y| y == &x.as_str()).unwrap() as u32)
    //             .unwrap()
    //     })
    //     .join(" ")
    long.iter()
        .map(|x| {
            format!(
                "{: <2}",
                dict.iter().position(|y| y == &x.as_str()).unwrap(),
            )
        })
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

/// Removes all Nodes that can always be put in the right folder:
/// If e.g. a node n in b only depends on nodes in a and only nodes in c depends on n and there are no nodes in b that (directly or indirectly) depend on nodes in c and there are no nodes in a that depend (directly or indirectly) on nodes in c, then we can remove n.
/// Example of a Node that will not be removed:
/// a/1 -> b/2
/// b/3 -> c/4
/// c/5 -> a/6
/// Node 1 will not be removed
///
///
/// a/1 -> b/2
/// b/3 -> c/4
/// c/5 -> d/6
/// e/7 -> c/5
fn remove_always_happy(equiv: &mut Graph<EquivNode, ()>) {
    let mut helper_graph = equiv.clone();
    let mut to_be_added = Vec::new();
    for a in equiv.node_indices() {
        for b in equiv.node_indices() {
            if equiv[a].path[0] == equiv[b].path[0] {
                to_be_added.push((a, b));
            }
        }
    }
    for (a, b) in to_be_added {
        helper_graph.update_edge(a, b, ());
        helper_graph.update_edge(b, a, ());
    }
    {
        let count = equiv.node_count();
        // equiv.retain_nodes(|frozen, ni| {
        //     frozen
        //         .edges(ni)
        //         .any(|x| has_path_connecting(&helper_graph, x.target(), x.source(), None))
        // });
        equiv.retain_nodes(|frozen, ni| {
            frozen
                .edges_directed(ni, Outgoing)
                .any(|x| has_path_connecting(&helper_graph, x.target(), x.source(), None))
                || frozen
                    .edges_directed(ni, Incoming)
                    .any(|x| has_path_connecting(&helper_graph, x.target(), x.source(), None))
        });
        if equiv.node_count() == count {
            return;
        }
    }
}

fn plot(equiv: &Graph<EquivNode, ()>) {
    // cargo run | dot -Tsvg > output.svg
    let visu = equiv.map(
        |ni, n| {
            n.path
                .iter()
                .map(|x| match x.as_str() {
                    "TurbulenceModels" => "T",
                    "transportModels" => "M",
                    "thermophysicalModels" => "t",
                    "phaseSystemModels" => "p",
                    "parallel" => "l",
                    "decompose" => "d",
                    "reconstruct" => "r",
                    "regionModels" => "r",
                    "multiphaseInter" => "m",
                    "twoPhaseEuler" => "P",
                    "twoPhaseInter" => "I",
                    "reactingEuler" => "E",
                    "lagrangian" => "l",
                    _ => x,
                })
                .join(" ")
        },
        |_ei, &_e| _e,
    );
    println!("{:?}", Dot::with_config(&visu, &[Config::EdgeNoLabel]));
}

/// Returns what targets cannot build in their ideal path if we want to put subdir('a') before subdir('b')
fn cost_of_dir_a_before_dir_b(
    equiv: &Graph<EquivNode, ()>,
    dir_a: &str,
    dir_b: &str,
) -> HoistsNeeded {
    let exists_path = |a, b, invert| -> bool {
        if invert {
            has_path_connecting(equiv, b, a, None)
        } else {
            has_path_connecting(equiv, a, b, None)
        }
    };
    HoistsNeeded::All(
        equiv
            .edge_references()
            .filter_map(|e| {
                if equiv[e.source()].path[0] == dir_a && equiv[e.target()].path[0] == dir_b {
                    Some(HoistsNeeded::Any(
                        [(e.source(), dir_b, false), (e.target(), dir_a, true)]
                            .iter()
                            .map(|(ni, dir, invert)| {
                                let mut vec = equiv
                                    .node_indices()
                                    .filter(|&x| {
                                        equiv[x].path[0] == *dir && exists_path(x, *ni, *invert)
                                    })
                                    .collect::<Vec<_>>();
                                vec.push(*ni);
                                HoistsNeeded::All(
                                    vec.iter()
                                        .map(|&x| HoistsNeeded::Single(x))
                                        .collect::<Vec<_>>(),
                                )
                            })
                            .collect::<Vec<_>>(),
                    ))
                } else {
                    None
                }
            })
            .collect::<Vec<_>>(),
    )
}

fn cost_to_break_circle(equiv: &Graph<EquivNode, ()>, cycle: Vec<&str>) -> HoistsNeeded {
    let mut cost = Vec::new();
    for i in 0..cycle.len() {
        let target_dir = cycle[i];
        let source_dir = if i == 0 {
            cycle.last().unwrap()
        } else {
            cycle[i - 1]
        };
        cost.push(cost_of_dir_a_before_dir_b(equiv, source_dir, target_dir));
    }
    HoistsNeeded::Any(cost)
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

struct MyGraph<NW: Eq + Hash + Copy, EW> {
    graph: Graph<NW, EW>,
    node_map: HashMap<NW, NodeIndex>,
}

impl<NW: Eq + Hash + Copy, EW> MyGraph<NW, EW> {
    fn from_nodes(nodes: &[NW]) -> Self {
        assert!(nodes.iter().duplicates().next() == None);
        let mut this = Self {
            graph: Graph::<NW, EW>::new(),
            node_map: HashMap::<NW, NodeIndex>::new(),
        };
        for node in nodes {
            let ni = this.graph.add_node(*node);
            this.node_map.insert(*node, ni);
        }
        this
    }
}

fn convert_to_equivalent_problem(part: Graph<Node, ()>) {
    let mut equiv = direct_equivalency(part);
    hoist_singles_upward(&mut equiv);
    kill_common_prefix(&mut equiv);
    remove_top_elements(&mut equiv);
    remove_always_happy(&mut equiv);

    let dirs = equiv
        .node_indices()
        .map(|ni| &equiv[ni].path[0])
        .unique()
        .collect::<Vec<_>>();
    let node_to_group = |ni: NodeIndex| dirs.iter().position(|x| x == &&equiv[ni].path[0]).unwrap();
    //let edge_count_matrix = Vec::<Vec<i32>>::new();
    let mut edge_count_matrix = vec![vec![0; dirs.len()]; dirs.len()];
    for e in equiv.edge_references() {
        edge_count_matrix[node_to_group(e.source())][node_to_group(e.target())] += 1;
    }
    // for x in 0..dirs.len() {
    //     for y in 0..dirs.len() {
    //         print!("{: >3}", edge_count_matrix[x][y]);
    //     }
    //     println!("");
    // }
    // let mut dirgraph = Graph::<&str, ()>::new();
    // for dir in dirs {
    //     digraph.add_node();
    // }
    let mut dirgraph = MyGraph::<&String, ()>::from_nodes(&dirs);

    for x in 0..dirs.len() {
        for y in 0..dirs.len() {
            if x != y && edge_count_matrix[x][y] > 0 {
                dirgraph
                    .graph
                    .add_edge(dirgraph.node_map[dirs[x]], dirgraph.node_map[dirs[y]], ());
            }
            if x != y {
                println!(
                    "{: <20} {: >2} {} ",
                    dirs[x], edge_count_matrix[x][y], dirs[y]
                );
                //dbg!(cost_of_dir_a_before_dir_b(&equiv, dirs[x], dirs[y]));
            }
        }
    }
    dbg!(&dirgraph.graph);
    let cycles = graphalgs::elementary_circuits::elementary_circuits(&dirgraph.graph);
    let mut cost = Vec::new();
    for cycle in cycles {
        let cycle = cycle
            .iter()
            .map(|x| dirs[x.index()].as_str())
            .collect::<Vec<_>>();
        cost.push(cost_to_break_circle(&equiv, cycle));
    }
    let cost = HoistsNeeded::All(cost);
    minimum_hoists_needed(cost);
}

fn find_problematic_subtrees(deps: &Graph<Node, ()>, total_tree: &Tree, prefix: Vec<String>) {
    let mut dir_graph = Graph::<&str, ()>::new();
    let mut node_index_map: HashMap<&str, NodeIndex> = HashMap::new();
    let mut subtree = total_tree;
    for el in &prefix {
        subtree = &subtree.subdirs[el.as_str()];
    }
    for (key, value) in &subtree.subdirs {
        node_index_map.insert(key, dir_graph.add_node(key));
    }
    for (key1, value1) in &subtree.subdirs {
        for (key2, value2) in &subtree.subdirs {
            if key1 == key2 {
                continue;
            }
            let mut combined = prefix.clone();
            combined.push(key2.to_string());
            if itaid_from_folder_to_folder(&deps, value1, &combined[..]) {
                dir_graph.update_edge(node_index_map[key1], node_index_map[key2], ());
            }
        }
    }
    let sorted = topo_sort_group_cycles(&dir_graph);
    for single_or_cycle in sorted {
        if single_or_cycle.len() == 1 {
            let mut combined = prefix.clone();
            combined.push(dir_graph[single_or_cycle[0]].to_string());
            find_problematic_subtrees(deps, total_tree, combined);
        } else {
            {
                let mut combined = prefix.clone();
                combined.push(dir_graph[single_or_cycle[0]].to_string());
                find_problematic_subtrees(deps, total_tree, combined);
            }
            let interesting_nodes = single_or_cycle
                .iter()
                .map(|&dir_index| {
                    let dir = dir_graph[dir_index];
                    let mut combined = prefix.clone();
                    combined.push(dir.to_string());
                    deps.node_indices()
                        .filter(move |&x| is_in_group(deps, x, &combined))
                })
                .flatten()
                .collect::<Vec<_>>();
            let mut part = (*deps).clone();
            part.retain_nodes(|_, x| interesting_nodes.contains(&x));
            convert_to_equivalent_problem(part);
            // for &dir_index in &single_or_cycle {

            //         .collect::<Vec<_>>();
            //     dbg!(nodes_in_dir);
            // }
        }
    }
}

pub fn random_digraph(nodes: u32, nedges: u32) -> Result<Vec<(u32, u32)>, &'static str> {
    if nodes == 0 {
        return Ok(Vec::new());
    }

    if nedges > nodes * (nodes - 1) {
        return Err("Too many edges, too few nodes");
    }

    //let mut rng = rand::thread_rng();
    let mut rng = StdRng::seed_from_u64(123);
    let mut edges = Vec::with_capacity(nedges as usize);
    let mut count = 0;

    while count < nedges {
        let i = rng.gen_range(0..nodes);
        let j = rng.gen_range(0..nodes);

        if i != j && !edges.contains(&(i, j)) {
            edges.push((i, j));
            count += 1;
        }
    }

    Ok(edges)
}

fn main() {
    let file = std::fs::File::open("../../data.json").unwrap();
    let reader = std::io::BufReader::new(file);
    let dat: ImportedData = serde_json::from_reader(reader).unwrap();
    let mut deps = Graph::<Node, ()>::new();
    let mut root = Tree::new();

    let mut fvm = FiniteValuesMap::new();
    let mut node_index_map: HashMap<&str, NodeIndex> = HashMap::new();
    for (key, value) in &dat {
        assert_eq!(key, &value.provides);
        let node = deps.add_node(Node {
            provides: key,
            path: &value.outpath[..],
        });
        node_index_map.insert(&key, node);
        fvm.add(&value.provides, 0);
        let mut head = &mut root;
        for dirname in &value.outpath {
            // todo
            // head = head.subdirs.entry(dirname).or_insert(Tree::new())
            if !head.subdirs.contains_key(dirname.as_str()) {
                head.subdirs.insert(dirname, Tree::new());
            }
            head = head.subdirs.get_mut(dirname.as_str()).unwrap();
        }
        head.targets.push(node);
        value.ddeps.iter().for_each(|el| fvm.add(&el, 1));
        value
            .outpath
            .iter()
            .enumerate()
            .for_each(|el| fvm.add(&el.1, (2 + el.0).try_into().unwrap()));
    }
    for (key, value) in &dat {
        deps.extend_with_edges(
            value
                .ddeps
                .iter()
                .map(|el| (node_index_map[key.as_str()], node_index_map[el.as_str()])),
        );
    }
    match toposort(&deps, None) {
        Ok(_) => {}
        Err(_) => {
            println!("Graph cannot be topologically sorted.");
            std::process::exit(1);
        }
    }
    //simplify(&deps, &root, vec![]);
    //algo_test();
    find_problematic_subtrees(&deps, &root, vec![]);
}
