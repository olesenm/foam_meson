use std::collections::HashSet;

use enum_as_inner::EnumAsInner;
use itertools::Itertools;
type NodeIndex = petgraph::stable_graph::NodeIndex<petgraph::stable_graph::DefaultIx>;

/// HoistsNeeded indicates which nodes need to be hoisted.
#[derive(Debug, Clone, EnumAsInner)]
pub enum HoistsNeeded {
    /// The Node given by the NodeIndex needs to be hoisted.
    Single(NodeIndex),
    /// Hoisting any one of the vector elements is sufficient.
    Any(Vec<HoistsNeeded>),
    /// All elements of the vector need to be hoisted.
    All(Vec<HoistsNeeded>),
}

/// I experimented with different integer lengths, but it made no real impact, so I just set it to usize.
pub type FastInt = usize;

/// A more complex, uglier and more restrictive, but faster data-format of `HoistsNeeded`.
/// The boolean indicates if the `[Vec<FastInt>; 2]` is "disabled", i.e. it should be ignored. Afaik, this "disabling" is faster than removing elements from the vec.
#[derive(Debug, Clone)]
pub struct FastHN(pub Vec<(bool, [Vec<FastInt>; 2])>);

impl FastHN {
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

fn count_occurences(node_count: usize, cost: &Vec<&mut FastHN>) -> Vec<usize> {
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

fn disable_solved_problems(cost: &mut Vec<&mut FastHN>, node: FastInt) {
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
    mut cost: Vec<&mut FastHN>,
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
        assert!(!el.0.is_empty());
    }
    hoists_chosen
}
