#! /bin/bash

SERVER='/var/www/hugo'
rm -f $SERVER/content/posts/list.md
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

function tv_table {
	mapfile -t title < <(jq .[].title "$1")
	mapfile -t season < <(jq .[].season "$1")
	mapfile -t episode < <(jq .[].episode "$1")

	let numero=${#title[@]}-1

	lista_epi=$(for i in $( seq 0 $numero ); do
	        echo "${title[$i]} | ${season[$i]} | ${episode[$i]}"
	done)
	count_epi=$(echo "$lista_epi" | wc -l)
}

tv_table $TV_JSON
echo -e "---
title: \"List of TV shows and episodes\"
---
Automatically generated at $(date). This list is updated every day.

The bot is open source: [Github repository](https://github.com/vitiko123/Certified-Kino-Bot)


### Total: $count_epi

> Note 1: if you want a season or tv show to be added, please let me know through Facebook comments.

> See also: [List of films](index.html)

Title | Season | Episode
--- | --- | ---
$lista_epi
" > $SERVER/content/posts/list.md
hugo --config="$SERVER/config.toml" -s "$SERVER/" -d "$SERVER/"
cp $SERVER/posts/list/index.html $SERVER/episodes.html

movie_table $MOVIE_JSON
echo -e "---
title: \"List of films & instructions\"
---
Automatically generated at $(date). This list is updated every day.

If you are going to request a frame, please keep in mind that:

* There are three types of requests: by **[words]**, by **[minute:second]** or by **[hour:minute:second]**. Examples: *!req Taxi Driver [you talking to me?]; !req Stalker [04:01]* 
* You can request a screenshot from any of the films in the list.
* You can comment the original or the english title but NOT both.
* Movies with short names may need a discriminator (the year) in order to be found. For example: *!req Yi Yi 2000 [some Yi Yi quote]*
* You don't need to type the movie or the quote exactly as it is. The bot will be smart enough to find the most similar movie and quote/line.
* Your request will be ignored if the movie doesn't have subtitles available. If you want a movie without subtitles posted, use seconds instead of words (eg. *!req Duck Amuck [04:32]*)
* Quotes are in english.
* Avoid duplicates. Your request won't be ignored.

The bot is open source: [Github repository](https://github.com/vitiko123/Certified-Kino-Bot)

### Total: $count

> Note: some elements in this list are not duplicates but movies splitted in multiple parts.

> Note 2: if you want a specific film to be added, please let me know through Facebook comments.

> See also: [List of episodes](episodes.html)

Title | Original Title | Year | Director
--- | --- | --- | ---
$lista_movies

You can suggest more films via [Facebook comments](https://www.facebook.com/certifiedkino)
" > $SERVER/content/posts/list.md
hugo --config="$SERVER/config.toml" -s "$SERVER/" -d "$SERVER/"
cp $SERVER/posts/list/index.html $SERVER/index.html
