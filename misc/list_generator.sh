#! /bin/bash

rm -f /var/www/hugo/content/posts/list.md
md_date=$(date +'%Y-%-m-%-dT%H:%M:%S-04:0')

function make_lists {
	find ~/plex/Personal/films/Collection/ -type f \
		\( -iname \*.mkv -o -iname \*.avi -o -iname \*.m4v -o -iname \*.mp4 \) \
		| sed 's/.*\///' > ~/.movie_list
	
	count=$(wc -l ~/.movie_list | cut -d " " -f 1)
}

function get_json {
	while IFS= read -r line; do
		if grep -Fx "$line" ~/.dupes; then
			echo "dupe"
		else
			python3 /usr/local/bin/guessit "$line" -j >> ~/.movies_json
			echo "$line" >> ~/.dupes
		fi
	done < ~/.movie_list
}

function movie_table {
	mapfile -t title < <(jq .title ~/.movies_json)
	mapfile -t year < <(jq .year ~/.movies_json)
	mapfile -t Source < <(jq .source ~/.movies_json)

	let numero=${#title[@]}-1

	lista_movies=$(for i in $( seq 0 $numero ); do
	        echo "${title[$i]} | ${year[$i]} | ${Source[$i]}"
	done)
	sorted=$(echo "$lista_movies" | sort -k1)
	unset numero
}

make_lists
get_json
movie_table

echo -e "---
title: \"List of films\"
date: $md_date
---
Automatically generated at $(date). This list is updated every day.

The bot is open source: [Github repository](https://github.com/vitiko123/Certified-Kino-Bot)

### Total: $count

Title | Year | Source
--- | --- | ---
$sorted

You can suggest more films via [Facebook comments](https://www.facebook.com/certifiedkino)
" > /var/www/hugo/content/posts/list.md

hugo --config="/var/www/hugo/config.toml" -s /var/www/hugo/ -d /var/www/hugo/

cp /var/www/hugo/posts/list/index.html /var/www/hugo/index.html
