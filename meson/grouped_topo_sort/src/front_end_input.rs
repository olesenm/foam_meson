use petgraph::algo::toposort;
use petgraph::Graph;
use serde::Deserialize;
use std::collections::HashMap;

use crate::BetterGraph;
use crate::DepGraph;
use crate::DirName;
use crate::Node;
use crate::NodeIndex;
use crate::TargetName;
use crate::Tree;

#[derive(Debug, Deserialize)]
pub struct ImportedTarget {
    provides: String,
    ddeps: Vec<String>,
    ideal_path: Vec<String>,
}

type ImportedData = Vec<ImportedTarget>;

/// The `owner` variable is just there to make the borrow checker happy. Just pass an empty Vec and ignore the Vec afterwards.
pub fn parse<R: std::io::Read>(
    owner: &mut Vec<(TargetName, Vec<TargetName>, Vec<DirName>)>,
    rdr: R,
) -> (DepGraph, Tree) {
    let dat: ImportedData = serde_json::from_reader(rdr).unwrap();

    // This variable looks like it could be refactored out, but the borrow checker will complain.
    owner.extend(dat.into_iter().map(|x| {
        (
            TargetName(x.provides),
            x.ddeps
                .into_iter()
                .map(|y| TargetName(y))
                .collect::<Vec<_>>(),
            x.ideal_path
                .into_iter()
                .map(|y| DirName(y))
                .collect::<Vec<_>>(),
        )
    }));
    //.collect::<Vec<_>>();

    let mut deps = DepGraph::new();
    let mut tree = Tree::new();

    for (provides, ddeps, ideal_path) in owner.iter() {
        let node = Node {
            provides: provides,
            path: ideal_path,
        };
        deps.add_node(node, &provides);

        let mut head = &mut tree;
        for dirname in ideal_path {
            head = head.subdirs.entry(dirname).or_insert(Tree::new());
        }
        head.targets.push(provides);
    }
    for (provides, ddeps, ideal_path) in owner.iter() {
        for x in ddeps.iter() {
            deps.add_edge(provides, x, ());
        }
    }
    if toposort(&deps.graph, None).is_err() {
        println!("Graph cannot be topologically sorted.");
        std::process::exit(1);
    }
    (deps, tree)
}

// todo
// fn weird() {
//     let mut owner = Vec::new();
//     let mut borrower = Vec::new();
//     for el in [String::from("abc"), String::from("def")] {
//         owner.push(el);
//         let ptr = owner.last().unwrap();
//         borrower.push(&ptr);
//     }
// }

// fn mix() {
//     let mut owner = Vec::new();
//     let mut borrower = Vec::new();

//     let el = String::from("abc");
//     owner.push(el);
//     let ptr = owner.last().unwrap();
//     borrower.push(&ptr);

//     let el = String::from("def");
//     owner.push(el);
//     let ptr = owner.last().unwrap();
//     borrower.push(&ptr);
// }

// fn work() {
//     let mut owner = Vec::new();
//     let mut borrower = Vec::new();
//     for el in [String::from("abc"), String::from("def")] {
//         owner.push(el);
//     }
//     for el in owner.iter() {
//         borrower.push(el);
//     }
// }
