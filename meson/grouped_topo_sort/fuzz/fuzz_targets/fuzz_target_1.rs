#![no_main]
use libfuzzer_sys::fuzz_target;
use std::collections::HashSet;

use mylib::fixer::*;
use mylib::front_end_input::*;
use mylib::*;

fuzz_target!(|input: Vec<fuzz_input::FuzzInput>| {
    let data = input
        .iter()
        .enumerate()
        .map(|(i, x)| ImportedTarget {
            provides: format!("{}", i),
            ddeps: x.ddeps.iter().map(|y| format!("{}", y)).collect::<Vec<_>>(),
            ideal_path: x
                .ideal_path
                .iter()
                .map(|y| format!("{}", y))
                .collect::<Vec<_>>(),
        })
        .collect::<Vec<_>>();

    let used = data
        .iter()
        .map(|x| x.ddeps.clone())
        .flatten()
        .collect::<HashSet<_>>();

    let data = data
        .into_iter()
        .filter(|x| x.ddeps.len() != 0 || used.contains(&x.provides))
        .collect::<Vec<_>>();

    let mut owner = Vec::new();
    if let Ok((mut deps, mut tree)) = inner_parse(&mut owner, data) {
        dbg!(&deps.graph, &tree);
        let mut hoists = Vec::new();
        find_all_hoists_needed(&mut hoists, &deps, &tree, vec![]);
        execute_hoists(&mut deps, &mut tree, &hoists);
        dbg!(&hoists, &deps.graph, &tree);
        assert_toposort_possible(&deps, &tree);
    }
});
