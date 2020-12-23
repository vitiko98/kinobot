#! /bin/bash

convert $1 -colors 10 -unique-colors txt:- | tail -n +2 \
	| sed -n 's/^.*\#.* \(.*\).*$/xc\:\1/p' | cut \
	-d "(" -f2 | cut -d ")" -f1
