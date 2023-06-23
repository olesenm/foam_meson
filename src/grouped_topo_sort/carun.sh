#!/usr/bin/env bash
set -e
cargo build --release

cat ../../data.json | target/release/grouped_topo_sort

exit 0

target/release/grouped_topo_sort << EOM
[
    {
        "provides": "foo",
        "ddeps": ["bar", "other"],
        "ideal_path": ["top", "midShared", "bottom"]
    },
    {
        "provides": "bar",
        "ddeps": [],
        "ideal_path": ["top", "midShared"]
    },
    {
        "provides": "other",
        "ddeps": ["bar"],
        "ideal_path": ["top", "midOther"]
    }
]
EOM
