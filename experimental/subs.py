import srt
import sys
from fuzzywuzzy import fuzz

subt = open(sys.argv[1], 'r')

subtitle_generator = srt.parse(subt)

subtitles = list(subtitle_generator)

initial = 0
List = []
for sub in subtitles:
    fuzzy = fuzz.partial_ratio(sys.argv[2], sub.content)
    if fuzzy > initial:
        initial = fuzzy
        List.append({'message': sub.content,
                     'time': sub.start, 'score': fuzzy})

print(List[-1])
