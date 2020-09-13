#! /bin/bash

mapfile -t this < <(convert $1 -colors 10 -unique-colors txt:- | tail -n +2 | sed -n 's/^.*\#.* \(.*\).*$/xc\:\1/p')

for i in "${this[@]}"; do
	echo "$i" | cut -d "(" -f2 | cut -d ")" -f1
done
