#! /bin/bash

## USAGE: ./list_generator.sh JSON.json

rm -f /var/www/hugo/content/posts/list.md
md_date=$(date +'%Y-%-m-%-dT%H:%M:%S-04:0')


function movie_table {
	mapfile -t title < <(jq .[].title "$1")
	mapfile -t year < <(jq .[].year "$1")
	mapfile -t original < <(jq .[].original_title "$1")
	mapfile -t director < <(jq '.[]."director(s)"' "$1")

	let numero=${#title[@]}-1

	lista_movies=$(for i in $( seq 0 $numero ); do
	        echo "${title[$i]} | ${original[$i]} | ${year[$i]} | ${director[$i]}"
	done)
	count=$(echo "$lista_movies" | wc -l)
}

movie_table $1

echo -e "---
title: \"List of films\"
date: $md_date
---
Automatically generated at $(date). This list is updated every day.

The bot is open source: [Github repository](https://github.com/vitiko123/Certified-Kino-Bot)

### Total: $count

> Note: some elements in this list are not duplicates but movies splitted in multiple parts.

Title | Original Title | Year | Director
--- | --- | --- | ---
$lista_movies

You can suggest more films via [Facebook comments](https://www.facebook.com/certifiedkino)
" > /var/www/hugo/content/posts/list.md

hugo --config="/var/www/hugo/config.toml" -s /var/www/hugo/ -d /var/www/hugo/

cp /var/www/hugo/posts/list/index.html /var/www/hugo/index.html
