#!/bin/sh

for i in $(find $1 -name '*.C' ! -path '*lnInclude*'); do
  echo $i
done
