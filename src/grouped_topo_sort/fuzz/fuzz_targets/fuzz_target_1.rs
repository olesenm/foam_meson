#![no_main]
use libfuzzer_sys::fuzz_target;
use std::collections::HashSet;

use mylib::fixer::*;
use mylib::front_end_input::*;
use mylib::*;

fn simplify(data: ImportedData) -> ImportedData {
    let used = data
        .iter()
        .map(|x| x.ddeps.clone())
        .flatten()
        .collect::<HashSet<_>>();

    let mut data = data
        .into_iter()
        .filter(|x| x.ddeps.len() != 0 || used.contains(&x.provides))
        .collect::<Vec<_>>();

    for x in data.iter_mut() {
        x.ddeps.dedup();
    }

    data
}

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

    // let mut data = simplify(data);
    // let blacklist = [
    //     "255", "189", "177", "163", "156", "121", "91", "75", "66", "63", "43", "40", "36", "34",
    //     "32", "31", "30", "29", "28", "26", "25", "24", "22", "20", "19", "18", "17", "16", "14",
    //     "12", "9", "6", "4", "1",
    // ];
    // data.retain(|x| !blacklist.contains(&x.provides.as_str()));
    // for x in data.iter_mut() {
    //     x.ddeps.retain(|x| !blacklist.contains(&x.as_str()));
    // }

    let mut owner = Vec::new();
    if let Ok((mut deps, mut tree)) = inner_parse(&mut owner, data) {
        let mut hoists = Vec::new();
        find_all_hoists_needed(&mut hoists, &deps, &tree, vec![]);
        execute_hoists(&mut deps, &mut tree, &hoists);
        assert_toposort_possible(&deps, &tree);
    }
});
