use std::collections::HashSet;

use enum_as_inner::EnumAsInner;
use itertools::Itertools;
type NodeIndex = petgraph::stable_graph::NodeIndex<petgraph::stable_graph::DefaultIx>;

/// HoistsNeeded indicates which nodes need to be noisted
/// All5 is an alternative format for this data.
#[derive(Debug, Clone, EnumAsInner)]
pub enum HoistsNeeded {
    Single(NodeIndex),
    Any(Vec<HoistsNeeded>),
    All(Vec<HoistsNeeded>),
}

/// Another format of Hoists Needed
#[derive(Debug, Clone)]
struct All5(Vec<Any4>);
#[derive(Debug, Clone)]
struct Any4(Vec<All3>);
#[derive(Debug, Clone)]
struct All3(Vec<Any2>);
#[derive(Debug, Clone)]
struct Any2(Vec<All1>);
#[derive(Debug, Clone)]
struct All1(Vec<NodeIndex>);
/// Same as All1, but uses a  HashSet instead of a Vec
#[derive(Debug, Clone, PartialEq)]
struct All1H(HashSet<NodeIndex>);
#[derive(Debug, Clone, PartialEq)]
struct Any2H(Vec<All1H>);

fn all1_converter(input: HoistsNeeded) -> All1 {
    All1(
        input
            .into_all()
            .unwrap()
            .into_iter()
            .map(|x| x.into_single().unwrap())
            .collect::<Vec<_>>(),
    )
}

fn any2_converter(input: HoistsNeeded) -> Any2 {
    Any2(
        input
            .into_any()
            .unwrap()
            .into_iter()
            .map(all1_converter)
            .collect::<Vec<_>>(),
    )
}

fn all3_converter(input: HoistsNeeded) -> All3 {
    All3(
        input
            .into_all()
            .unwrap()
            .into_iter()
            .map(any2_converter)
            .collect::<Vec<_>>(),
    )
}

fn any4_converter(input: HoistsNeeded) -> Any4 {
    Any4(
        input
            .into_any()
            .unwrap()
            .into_iter()
            .map(all3_converter)
            .collect::<Vec<_>>(),
    )
}

fn all5_converter(input: HoistsNeeded) -> All5 {
    All5(
        input
            .into_all()
            .unwrap()
            .into_iter()
            .map(any4_converter)
            .collect::<Vec<_>>(),
    )
}

fn get_nth_option_3(input: &All3, n: &Vec<usize>) -> All1H {
    All1H(
        (0..input.0.len())
            .map(|i| input.0[i].0[n[i]].0.clone())
            .flatten()
            .collect::<HashSet<_>>(),
    )
}

fn get_nth_option_5(input: &Vec<Vec<All1H>>, n: &Vec<usize>) -> All1H {
    All1H(
        (0..input.len())
            .map(|i| input[i][n[i]].0.clone())
            .flatten()
            .collect::<HashSet<_>>(),
    )
}

/// Tries to "increment" n, a.k.a. get the next option. "increment" is in quotes
/// because n is not simply a number. Returns true on success and false on
/// failure. It fails if the biggest number has been reached.
fn increment_n_3(input: &All3, n: &mut Vec<usize>) -> bool {
    let mut pos = 0;
    while n[pos] + 1 == input.0[pos].0.len() {
        pos += 1;
        if pos == n.len() {
            return false;
        }
    }
    n[pos] += 1;
    n[0..pos].fill(0);
    true
}

fn increment_n_5(input: &Vec<Vec<All1H>>, n: &mut Vec<usize>) -> bool {
    let mut pos = 0;
    while n[pos] + 1 == input[pos].len() {
        pos += 1;
        if pos == n.len() {
            return false;
        }
    }
    n[pos] += 1;
    n[0..pos].fill(0);
    true
}

fn flatten_all3(input: &All3) -> Any2H {
    let mut n = vec![0; input.0.len()];
    let mut ret = Vec::new();

    loop {
        ret.push(get_nth_option_3(&input, &n));
        if !increment_n_3(&input, &mut n) {
            break;
        }
    }
    Any2H(ret)
}

fn flatten_all5(input: Vec<Vec<All1H>>) -> Any2H {
    let mut n = vec![0; input.len()];
    let mut ret = Vec::new();

    loop {
        ret.push(get_nth_option_5(&input, &n));
        if !increment_n_5(&input, &mut n) {
            break;
        }
    }
    Any2H(ret)
}

fn remove_node(all3: &mut All3, node: NodeIndex) {
    for any2 in all3.0.iter_mut() {
        for all1 in any2.0.iter_mut() {
            all1.0.retain(|&ni| ni != node);
        }
    }
    // Remove conditions that are now trivially fulfilled. E.g.
    // Any2([
    //         All1([NodeIndex(41)]),
    //         All1([])
    // ])
    // Is trivially fulfilled.
    all3.0
        .retain(|all2| all2.0.iter().all(|all1| all1.0.len() != 0));
}

/// Not an exact algorithm, but an approximation that is way
/// faster than the fastest exact algorithm I can think of.
pub fn minimum_hoists_needed_approx(node_count: usize, cost: HoistsNeeded) -> HashSet<NodeIndex> {
    let mut all3 = all3_converter(cost);
    let mut hoists_chosen = HashSet::new();
    loop {
        let mut occurences = vec![0; node_count];
        for any2 in all3.0.iter() {
            for all1 in any2.0.iter() {
                if all1.0.len() == 1 {
                    occurences[all1.0[0].index()] += 1;
                }
            }
        }
        let most_common_node = NodeIndex::new(occurences.iter().position_max().unwrap());
        hoists_chosen.insert(most_common_node);
        // The earlier we exit, the slower and more precise this function will be.
        if occurences[most_common_node.index()] < 2 {
            break;
        }
        remove_node(&mut all3, most_common_node);
    }
    for any2 in all3.0.iter() {
        let minpos = any2.0.iter().position_min_by_key(|all1| all1.0.len());
        if let Some(minpos) = minpos {
            for &ni in &any2.0[minpos].0 {
                hoists_chosen.insert(ni);
            }
        }
    }
    hoists_chosen
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_flatten_all3() {
        let input = All3(vec![
            Any2(vec![
                All1(vec![NodeIndex::new(19)]),
                All1(vec![NodeIndex::new(33)]),
            ]),
            Any2(vec![
                All1(vec![NodeIndex::new(9)]),
                All1(vec![NodeIndex::new(33)]),
            ]),
        ]);
        let expected_output = Any2H(
            vec![
                All1H(
                    vec![NodeIndex::new(19), NodeIndex::new(9)]
                        .into_iter()
                        .collect(),
                ),
                All1H(
                    vec![NodeIndex::new(33), NodeIndex::new(9)]
                        .into_iter()
                        .collect(),
                ),
                All1H(
                    vec![NodeIndex::new(19), NodeIndex::new(33)]
                        .into_iter()
                        .collect(),
                ),
                All1H(vec![NodeIndex::new(33)].into_iter().collect()),
            ]
            .into_iter()
            .collect(),
        );
        let actual_output = flatten_all3(&input);
        assert_eq!(actual_output, expected_output);
    }
}
