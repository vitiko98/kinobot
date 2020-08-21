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
title: \"List of films & instructions\"
date: $md_date
---
Automatically generated at $(date). This list is updated every day.

If you are going to request a frame/gif, please keep in mind that:

* There are two types of requests: by **[words]** and by **[minute:second]**. Examples: *!req Taxi Driver [you talking to me?]; !req Stalker [04:01]* 
* You can request a screenshot/gif from any of the films in the list.
* You can comment the original or the english title but NOT both.
* Movies with short names may need a discriminator (the year) in order to be found. For example: *!req Her 2013 [some her quote]*
* You don't need to type the movie or the quote exactly as it is. The bot will be smart enough to find the most similar movie and quote/line.
* Your request will be ignored if the movie doesn't have subtitles available. If you want a movie without subtitles posted, use seconds instead of words (eg. *!req Duck Amuck [04:32]*)
* Quotes are in english.
* Avoid duplicates. Your request won't be ignored.

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
