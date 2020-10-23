#! /bin/bash 

# DEPRECATED

MOVIE_SUBTITLES=$HOME/subtitles
TV_SUBTITLES=$HOME/subtitles/shows

function find_subtitle {
	video="$1"
	discriminator="$2"
	name=$(echo "${video%.*}" | sed "s/.*\///")

	if [ ! -e "$discriminator/$name.en.srt" ]; then
		subliminal --opensubtitles averroista $OPEN_PWD \
			download "$video" -l en -f -d $discriminator -e 'UTF-8'
	else
		echo "$name already exists"
	fi
	}

mapfile -t films < <(find $FILM_COLLECTION -name '*.mp4' -o -name '*.mkv' -o -name '*.avi')
mapfile -t tv < <(find $TV_COLLECTION -name '*.mp4' -o -name '*.mkv' -o -name '*.avi')

for i in "${films[@]}"; do
	find_subtitle "$i" $MOVIE_SUBTITLES
done

for i in "${tv[@]}"; do
	find_subtitle "$i" $TV_SUBTITLES
done
