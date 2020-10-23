#! /bin/bash

SERVER='/var/www/hugo'
STATIC="$HOME/kinoweb"
SUBTILES="$HOME/subs"

rm -f $SERVER/content/posts/list.md
md_date=$(date +'%Y-%-m-%-dT%H:%M:%S-04:0')

function movie_table {
	mapfile -t title < <(jq -r .[].title "$1")
	mapfile -t year < <(jq .[].year "$1")
	mapfile -t original < <(jq -r .[].original_title "$1")
	mapfile -t subs < <(jq -r .[].subtitle "$1")
	mapfile -t director < <(jq -r .[].director "$1")
	mapfile -t country < <(jq -r .[].country "$1")
	length=${#title[@]} 

	mapfile -t subtitles < <(for i in $( seq 0 $length ); do
		sanitized_title="${title[i]//[^a-zA-Z0-9]/}.txt"
		cleaned=$(echo "${subs[i]}" | cut -d'/' -f6-)
		sub_file="$SUBTILES/$cleaned"
		final="${SERVER}/subtitles/${sanitized_title}"
		if [ -e "$sub_file" ]; then 
			cat "$sub_file" > "${final}"
		else
			echo "NULL" > "${final}"
		fi
		echo "subtitles/${sanitized_title}"
		done)

	let numero=${#title[@]}-1
	lista_movies=$(for i in $( seq 0 $numero ); do
	        echo "${title[$i]} | ${original[$i]} | ${year[$i]} | [Subtitles](${subtitles[$i]}) | ${director[$i]} | ${country[$i]}"
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


movie_table $MOVIE_JSON
echo -e "---
title: \"List of films & instructions\"
anchor: "introduction"
weight: 25
---
**Kinobot** is developed and maintained by **Vitiko**. The source code is completely open: [Github repository](https://github.com/vitiko123/Certified-Kino-Bot).

**Kinobot** is really flexible and powerful. You can make beautiful posts by just having a decent taste in cinema (jk, you can have shit taste and make beautiful posts too).

Some tips before making a request:

* There are three types of requests: by **[words]**, by **[minute:second]** and by **[hour:minute:second]**. Examples: *!req Taxi Driver 1976 [you talking to me?]; !req Stalker [04:01]; !req Vagabond [1:01:30]* 
* You can also request more than one minute/quote (eg. *!req Uncut Gems [10:20] ['holy shit im gonna cum] [60:23]*)
* Likewise, if you request a single quote, the bot will try to **detect its context**. This means that it will generate as many frames as necessary. (This function doesn't apply for multiple requests)
* You can request with the original or the english title but NOT both
* You don't need to type the movie or the quote exactly as it is: the bot will be smart enough to find the most similar movie and quote/line
* If you want a specific film to be added, [please let me know](https://forms.gle/y3fg7htZ9ouNFwsv9)


### Total: $count
> **Check the film's subtitle url to improve the request accuracy**

Title | Original Title | Year | Subtitles | Director | Country
--- | --- | --- | --- | --- | ---
$lista_movies

You can suggest more films via [Facebook comments](https://www.facebook.com/certifiedkino)
" > $STATIC/content/_index.md 
cd $STATIC
hugo -D
cp -r public/* $SERVER/ -v
cd
