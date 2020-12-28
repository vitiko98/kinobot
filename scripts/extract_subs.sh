#! /bin/bash

# This should only be used in extreme cases.
#
# We can't apply this technique to every movie; such thing would destroy
# the server (bandwith and CPU).

MOVIE="$1"
TMP_FILE="/tmp/${MOVIE##/*/}.srt"
SUBTITLE="${MOVIE/.mkv/.en.srt}"

index=$(ffprobe "$MOVIE" -v quiet -print_format json -show_format -show_streams \
	| jq '[ .streams[] | select(.codec_long_name=="SubRip subtitle") | select(.tags.language=="eng") ][0].index')

[ $index == "null" ] && echo "No index found for movie" && exit 1

echo "Found index: $index"

ffmpeg -v quiet -stats -i "$MOVIE" -map "0:${index}" "$TMP_FILE"

if [[ $(wc -l "$TMP_FILE" | cut -d " " -f 1) -ge 100 ]]
then
	echo -e "Good subtitle: $TMP_FILE \n"
	cp -v "$SUBTITLE" "${SUBTITLE}.save"
	mv -v "$TMP_FILE" "$SUBTITLE"
else
	echo "Empty subtitle. This file will be ignored"
fi
