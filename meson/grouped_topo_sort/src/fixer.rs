use permute::permutations_of;
use petgraph::Graph;
use serde::Serialize;
use std::collections::HashSet;

use crate::hoists::FastInt;
use crate::is_in_group;
use crate::itaid_from_folder_to_folder;
use crate::print_time_complexity_note;
use crate::DepGraph;
use crate::DirGraph;
use crate::DirName;
use crate::HoistsNeeded;
use crate::Node;
use crate::NodeIndex;
use crate::Tree;
use crate::*; // todo

/// Returns what targets need to be hoisted if we want to put subdir('a') before subdir('b').
fn cost_of_dir_a_before_dir_b(
    part: &Graph<EquivNode, ()>,
    dir_a: &DirName,
    dir_b: &DirName,
) -> HoistsNeeded {
    if dir_a == dir_b {
        // Calling this function with dir_a == dir_b is kind of nonsensical, so
        // we just return something simple to make debugging easy.
        return HoistsNeeded::All(Vec::new());
    }
    let exists_path = |a, b, invert| -> bool {
        if invert {
            has_path_connecting(part, b, a, None)
        } else {
            has_path_connecting(part, a, b, None)
        }
    };
    HoistsNeeded::All(
        part.edge_references()
            .filter_map(|e| {
                if &part[e.source()].ideal_path[0] == dir_a
                    && &part[e.target()].ideal_path[0] == dir_b
                {
                    Some(HoistsNeeded::Any(
                        [(e.source(), dir_b, false), (e.target(), dir_a, true)]
                            .iter()
                            .map(|(ni, dir, invert)| {
                                let mut vec = part
                                    .node_indices()
                                    .filter(|&x| {
                                        part[x].ideal_path[0] == **dir
                                            && exists_path(x, *ni, *invert)
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

/// If a directory contains only one node, we hoist these nodes up. Note that
/// `move_singles_downwards` will later revert this affect.
fn hoist_singles_upward(part: &mut Graph<EquivNode, ()>) {
    let mut stale = false;
    while !stale {
        stale = true;
        for ni in part.node_indices() {
            if part
                .node_indices()
                .filter(|&x| path_begins_with(part[x].ideal_path, part[ni].ideal_path))
                .count()
                == 1
                && !part[ni].ideal_path.is_empty()
            {
                part[ni].ideal_path = &part[ni].ideal_path[..part[ni].ideal_path.len() - 1];
                stale = false;
            }
        }
    }
}

fn kill_common_prefix(part: &mut Graph<EquivNode, ()>) {
    loop {
        if part[NodeIndex::new(0)].ideal_path.is_empty() {
            return;
        }
        let attempt = &part[NodeIndex::new(0)].ideal_path[0];
        if part
            .node_indices()
            .all(|x| part[x].ideal_path.first() == Some(attempt))
        {
            for ni in part.node_indices() {
                part[ni].ideal_path = &part[ni].ideal_path[1..part[ni].ideal_path.len()]
            }
        } else {
            return;
        }
    }
}

fn remove_top_elements(part: &mut Graph<EquivNode, ()>) {
    let mut edges = Vec::new();
    for ni in part.node_indices() {
        if part[ni].ideal_path.is_empty() {
            for incoming in part.edges_directed(ni, Incoming) {
                for outgoing in part.edges_directed(ni, Outgoing) {
                    edges.push((incoming.source(), outgoing.target(), ()))
                }
            }
        }
    }
    for (a, b, weight) in edges {
        part.update_edge(a, b, weight);
    }
    part.retain_nodes(|frozen, ni| !frozen[ni].ideal_path.is_empty());
}

/// Removes all Nodes that can always be put in the right folder:
/// If e.g. a node n in b only depends on nodes in a and only nodes in c depends on n and there are no nodes in b that (directly or indirectly) depend on nodes in c and there are no nodes in a that depend (directly or indirectly) on nodes in c, then we can remove n.
/// # Example
/// Here, Node 1 would b removed
/// ```
/// a/1 -> b/2
/// b/3 -> c/4
/// c/5 -> d/6
/// e/7 -> c/5
/// ```
fn remove_always_happy(part: &mut Graph<EquivNode, ()>) {
    let mut helper_graph = part.clone();
    let mut edges = Vec::new();
    for a in part.node_indices() {
        for b in part.node_indices() {
            if part[a].ideal_path[0] == part[b].ideal_path[0] {
                edges.push((a, b));
            }
        }
    }
    for (a, b) in edges {
        helper_graph.update_edge(a, b, ());
        helper_graph.update_edge(b, a, ());
    }
    part.retain_nodes(|frozen, ni| {
        frozen
            .edges_directed(ni, Outgoing)
            .any(|x| has_path_connecting(&helper_graph, x.target(), x.source(), None))
            || frozen
                .edges_directed(ni, Incoming)
                .any(|x| has_path_connecting(&helper_graph, x.target(), x.source(), None))
    });
}

/// Some more or less trivial simplifications to the tree. These are (afaik) not necessary for correctness, but boost the performance by removing some elements.
fn simple_simplifications(part: &mut Graph<Node, ()>) {
    hoist_singles_upward(part);
    kill_common_prefix(part);
    remove_top_elements(part);
    remove_always_happy(part);
}

/// Number of hoists that are needed if we want the dirs to be in the `order` order.
fn cost_of_order(
    node_count: usize,
    cost_of_a_before_b: &mut Vec<Vec<FastHN>>,
    order: &Vec<usize>,
) -> HashSet<FastInt> {
    let all = cost_of_a_before_b
        .iter_mut()
        .enumerate()
        .flat_map(|(l, x)| {
            x.iter_mut()
                .enumerate()
                .filter(move |(r, _y)| {
                    order.iter().position(|&i| i == l) < order.iter().position(|i| i == r)
                })
                .map(|(_r, y)| y)
        })
        .filter(|el| !el.0.is_empty())
        .collect::<Vec<_>>();
    minimum_hoists_needed_approx(node_count, all)
}

fn find_hoists_needed_for_subgraph<'a, 'o: 'a>(
    all_hoists_needed: &'a mut Vec<Hoist<'o>>,
    prefix: &'a Vec<&'o DirName>,
    mut part: Graph<Node<'o>, ()>,
) {
    simple_simplifications(&mut part);
    let dirs = part
        .node_indices()
        .map(|ni| &part[ni].ideal_path[0])
        .unique()
        .collect::<Vec<_>>();

    let mut cost_of_a_before_b = dirs
        .iter()
        .map(|x| {
            dirs.iter()
                .map(|y| FastHN::from_hn(cost_of_dir_a_before_dir_b(&part, x, y)))
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();

    print_time_complexity_note(dirs.len());
    let (_optimal_order, hoists_needed) = permutations_of(&(0..dirs.len()).collect::<Vec<_>>())
        .map(|order| {
            let order = order.copied().collect::<Vec<_>>();
            (
                order.clone(),
                cost_of_order(part.node_count(), &mut cost_of_a_before_b, &order),
            )
        })
        .min_by_key(|el| el.1.len())
        .unwrap();

    // todo: I don't think we need optimal_order

    all_hoists_needed.extend(hoists_needed.iter().map(|&x| Hoist {
        target: part[NodeIndex::new(x)].provides,
        actual_path: prefix.to_vec(),
    }));
}

/// The returned graph contains an edge from a to b, exactly if deps contains an
/// edge from
/// tree/prefix[0]/prefix[1]/.../prefix[prefix.len()-1]/a/foo/bar/node1
/// to
/// tree/prefix[0]/prefix[1]/.../prefix[prefix.len()-1]/b/something/node2
fn gen_dir_graph<'a, 'o: 'a>(
    deps: &'a DepGraph<'o>,
    tree: &'a Tree<'o>,
    prefix: &'a Vec<&'o DirName>,
) -> DirGraph<'o> {
    let subtree = prefix.iter().fold(tree, |acc, x| &acc.subdirs[x]);
    let mut ret =
        DirGraph::from_nodes(&subtree.subdirs.iter().map(|(&k, _v)| k).collect::<Vec<_>>());
    for (key1, value1) in &subtree.subdirs {
        for key2 in subtree.subdirs.keys() {
            if key1 == key2 {
                continue;
            }
            let mut dirpath = prefix.clone();
            dirpath.push(key2);
            if itaid_from_folder_to_folder(deps, value1, &dirpath) {
                ret.add_edge(key1, key2, ());
            }
        }
    }
    ret
}

#[derive(Debug, Serialize, PartialEq, Eq)]
/// Indicates that `target` will not be build in its ideal path, but in `actual_path`.
pub struct Hoist<'a> {
    target: &'a TargetName,
    actual_path: Vec<&'a DirName>,
}

pub fn find_all_hoists_needed<'a, 'o: 'a>(
    hoists_needed: &'a mut Vec<Hoist<'o>>,
    deps: &'a DepGraph<'o>,
    tree: &'a Tree<'o>,
    prefix: Vec<&'o DirName>,
) {
    let dir_graph = gen_dir_graph(deps, tree, &prefix).graph;
    let mut tarjan = petgraph::algo::TarjanScc::new();
    tarjan.run(&dir_graph, |single_or_cycle| {
        if single_or_cycle.len() == 1 {
            let mut combined = prefix.clone();
            combined.push(dir_graph[single_or_cycle[0]]);
            find_all_hoists_needed(hoists_needed, deps, tree, combined);
        } else {
            // #APPROX: We first descend into subdirectories and fix those, then we fix this group of dirs. I.e. we solve both problems separately. I'm not sure if there might be coupling between those two problems
            for dir in single_or_cycle {
                let mut combined = prefix.clone();
                combined.push(dir_graph[*dir]);
                find_all_hoists_needed(hoists_needed, deps, tree, combined);
            }
            let interesting_nodes = single_or_cycle
                .iter()
                .flat_map(|&dir_index| {
                    let mut combined = prefix.clone();
                    combined.push(dir_graph[dir_index]);
                    deps.graph
                        .node_indices()
                        .filter(move |&x| is_in_group(deps, x, &combined))
                })
                .collect::<Vec<_>>();
            let mut part = deps.graph.clone();
            part.retain_nodes(|_, x| interesting_nodes.contains(&x));
            find_hoists_needed_for_subgraph(hoists_needed, &prefix, part);
        }
    });
}
