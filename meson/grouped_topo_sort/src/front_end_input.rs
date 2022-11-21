use petgraph::algo::toposort;
use serde::Deserialize;

use crate::DepGraph;
use crate::DirName;
use crate::Node;
use crate::TargetName;
use crate::Tree;

#[cfg(feature = "arbitrary")]
pub mod fuzz_input {
    #[derive(Debug, arbitrary::Arbitrary)]
    pub struct FuzzInput {
        pub ddeps: Vec<u8>,
        pub ideal_path: Vec<u8>,
    }
}
#[derive(Debug, Deserialize)]
#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
pub struct ImportedTarget {
    pub provides: String,
    pub ddeps: Vec<String>,
    pub ideal_path: Vec<String>,
}

pub type ImportedData = Vec<ImportedTarget>;

#[derive(Debug)]
pub enum ParseError {
    DepgraphCycle,
    DependencyDoesNotExist(String, String),
}

pub fn inner_parse(
    owner: &mut Vec<(TargetName, Vec<TargetName>, Vec<DirName>)>,
    dat: ImportedData,
) -> Result<(DepGraph, Tree), ParseError> {
    // This variable looks like it could be refactored out, but the borrow checker will complain.
    owner.extend(dat.into_iter().map(|x| {
        (
            TargetName(x.provides),
            x.ddeps.into_iter().map(TargetName).collect::<Vec<_>>(),
            x.ideal_path.into_iter().map(DirName).collect::<Vec<_>>(),
        )
    }));
    //.collect::<Vec<_>>();

    let mut deps = DepGraph::new();
    let mut tree = Tree::new();

    for (provides, _ddeps, ideal_path) in owner.iter() {
        let node = Node {
            provides,
            path: ideal_path,
        };

        deps.add_node(node, provides);

        let mut head = &mut tree;
        for dirname in ideal_path {
            head = head.subdirs.entry(dirname).or_insert_with(Tree::new);
        }
        head.targets.push(provides);
    }
    for (provides, ddeps, _ideal_path) in owner.iter() {
        for x in ddeps.iter() {
            if !deps.node_map.contains_key(x) {
                return Err(ParseError::DependencyDoesNotExist(
                    provides.0.clone(),
                    x.0.clone(),
                ));
            }
            deps.update_edge(&provides, &x, ());
        }
    }
    if toposort(&deps.graph, None).is_err() {
        return Err(ParseError::DepgraphCycle);
    }
    Ok((deps, tree))
}

/// The `owner` variable is just there to make the borrow checker happy. Just pass an empty Vec and ignore the Vec afterwards.
pub fn parse<R: std::io::Read>(
    owner: &mut Vec<(TargetName, Vec<TargetName>, Vec<DirName>)>,
    rdr: R,
) -> (DepGraph, Tree) {
    let dat: ImportedData = serde_json::from_reader(rdr).unwrap();
    inner_parse(owner, dat).unwrap()
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
