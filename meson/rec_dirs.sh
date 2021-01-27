#!/bin/sh

for i in $(find $1 -type d ! -name "lnInclude"); do
  echo $i
done
