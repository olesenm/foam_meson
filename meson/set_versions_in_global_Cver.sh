#!/bin/sh

set -e
#cd "${0%/*}" || exit                            # Run from this directory

source $1
wmake/scripts/wmake-build-info -update -filter $2 > $3