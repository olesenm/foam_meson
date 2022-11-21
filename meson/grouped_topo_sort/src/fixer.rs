use permute::permutations_of;
use petgraph::visit::depth_first_search;
use petgraph::visit::{Control, DfsEvent};
use petgraph::Graph;
use std::collections::HashSet;

use crate::hoists::FastInt;
use crate::is_in_group;
use crate::print_time_complexity_note;
use crate::DepGraph;
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
                if &part[e.source()].path[0] == dir_a && &part[e.target()].path[0] == dir_b {
                    Some(HoistsNeeded::Any(
                        [(e.source(), dir_b, false), (e.target(), dir_a, true)]
                            .iter()
                            .map(|(ni, dir, invert)| {
                                let mut vec = part
                                    .node_indices()
                                    .filter(|&x| {
                                        part[x].path[0] == **dir && exists_path(x, *ni, *invert)
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

/// If a directory contains only one node, we hoist these nodes up. Note that
/// `move_singles_downwards` will later revert this affect.
fn hoist_singles_upward(part: &mut Graph<EquivNode, ()>) {
    let mut stale = false;
    while !stale {
        stale = true;
        for ni in part.node_indices() {
            if part
                .node_indices()
                .filter(|&x| path_begins_with(part[x].path, part[ni].path))
                .count()
                == 1
                && !part[ni].path.is_empty()
            {
                part[ni].path = &part[ni].path[..part[ni].path.len() - 1];
                stale = false;
            }
        }
    }
}

fn kill_common_prefix(part: &mut Graph<EquivNode, ()>) {
    loop {
        if part[NodeIndex::new(0)].path.is_empty() {
            return;
        }
        let attempt = &part[NodeIndex::new(0)].path[0];
        if part
            .node_indices()
            .all(|x| part[x].path.first() == Some(attempt))
        {
            for ni in part.node_indices() {
                part[ni].path = &part[ni].path[1..part[ni].path.len()]
            }
        } else {
            return;
        }
    }
}

fn remove_top_elements<'o>(part: &mut Graph<EquivNode<'o>, ()>) -> HoistsNeededNamed<'o> {
    let mut hoists_always_needed = Vec::new();
    let mut edges = Vec::new();
    for ni in part.node_indices() {
        if part[ni].path.is_empty() {
            for incoming in part.edges_directed(ni, Incoming) {
                for outgoing in part.edges_directed(ni, Outgoing) {
                    let source = incoming.source();
                    let target = outgoing.target();
                    // If we have this configuration:
                    // a/1 -> 2
                    // 2   -> b/3
                    // We remove node 2 (later in this function) and add an edge:
                    // a/2 -> b/3
                    edges.push((source, target, ()));
                    if part[source].path[0] == part[target].path[0] {
                        // If we have this configuration:
                        // a/1 -> 2
                        // 2   -> 3
                        // 3   -> 4
                        // 4   -> a/5
                        // Removing node 2,3,4 and adding the edge a/1 -> a/5 is not enough, we need to note that we have to hoist either Node 1 or Node 5
                        hoists_always_needed.push(HoistsNeededNamed::Any(vec![
                            HoistsNeededNamed::Single(part[source].provides),
                            HoistsNeededNamed::Single(part[target].provides),
                        ]));
                        // #PERFORMANCE: Here, we create two vectors that always
                        // have a length of 1. This is inefficient, the type
                        // `Vec<FastInt>` could be replaced by the type
                        // `FastInt`.
                    }
                }
            }
        }
    }
    for (a, b, weight) in edges {
        part.update_edge(a, b, weight);
    }
    part.retain_nodes(|frozen, ni| !frozen[ni].path.is_empty());
    HoistsNeededNamed::All(hoists_always_needed)
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
            if part[a].path[0] == part[b].path[0] {
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
fn simple_simplifications<'o>(part: &mut Graph<Node<'o>, ()>) -> HoistsNeededNamed<'o> {
    hoist_singles_upward(part);
    kill_common_prefix(part);
    let hoists_always_needed = remove_top_elements(part);
    remove_always_happy(part);
    hoists_always_needed
}

/// Number of hoists that are needed if we want the dirs to be in the `order` order.
fn cost_of_order(
    node_count: usize,
    cost_of_a_before_b: &mut Vec<Vec<FastHN>>,
    order: &Vec<usize>,
    hoists_always_needed: &mut FastHN,
) -> HashSet<FastInt> {
    // If e.g. `7` comes before `5` in `order`, then `cost_of_a_before_b[7][5]` will be added to `all`, but `cost_of_a_before_b[5][7]` won't.
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
        .chain(std::iter::once(hoists_always_needed))
        .filter(|el| !el.0.is_empty())
        .collect::<Vec<_>>();
    minimum_hoists_needed_approx(node_count, all)
}

fn find_hoists_needed_for_subgraph<'a, 'o: 'a>(
    all_hoists: &'a mut Vec<Hoist<'o>>,
    prefix: &'a Vec<&'o DirName>,
    mut part: Graph<Node<'o>, ()>,
) {
    let hoists_always_needed = simple_simplifications(&mut part);
    let hoists_always_needed = hoists_always_needed.names_to_indices(&part);
    let mut hoists_always_needed = FastHN::from_hn(hoists_always_needed);
    // #Performance: Maybe we could do some pre-computation on hoists_always_needed here
    let dirs = part
        .node_indices()
        .map(|ni| &part[ni].path[0])
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
                cost_of_order(
                    part.node_count(),
                    &mut cost_of_a_before_b,
                    &order,
                    &mut hoists_always_needed,
                ),
            )
        })
        .min_by_key(|el| el.1.len())
        .unwrap();

    // todo: I don't think we need optimal_order

    all_hoists.extend(hoists_needed.iter().map(|&x| Hoist {
        target: part[NodeIndex::new(x)].provides,
        actual_path: prefix.iter().cloned().cloned().collect::<Vec<DirName>>(),
    }));
}

pub fn find_all_hoists_needed<'a, 'o: 'a>(
    hoists: &'a mut Vec<Hoist<'o>>,
    deps: &'a DepGraph<'o>,
    tree: &'a Tree<'o>,
    prefix: Vec<&'o DirName>,
) {
    // #APPROX: We first descend into subdirectories and fix those, then we fix this group of dirs. I.e. we solve both problems separately. I'm not sure if there might be coupling between those two problems
    for key in tree.get_subtree_from_prefix(&prefix).subdirs.keys() {
        let mut combined = prefix.clone();
        combined.push(key);
        find_all_hoists_needed(hoists, deps, tree, combined);
    }

    let mut owner = Vec::new();
    let dir_graph = gen_dir_graph(&mut owner, deps, tree, &prefix).graph;
    let mut tarjan = petgraph::algo::TarjanScc::new();
    tarjan.run(&dir_graph, |groups| {
        if groups.len() != 1 {
            // if groups.len() != 1, we found a cycle of groups. We first identify the relevant subgraph, then pass it to find_hoists_needed_for_subgraph which finds/chooses hoists that break the cycle.
            let interesting_nodes = groups
                .iter()
                .flat_map(|&x| match dir_graph[x] {
                    DirOrSingle::Dir(dir) => {
                        let mut combined = prefix.clone();
                        combined.push(dir);
                        deps.graph
                            .node_indices()
                            .filter(move |&x| is_in_group(deps, x, &combined))
                            .collect::<Vec<_>>()
                    }
                    DirOrSingle::Single(single) => {
                        vec![deps.get_node_index(single)]
                    }
                })
                .collect::<Vec<_>>();
            let mut part = deps.graph.clone();
            part.retain_nodes(|_, x| interesting_nodes.contains(&x));
            find_hoists_needed_for_subgraph(hoists, &prefix, part);
        }
    });
}
