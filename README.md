# kinobot
See it in action: [Kinobot (aka Certified Kino Bot)](https://www.facebook.com/certifiedkino/)

Website: https://kino.caretas.club

![alt text](result.png)

## Features
* Search quotes
* Search frames
* Capture quotes and frames
* Detect contextual quotes
* Generate gifs
* Generate beautiful color palettes
* Handle Facebook comments as requests
* Discover movies through keywords
* Get film/episode information
* Find the most "colorful" frame
* And a lot more

## API
```python
from kinobot.frame import cv2_to_pil, fix_frame, get_frame_from_movie
from kinobot.palette import get_palette

movie = "some_movie.mkv"

# Extract a frame from some movie
frame = get_frame_from_movie(movie, second=400, microsecond=0)

# Prettify the frame with kinobot's superpowers
frame = fix_frame(movie, frame)

# Convert the image to a PIL object and add a palette
pil_image = cv2_to_pil(frame)

palette = get_palette(pil_image)

palette.save("palette_test.png")
```

## Fundamental history
### June 17, 2020
Page creation
### Aug 05, 2020
Massive rewrite in Python
### Aug 16, 2020
Implementation of requests system
### Dec 21, 2020
Massive code refactoring
