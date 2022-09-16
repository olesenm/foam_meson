#!/bin/bash
root_path="$1"
source "$root_path/etc/bashrc"
$root_path/wmake/scripts/wmake-build-info  | sed '1d;s/ = /=/g;s/    //g;s/\n/kk/g' | tr '\n' ';' | sed 's/;/; /g;s/; $/\n/'
