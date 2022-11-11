use permute::permutations_of;
use petgraph::Graph;
use std::collections::HashMap;

use crate::is_in_group;
use crate::itaid_from_folder_to_folder;
use crate::print_time_complexity_note;
use crate::topo_sort_group_cycles;
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

/// Reverts the effect of hoist_singles_upward
fn move_singles_downwards() {
    todo!()
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
                && part[ni].path.len() != 0
            {
                part[ni].path = &part[ni].path[..part[ni].path.len() - 1];
                stale = false;
            }
        }
    }
}

fn kill_common_prefix(part: &mut Graph<EquivNode, ()>) {
    loop {
        if part[NodeIndex::new(0)].path.len() == 0 {
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

fn remove_top_elements(part: &mut Graph<EquivNode, ()>) {
    let mut edges = Vec::new();
    for ni in part.node_indices() {
        if part[ni].path.len() == 0 {
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
    part.retain_nodes(|frozen, ni| frozen[ni].path.len() != 0);
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
fn simple_simplifications(part: &mut Graph<Node, ()>) {
    hoist_singles_upward(part);
    kill_common_prefix(part);
    remove_top_elements(part);
    remove_always_happy(part);
}

/// Number of hoists that are needed if we want the dirs to be in the `order` order.
fn cost_of_order(
    node_count: usize,
    cost_of_a_before_b: &Vec<Vec<HoistsNeeded>>,
    order: &Vec<usize>,
) -> usize {
    let mut all = Vec::new();
    for l in 0..(order.len() - 1) {
        for r in (l + 1)..order.len() {
            all.append(
                &mut cost_of_a_before_b[order[l]][order[r]]
                    .as_all()
                    .unwrap()
                    .clone(),
            );
        }
    }
    let all = HoistsNeeded::All(all);
    minimum_hoists_needed_approx(node_count, all).len()
}

fn fix_problematic_subgraph(mut part: Graph<Node, ()>) {
    simple_simplifications(&mut part);
    let dirs = part
        .node_indices()
        .map(|ni| &part[ni].path[0])
        .unique()
        .collect::<Vec<_>>();
    print_time_complexity_note(dirs.len());

    let cost_of_a_before_b = dirs
        .iter()
        .map(|x| {
            dirs.iter()
                .map(|y| cost_of_dir_a_before_dir_b(&part, x, y))
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();

    // let temp = cost_of_a_before_b
    //     .clone()
    //     .into_iter()
    //     .map(|x| {
    //         x.into_iter()
    //             .map(|y| Fast_HN_OrderDependent::from_hn(y))
    //             .collect::<Vec<_>>()
    //     })
    //     .collect::<Vec<_>>();

    // let estimate_memory_needed = (0..cost_of_a_before_b.len())
    //     .map(|x| {
    //         (0..cost_of_a_before_b.len())
    //             .map(|y| cost_of_a_before_b[x][y].max(cost_of_a_before_b[y][x]))
    //             .sum::<usize>()
    //     })
    //     .sum::<usize>();

    dbg!(permutations_of(&(0..dirs.len()).collect::<Vec<_>>())
        .map(|order| {
            let order = order.map(|x| *x).collect::<Vec<_>>();
            (
                order.clone(),
                cost_of_order(part.node_count(), &cost_of_a_before_b, &order),
            )
        })
        .min_by_key(|el| el.1));
}

/// The returned graph contains an edge from a to b, exactly if deps contains an
/// edge from
/// tree/prefix[0]/prefix[1]/.../prefix[prefix.len()-1]/a/foo/bar/node1
/// to
/// tree/prefix[0]/prefix[1]/.../prefix[prefix.len()-1]/b/something/node2
fn gen_dir_graph<'a>(deps: &'a DepGraph, tree: &'a Tree, prefix: &Vec<&DirName>) -> DirGraph<'a> {
    let subtree = prefix.iter().fold(tree, |acc, x| &acc.subdirs[x]);
    let mut ret =
        DirGraph::from_nodes(&subtree.subdirs.iter().map(|(&k, v)| k).collect::<Vec<_>>());
    for (key1, value1) in &subtree.subdirs {
        for (key2, value2) in &subtree.subdirs {
            if key1 == key2 {
                continue;
            }
            let mut dirpath = prefix.clone();
            dirpath.push(key2);
            if itaid_from_folder_to_folder(&deps, value1, &dirpath) {
                ret.add_edge(key1, key2, ());
            }
        }
    }
    ret
}

pub fn find_and_fix_problematic_subgraph(deps: &DepGraph, tree: &Tree, prefix: Vec<&DirName>) {
    let dir_graph = gen_dir_graph(deps, tree, &prefix).graph;
    let mut tarjan = petgraph::algo::TarjanScc::new();
    tarjan.run(&dir_graph, |single_or_cycle| {
        if single_or_cycle.len() == 1 {
            let mut combined = prefix.clone();
            combined.push(dir_graph[single_or_cycle[0]]);
            find_and_fix_problematic_subgraph(deps, tree, combined);
        } else {
            // #APPROX: We first descend into subdirectories and fix those, then we fix this group of dirs. I.e. we solve both problems separately. I'm not sure if there might be coupling between those two problems
            for dir in single_or_cycle {
                let mut combined = prefix.clone();
                combined.push(dir_graph[single_or_cycle[0]]);
                find_and_fix_problematic_subgraph(deps, tree, combined);
            }
            let interesting_nodes = single_or_cycle
                .iter()
                .map(|&dir_index| {
                    let mut combined = prefix.clone();
                    combined.push(dir_graph[dir_index]);
                    deps.graph
                        .node_indices()
                        .filter(move |&x| is_in_group(deps, x, &combined))
                })
                .flatten()
                .collect::<Vec<_>>();
            let mut part = deps.graph.clone();
            part.retain_nodes(|_, x| interesting_nodes.contains(&x));
            fix_problematic_subgraph(part);
        }
    });
}
