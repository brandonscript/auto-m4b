AUDIO_EXTS = [".mp3", ".m4a", ".m4b", ".aac", ".wma"]
# Sidecar / folder cover images we will discover. Formats outside JPEG/PNG are
# normalized to JPEG before mutagen/ffmpeg embedding (containers only accept those).
IMAGE_EXTS = [
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".png",
    ".apng",
    ".webp",
    ".avif",
    ".avifs",
    ".heic",
    ".heif",
    ".gif",
    ".bmp",
    ".dib",
    ".tif",
    ".tiff",
    ".jp2",
    ".j2k",
    ".jpf",
    ".jpx",
]
# Codecs ffprobe may report for attached_pic / cover streams.
COVER_STREAM_CODECS = frozenset({"mjpeg", "png", "webp", "bmp", "gif"})
OTHER_EXTS = [
    *IMAGE_EXTS,
    ".svg",
    ".epub",
    ".mobi",
    ".azw",
    ".pdf",
    ".txt",
    ".log",
]
DEFAULT_SLEEP_TIME: float = 10
DEFAULT_WAIT_TIME: float = 5
IGNORE_FILES = [
    ".DS_Store",
    "._*",
    ".AppleDouble",
    ".LSOverride",
    ".Spotlight-V100",
    ".Trashes",
    "__MACOSX",
    "Desktop.ini",
    "ehthumbs.db",
    "Thumbs.db",
    "@eaDir",
]
WORKING_DIRS = [
    "BUILD_FOLDER",
    "MERGE_FOLDER",
    "TRASH_FOLDER",
]
