#!/bin/sh

for i in $(find $1 -name '*.[CH]' ! -path '*lnInclude*'); do
  echo $i
done
