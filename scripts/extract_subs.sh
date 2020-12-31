#! /bin/bash

# We can't apply this technique to every movie; such thing would destroy
# the server (bandwith and CPU).

update_movie () {
	sqlite3 $KINOBASE <<-EOF
	update movies set og_sub=1 where path="$1";
	EOF
	echo -e "$1\n$2" >> $LOGFILE
}

if [[ -z $1 ]]
then
	MOVIE=$(sqlite3 $KINOBASE "select path from movies where cast(popularity as Integer) > 15 and og_sub=0 limit 1;")
else
	MOVIE="$1"
fi

MOVIE_SIZE=$(stat --printf="%s" "$MOVIE")
TMP_FILE="/tmp/${MOVIE##/*/}.srt"
SUBTITLE="${MOVIE/.mkv/.en.srt}"
LOGFILE=$HOME/.extracted_subs.log 

echo "Movie path: $MOVIE [$KINOBASE]"

if grep -q -e "$MOVIE_SIZE" -e "$MOVIE" $LOGFILE
then
	echo "Duplicate" && update_movie "$MOVIE" "$MOVIE_SIZE" && exit 1
fi

index=$(ffprobe "$MOVIE" -v quiet -print_format json -show_format -show_streams \
	| jq '[ .streams[] | select(.codec_long_name|test("SubRip";"i")) | select(.tags.language|test("en")) ][0].index')

[ $index == "null" ] && echo "No index found for movie" && update_movie "$MOVIE" "$MOVIE_SIZE" && exit 1

echo "Found index: $index"

ffmpeg -y -v quiet -stats -i "$MOVIE" -map "0:${index}" "$TMP_FILE"

if [[ $(wc -l "$TMP_FILE" | cut -d " " -f 1) -ge 100 ]]
then
	echo -e "Apparently good subtitle: "$TMP_FILE" \n"
	if [[ $(egrep -c '^[[:upper:]]+$' "$TMP_FILE") -ge 10 ]] || [[ $(grep -c "\[" "$TMP_FILE") -ge 5 ]]
	then
		echo "Possible HI subtitle. This file will be ignored"
	else
		cp -v "$SUBTITLE" "${SUBTITLE}.save"
		mv -v "$TMP_FILE" "$SUBTITLE"
	fi
else
	echo "Empty subtitle. This file will be ignored"
fi

update_movie "$MOVIE" "$MOVIE_SIZE"
