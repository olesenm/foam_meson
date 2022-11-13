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

/// I experimented with different integer lengths, but it made no real impact, so I just set it to usize.
type FastInt = usize;

// todo: documentation of FastHN and pretty printing
/// The boolean indicates if the `[Vec<FastInt>; 2]` is "disabled", i.e. it should be ignored. Afaik, this "disabling" is faster than removing elements from the vec.
#[derive(Debug, Clone)]
#[allow(non_camel_case_types)]
pub struct Fast_HN_OrderDependent(pub Vec<(bool, [Vec<FastInt>; 2])>);
// pub struct Fast_HN_OrderDependent<'a>(&'a [[&'a [FastInt]; 2]]);

impl Fast_HN_OrderDependent {
    fn helper(all1: HoistsNeeded) -> Vec<FastInt> {
        all1.into_all()
            .unwrap()
            .into_iter()
            .map(|x| x.into_single().unwrap().index() as FastInt)
            .collect::<Vec<_>>()
    }

    /// Converts a slow, flexible and simple datatype into a fast and restrictive datatype
    pub fn from_hn(all3: HoistsNeeded) -> Self {
        Self(
            all3.into_all()
                .unwrap()
                .into_iter()
                .map(|any2| {
                    let mut vec = any2.into_any().unwrap();
                    assert!(vec.len() == 2);
                    let second = vec.pop().unwrap();
                    let first = vec.pop().unwrap();
                    (false, [Self::helper(first), Self::helper(second)])
                })
                .collect::<Vec<_>>(),
        )
    }
}

// todo would something like this be faster:
// enum FastHN1 {
//     Single(FastInt),
//     Multiiple(Vec<FastInt>),
// }

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

fn count_occurences(node_count: usize, cost: &Vec<&mut Fast_HN_OrderDependent>) -> Vec<usize> {
    let mut occurences = vec![0; node_count];
    for a in cost.iter() {
        for b in a.0.iter() {
            if b.0 {
                for c in b.1.iter() {
                    if c.len() == 1 {
                        occurences[c[0] as usize] += 1;
                    }
                }
            }
        }
    }
    occurences
}

fn disable_solved_problems(cost: &mut Vec<&mut Fast_HN_OrderDependent>, node: FastInt) {
    for all3 in cost.iter_mut() {
        for any2 in all3.0.iter_mut() {
            for all1 in any2.1.iter() {
                if all1.len() == 1 && all1[0] == node {
                    any2.0 = false;
                    break;
                }
            }
        }
    }
}

/// #APPROX: Not an exact algorithm, but an approximation that is way faster
/// than the fastest exact algorithm I can think of.
pub fn minimum_hoists_needed_approx(
    node_count: usize,
    mut cost: Vec<&mut Fast_HN_OrderDependent>,
) -> HashSet<FastInt> {
    let mut hoists_chosen = HashSet::new();
    for all3 in cost.iter_mut() {
        for any2 in all3.0.iter_mut() {
            any2.0 = true;
        }
    }
    loop {
        let occurences = count_occurences(node_count, &cost);
        let most_common_node = occurences.iter().position_max().unwrap() as FastInt;
        if occurences[most_common_node as usize] < 2 {
            break;
        }
        hoists_chosen.insert(most_common_node);
        disable_solved_problems(&mut cost, most_common_node);
    }
    for all3 in cost.iter() {
        for any2 in all3.0.iter() {
            if any2.0 {
                let minpos = any2.1.iter().position_min_by_key(|all1| {
                    all1.iter().filter(|&x| !hoists_chosen.contains(x)).count()
                });
                if let Some(minpos) = minpos {
                    for &ni in &any2.1[minpos] {
                        hoists_chosen.insert(ni);
                    }
                }
            }
        }
    }
    for el in cost {
        assert!(el.0.len() != 0);
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
