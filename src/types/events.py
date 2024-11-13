from typing import Literal, NotRequired, TypedDict


__all__ = (
    "DeviceInfo",
    "Device",
    "LoungeStatus",
    "SubtitleStyle",
    "VideoData",
    "OnStateChange",
    "PartialNotPlaying",
    "NowPlaying",
    "VolumeChanged",
    "OAutoplayModeChanged",
    "OnHasPreviousNextChanged",
    "PlaylistModified",
    "KnownEventsStr",
    "KnownEventPayload",
)

class DeviceInfo(TypedDict):
    brand: str
    model: str
    year: int
    os: str
    osVersion: str
    chipset: str
    clientName: str
    dialAdditionalDataSupportLevel: Literal["full", "none", "partial"]
    mdxDialServerType: Literal[
        "MDX_DIAL_SERVER_TYPE_IN_APP", "MDX_DIAL_SERVER_TYPE_EXTERNAL"
    ]


class Device(TypedDict):
    app: str
    capabilities: str
    clientName: str
    experiments: str
    name: str
    theme: str
    id: str
    type: str
    hasCc: NotRequired[str]
    deviceInfo: NotRequired[str] # DeviceInfo
    receiverIdentityMatchStatus: str
    pairingType: NotRequired[str]
    deviceContext: NotRequired[str]
    localChannelEncryptionKey: NotRequired[str]


class LoungeStatus(TypedDict):
    queueId: str
    devices: str  # List[Device]


class SubtitleStyle(TypedDict):
    background: str
    backgroundOpacity: float
    charEdgeStyle: str
    color: str
    fontFamily: int
    fontSizeIncrement: int
    fontStyle: int
    textOpacity: float
    windowColor: str
    windowOpacity: float
    backgroundOverride: bool
    backgroundOpacityOverride: bool
    charEdgeStyleOverride: bool
    colorOverride: bool
    fontFamilyOverride: bool
    fontSizeIncrementOverride: bool
    textOpacityOverride: bool
    windowColorOverride: bool
    windowOpacityOverride: bool
    fontFamilyOption: str


class VideoData(TypedDict):
    videoId: str
    style: SubtitleStyle


class OnStateChange(TypedDict):
    currentTime: str
    duration: str
    cpn: str
    loadedTime: str
    state: Literal["0", "1", "2", "3"]
    seekableStartTime: str
    seekableEndTime: str


class PartialNotPlaying(TypedDict):
    listId: str


class NowPlaying(PartialNotPlaying):
    duration: str
    currentTime: str
    cpn: str
    loadedTime: str
    videoId: str
    state: str
    params: str
    seekableEndTime: str
    seekableStartTime: str


class VolumeChanged(TypedDict):
    volume: str
    muted: str


class OAutoplayModeChanged(TypedDict):
    autoplayMode: Literal["ENABLED", "DISABLED"]


class OnHasPreviousNextChanged(TypedDict):
    hasPrevious: Literal["true", "false"]
    hasNext: Literal["true", "false"]


class PlaylistModified(TypedDict):
    listId: str
    firstVideoId: str



KnownEventsStr = Literal[
    "onStateChange",
    "nowPlaying",
    "onAdStateChange",
    "onVolumeChanged",
    "onAutoplayModeChanged",
    "onSubtitlesTrackChanged",
    "loungeScreenDisconnected",
    "loungeStatus",
    "autoplayUpNext",
    "adPlaying",
]

KnownEventPayload = (
    NowPlaying
    | OnStateChange
    | PartialNotPlaying
    | VolumeChanged
    | OAutoplayModeChanged
    | OnHasPreviousNextChanged
    | PlaylistModified
    | LoungeStatus
    | VideoData
)
