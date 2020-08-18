import glob
import time
import os

class Scan:
    def __init__(self, collectionPath):
        self.collectionPath = collectionPath
        self.extensions = ['*.mkv', '*.mp4', '*.avi']
        self.Collection = []
        self.collectionSize = 0
        self.date = time.strftime("%H:%M:%S -04", time.localtime())
        # scan directory
        for movies in self.extensions:
            for movie in (glob.iglob((self.collectionPath + movies),
                                     recursive=True)):
                self.Collection.append(movie)

        # get directory size (TB)
        for entry in os.scandir(self.collectionPath):
            if entry.is_file():
                self.collectionSize += entry.stat().st_size
            elif entry.is_dir():
                self.collectionSize += folder_size(entry.path)

        self.collectionSize = '%.3f' % (self.collectionSize/float(1<<40))

    def getFootnote(self, prob):
        return ('Automatically executed at {}; collected films: {} [{} TB]'
                '; probability: {}%\n \nThis bot is open source: '
                'https://github.com/vitiko98/'
                'Certified-Kino-Bot').format(self.date, len(self.Collection),
                                             self.collectionSize,
                                             prob)
