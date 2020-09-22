#! /bin/bash

SERVER='/var/www/hugo'
rm -f $SERVER/content/posts/list.md
md_date=$(date +'%Y-%-m-%-dT%H:%M:%S-04:0')

function movie_table {
	mapfile -t title < <(jq -r .[].title "$1")
	mapfile -t year < <(jq .[].year "$1")
	mapfile -t original < <(jq .[].original_title "$1")
	mapfile -t director < <(jq '.[]."director(s)"' "$1")
	mapfile -t subs < <(jq -r .[].subtitle "$1")

	let length=${#title[@]}-1
	mapfile -t subtitles < <(for i in $( seq 0 $length ); do
		sanitized_title="${title[i]//[^a-zA-Z0-9]/}.txt"
		final="${SERVER}/subtitles/${sanitized_title}"
		if [ -e "${subs[i]}" ]; then 
			cat "${subs[i]}" > "${final}"
		else
			echo "NULL" > "${final}"
		fi
		echo "subtitles/${sanitized_title}"
		done)

	let numero=${#title[@]}-1
	lista_movies=$(for i in $( seq 0 $numero ); do
	        echo "${title[$i]} | ${original[$i]} | ${year[$i]} | [Subtitles](${subtitles[$i]}) | ${director[$i]}"
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

**Kinobot** is really flexible and powerful. You can make beautiful posts by just having a decent taste in cinema.

If you are going to request a frame, please keep in mind that:

* There are three types of requests: by **[words]**, by **[minute:second]** and by **[hour:minute:second]**. Examples: *!req Taxi Driver [you talking to me?]; !req Stalker [04:01]; !req The Wire s05e10 [1:01:30]* 
* You can also request more than one minute/quote (eg. *!req Uncut Gems [10:20] ['holy shit im gonna cum] [60:23]*)
* Likewise, if you request a single quote the bot will try to detect its context. This means that it will generate as many frames as necessary.
* You can comment the original or the english title but NOT both.
* Movies with short names may need a discriminator (the year) in order to be found (eg. *!req Yi Yi 2000 [some Yi Yi quote]*)
* You don't need to type the movie or the quote exactly as it is: the bot will be smart enough to find the most similar movie and quote/line.
* Quotes are in english.
* You'll be blocked if your requests are redundant (eg. if you request Pulp Fiction more than three times).

The bot is open source: [Github repository](https://github.com/vitiko123/Certified-Kino-Bot)

### Total: $count
> Tip: Check the film's subtitle url to improve the request accuracy

> Note: some elements in this list are not duplicates but movies splitted in multiple parts.

> Note 2: if you want a specific film to be added, please let me know through Facebook comments.

> See also: [List of episodes](episodes.html)

Title | Original Title | Year | Subtitles | Director
--- | --- | --- | --- | ---
$lista_movies

You can suggest more films via [Facebook comments](https://www.facebook.com/certifiedkino)
" > $SERVER/content/posts/list.md
hugo --config="$SERVER/config.toml" -s "$SERVER/" -d "$SERVER/"
cp $SERVER/posts/list/index.html $SERVER/index.html
