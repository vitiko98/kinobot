import exiftool
import sys

def get_aspect(file):
    with exiftool.ExifTool() as et:
        meta = et.get_metadata(file)
        print(meta)
        try:
            return (meta['Matroska:DisplayWidth'], meta['Matroska:DisplayHeight'])
        except KeyError:
            try:
                return (meta['File:DisplayWidth'], meta['File:DisplayHeight'])
            except KeyError:
                return (meta['QuickTime:SourceImageWidth'], meta['QuickTime:SourceImageHeight'])


print(get_aspect(sys.argv[1]))
