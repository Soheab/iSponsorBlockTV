from __future__ import annotations
from typing import TYPE_CHECKING

from enum import Enum
import time
import datetime

if TYPE_CHECKING:
    from .types.events import NowPlaying, OnStateChange

__all__ = ("CurrentVideo",)


class VideoState(Enum):
    START_PLAYING = "-1"  # ?
    STOPPED = "0"
    PLAYING = "1"
    PAUSED = "2"
    BUFFERING = "3"  # ?


class CurrentVideo:
    def __init__(
        self,
        data: NowPlaying | OnStateChange,
    ) -> None:
        self._update(data)

    def __repr__(self) -> str:
        return (
            f"<CurrentVideo video_id={self.video_id} state={self.state.name}"
            f" current_time={self.current_time_str} duration={self.duration_str}>"
        )

    def _update(self, data: NowPlaying | OnStateChange) -> None:
        self.data = data
        self.video_id = data.get("videoId", None)

        self.current_time: float = float(data["currentTime"])
        self.duration: float = float(data["duration"])
        self.loaded_time: float = float(data["loadedTime"])
        self.state: VideoState = VideoState(data["state"])
        self.seekable_start_time: float = float(data["seekableStartTime"])
        self.seekable_end_time: float = float(data["seekableEndTime"])

        self.dt_current_time: datetime.timedelta = datetime.timedelta(seconds=self.current_time)
        self.dt_duration: datetime.timedelta = datetime.timedelta(seconds=self.duration)
        self.dt_seekable_start_time: datetime.timedelta = datetime.timedelta(seconds=self.seekable_start_time)
        self.dt_seekable_end_time: datetime.timedelta = datetime.timedelta(seconds=self.seekable_end_time)

        self.timer = time.time()

    def progress_bar(self, length: int = 30, fill_char: str = "█", empty_char: str = "░") -> str:
        """Generate a progress bar for the current video.

        Parameters
        ----------
        length : int, optional
            The total length of the progress bar (default is 30).
        fill_char : str, optional
            The character used to represent the filled portion of the bar (default is "█").
        empty_char : str, optional
            The character used to represent the empty portion of the bar (default is "░").

        Returns
        -------
        str
            A string representation of the progress bar with current and end time.
        """
        if self.duration == 0:
            fill = length
        else:
            fill = int((self.current_time / self.duration) * length)
            fill = min(fill, length)

        current_time = self.format_time(self.current_time, show_milliseconds=False)
        end_time = self.format_time(self.duration, show_milliseconds=False)
        bar = f"[{fill_char * fill}{empty_char * (length - fill)}]"
        return f"{current_time} {bar} {end_time}"

    @property
    def has_ended(self) -> bool:
        elapsed_time = time.time() - self.timer
        return self.state == VideoState.STOPPED or (self.current_time + elapsed_time) >= self.duration

    def format_time(self, seconds: float, show_milliseconds: bool = True) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        seconds = int(seconds)

        if hours > 0:
            time_str = f"{int(hours)}:{int(minutes):02}:{seconds:02}"
        elif minutes > 0:
            time_str = f"{int(minutes)}:{seconds:02}"
        else:
            time_str = f"{seconds}"

        if show_milliseconds:
            time_str += f".{milliseconds:03}".rstrip("0").rstrip(".")

        return time_str

    def to_struct_time(self, seconds: float) -> time.struct_time:
        return time.gmtime(seconds)

    @property
    def remaining_time(self) -> str:
        return self.format_time(self.duration - self.current_time)

    @property
    def remaining_time_using_dt(self) -> str:
        return str(self.dt_duration - self.dt_current_time)

    @property
    def current_time_using_dt(self) -> str:
        return str(self.dt_current_time)

    @property
    def current_time_str(self) -> str:
        return self.format_time(self.current_time)

    @property
    def duration_str(self) -> str:
        return self.format_time(self.duration)

    @property
    def seekable_start_time_str(self) -> str:
        return self.format_time(self.seekable_start_time)

    @property
    def seekable_end_time_str(self) -> str:
        return self.format_time(self.seekable_end_time)

    @property
    def loaded_time_str(self) -> str:
        return self.format_time(self.loaded_time)
