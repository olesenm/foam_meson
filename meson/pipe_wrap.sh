#!/bin/bash

outpath="$1"
sourcepath="$2"
shift
shift

source "$sourcepath" #&& $@ > "$outpath"