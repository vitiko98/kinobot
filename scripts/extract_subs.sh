#! /bin/bash

# This should only be used in extreme cases.
#
# We can't apply this technique to every movie; such thing would destroy
# the server (bandwith and CPU).

MOVIE="$1"
TMP_FILE="/tmp/${MOVIE##/*/}.srt"
SUBTITLE="${MOVIE/.mkv/.en.srt}"
LOGFILE=$HOME/.extracted_subs.log 

if grep -q "$MOVIE" $LOGFILE
then
	echo "Duplicate" && exit 1
fi

index=$(ffprobe "$MOVIE" -v quiet -print_format json -show_format -show_streams \
	| jq '[ .streams[] | select(.codec_long_name=="SubRip subtitle") | select(.tags.language=="eng") ][0].index')

[ $index == "null" ] && echo "No index found for movie" && exit 1

echo "Found index: $index"

ffmpeg -v quiet -stats -i "$MOVIE" -map "0:${index}" "$TMP_FILE"

if [[ $(wc -l "$TMP_FILE" | cut -d " " -f 1) -ge 100 ]]
then
	echo -e "Apparently good subtitle: "$TMP_FILE" \n"
	if [[ $(egrep -c '^[[:upper:]]+$' "$TMP_FILE") -ge 10 ]] || [[ $(grep -c "\[" "$TMP_FILE") -ge 5 ]]
	then
		echo "Possible HI subtitle. This file will be ignored"
	else
		cp -v "$SUBTITLE" "${SUBTITLE}.save"
		mv -v $TMP_FILE "$SUBTITLE"
	fi
else
	echo "Empty subtitle. This file will be ignored"
fi

echo "$MOVIE" >> $LOGFILE
