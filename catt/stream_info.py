import random
from pathlib import Path

import netifaces

import youtube_dl

from .util import guess_mime


AUDIO_MODELS = [("Google Inc.", "Chromecast Audio")]
ULTRA_MODELS = [("Xiaomi", "MIBOX3"), ("Google Inc.", "Chromecast Ultra")]

BEST_MAX_2K = "best[width <=? 1920][height <=? 1080]"
BEST_MAX_4K = "best[width <=? 3840][height <=? 2160]"
BEST_ONLY_AUDIO = "bestaudio"
BEST_FALLBACK = "/best"
MAX_50FPS = "[fps <=? 50]"
TWITCH_NO_60FPS = "[format_id != 1080p60__source_][format_id != 720p60]"
MIXCLOUD_NO_DASH = "[format_id != dash-a1-x3]"
AUDIO_FORMAT = BEST_ONLY_AUDIO + MIXCLOUD_NO_DASH + BEST_FALLBACK
ULTRA_FORMAT = BEST_MAX_4K
STANDARD_FORMAT = BEST_MAX_2K + MAX_50FPS + TWITCH_NO_60FPS


class YouTubeExtractorFailedException(Exception):
    pass


class StreamInfo:
    def __init__(self, video_url, model=None):
        if "://" not in video_url:
            self._local_file = video_url
            self.local_ip = self._get_local_ip()
            self.port = random.randrange(45000, 47000)
            self.is_local_file = True
            self.is_standard_website = False
        else:
            self.is_local_file = False
            self.local_ip = None
            self.port = None
            try:
                self.is_standard_website = False
                self._ydl = youtube_dl.YoutubeDL({"quiet": True, "no_warnings": True})
                self._preinfo = self._get_stream_preinfo(video_url)
                # Some playlist urls needs to be re-processed (such as youtube channel urls).
                if self._preinfo.get("ie_key"):
                    self._preinfo = self._get_stream_preinfo(self._preinfo["url"])

                if model in AUDIO_MODELS:
                    self._best_format = AUDIO_FORMAT
                elif model in ULTRA_MODELS:
                    self._best_format = ULTRA_FORMAT
                else:
                    self._best_format = STANDARD_FORMAT

                if self.is_playlist:
                    self._entries = list(self._preinfo["entries"])
                    self._active_entry = None
                else:
                    self._info = self._get_stream_info(self._preinfo)

            except YouTubeExtractorFailedException:
                self._video_url = video_url
                self.is_standard_website = True

    @property
    def is_remote_file(self):
        return not self.is_local_file and not self.is_playlist

    @property
    def is_playlist(self):
        if self.is_standard_website:
            return False
        return not self.is_local_file and "entries" in self._preinfo

    @property
    def extractor(self):
        if self.is_standard_website:
            return None
        return self._preinfo["extractor"].split(":")[0] if not self.is_local_file else None

    @property
    def video_title(self):
        if self.is_standard_website:
            return self.video_url
        if self.is_local_file:
            return Path(self._local_file).name
        elif self.is_playlist:
            return None
        else:
            # "preinfo" does not contain a "title" key, when the user casts
            # an url that points directly to a media file.
            try:
                return self._preinfo["title"]
            except KeyError:
                return self._preinfo["webpage_url_basename"].split(".")[0]

    @property
    def video_url(self):
        if self.is_standard_website:
            return self._video_url
        if self.is_local_file:
            return "http://%s:%s/?loaded_from_catt" % (self.local_ip, self.port)
        elif self.is_playlist:
            return None
        else:
            return self._get_stream_url(self._info)

    @property
    def video_id(self):
        if self.is_standard_website:
            return self.video_url
        return self._preinfo["id"] if self.is_remote_file else None

    @property
    def video_thumbnail(self):
        if self.is_standard_website:
            return None
        return self._preinfo.get("thumbnail") if self.is_remote_file else None

    @property
    def guessed_content_type(self):
        if self.is_standard_website:
            return None
        if self.is_local_file:
            return guess_mime(self.video_title)
        elif self.is_remote_file and self._info.get("direct"):
            return guess_mime(self._info["webpage_url_basename"])
        else:
            return None

    @property
    def playlist_length(self):
        return len(self._entries) if self.is_playlist else None

    @property
    def playlist_all_ids(self):
        if self.is_playlist and self._entries and self._entries[0].get("id"):
            return [entry["id"] for entry in self._entries]
        else:
            return None

    @property
    def playlist_title(self):
        return self._preinfo["title"] if self.is_playlist else None

    @property
    def playlist_id(self):
        return self._preinfo["id"] if self.is_playlist else None

    @property
    def playlist_entry_title(self):
        return self._active_entry["title"] if self.is_playlist else None

    @property
    def playlist_entry_url(self):
        if self.is_playlist:
            return self._get_stream_url(self._get_stream_info(self._active_entry))
        else:
            return None

    @property
    def playlist_entry_id(self):
        return self._active_entry["id"] if self.is_playlist else None

    @property
    def playlist_entry_thumbnail(self):
        return self._active_entry.get("thumbnail") if self.is_playlist else None

    def set_playlist_entry(self, number):
        """
        Must be called with valid entry number
        before playlist entry properties can be accessed.
        """

        if self.is_playlist:
            # Some playlist entries needs to be re-processed.
            if self._entries[number].get("ie_key"):
                self._active_entry = self._get_stream_preinfo(self._entries[number]["url"])
            else:
                self._active_entry = self._entries[number]

    def _get_local_ip(self):
        interface = netifaces.gateways()['default'][netifaces.AF_INET][1]
        return netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['addr']

    def _get_stream_preinfo(self, video_url):
        try:
            return self._ydl.extract_info(video_url, process=False)
        except youtube_dl.utils.DownloadError:
            raise YouTubeExtractorFailedException("Remote resource not found.")

    def _get_stream_info(self, preinfo):
        try:
            return self._ydl.process_ie_result(preinfo, download=False)
        except (youtube_dl.utils.ExtractorError, youtube_dl.utils.DownloadError):
            raise YouTubeExtractorFailedException("Youtube-dl extractor failed.")

    def _get_stream_url(self, info):
        format_selector = self._ydl.build_format_selector(self._best_format)

        try:
            best_format = next(format_selector(info))
        except StopIteration:
            raise YouTubeExtractorFailedException("No suitable format was found.")
        # This is thrown when url points directly to media file.
        except KeyError:
            best_format = info

        return best_format["url"]
