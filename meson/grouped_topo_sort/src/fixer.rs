use petgraph::Graph;
use std::collections::HashMap;

use crate::convert_to_equivalent_problem;
use crate::is_in_group;
use crate::itaid_from_folder_to_folder;
use crate::topo_sort_group_cycles;
use crate::DepGraph;
use crate::DirName;
use crate::NodeIndex;
use crate::Tree;

pub fn find_and_fix_problematic_subtrees(
    deps: &DepGraph,
    total_tree: &Tree,
    prefix: Vec<&DirName>,
) {
    let mut dir_graph = Graph::<&DirName, ()>::new();
    let mut node_index_map: HashMap<&DirName, NodeIndex> = HashMap::new();
    let mut subtree = total_tree;
    for el in &prefix {
        subtree = &subtree.subdirs[el];
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
            combined.push(key2);
            if itaid_from_folder_to_folder(&deps, value1, &combined[..]) {
                dir_graph.update_edge(node_index_map[key1], node_index_map[key2], ());
            }
        }
    }
    let sorted = topo_sort_group_cycles(&dir_graph);
    for single_or_cycle in sorted.iter().rev() {
        if single_or_cycle.len() == 1 {
            let mut combined = prefix.clone();
            combined.push(dir_graph[single_or_cycle[0]]);
            find_and_fix_problematic_subtrees(deps, total_tree, combined);
        } else {
            {
                let mut combined = prefix.clone();
                combined.push(dir_graph[single_or_cycle[0]]);
                find_and_fix_problematic_subtrees(deps, total_tree, combined);
            }
            let interesting_nodes = single_or_cycle
                .iter()
                .map(|&dir_index| {
                    let dir = dir_graph[dir_index];
                    let mut combined = prefix.clone();
                    combined.push(dir);
                    deps.graph
                        .node_indices()
                        .filter(move |&x| is_in_group(deps, x, &combined))
                })
                .flatten()
                .collect::<Vec<_>>();
            let mut part = deps.graph.clone();
            part.retain_nodes(|_, x| interesting_nodes.contains(&x));
            convert_to_equivalent_problem(part);
            // for &dir_index in &single_or_cycle {

            //         .collect::<Vec<_>>();
            //     dbg!(nodes_in_dir);
            // }
        }
    }
}
