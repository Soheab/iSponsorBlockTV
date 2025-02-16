from typing import Any, TypedDict

from datetime import datetime


class Thumbnail(TypedDict):
    url: str
    width: int
    height: int


class Localized(TypedDict):
    title: str
    description: str


class Snippet(TypedDict):
    publishedAt: str
    channelId: str
    title: str
    description: str
    thumbnails: dict[str, Thumbnail]
    channelTitle: str
    tags: list[str]
    categoryId: str
    liveBroadcastContent: str
    defaultLanguage: str
    localized: Localized
    defaultAudioLanguage: str


class RegionRestriction(TypedDict):
    allowed: list[str]
    blocked: list[str]


class ContentRating(TypedDict):
    acbRating: str
    agcomRating: str
    anatelRating: str
    bbfcRating: str
    bfvcRating: str
    bmukkRating: str
    catvRating: str
    catvfrRating: str
    cbfcRating: str
    cccRating: str
    cceRating: str
    chfilmRating: str
    chvrsRating: str
    cicfRating: str
    cnaRating: str
    cncRating: str
    csaRating: str
    cscfRating: str
    czfilmRating: str
    djctqRating: str
    djctqRatingReasons: list[str]
    ecbmctRating: str
    eefilmRating: str
    egfilmRating: str
    eirinRating: str
    fcbmRating: str
    fcoRating: str
    fmocRating: str
    fpbRating: str
    fpbRatingReasons: list[str]
    fskRating: str
    grfilmRating: str
    icaaRating: str
    ifcoRating: str
    ilfilmRating: str
    incaaRating: str
    kfcbRating: str
    kijkwijzerRating: str
    kmrbRating: str
    lsfRating: str
    mccaaRating: str
    mccypRating: str
    mcstRating: str
    mdaRating: str
    medietilsynetRating: str
    mekuRating: str
    mibacRating: str
    mocRating: str
    moctwRating: str
    mpaaRating: str
    mpaatRating: str
    mtrcbRating: str
    nbcRating: str
    nbcplRating: str
    nfrcRating: str
    nfvcbRating: str
    nkclvRating: str
    oflcRating: str
    pefilmRating: str
    rcnofRating: str
    resorteviolenciaRating: str
    rtcRating: str
    rteRating: str
    russiaRating: str
    skfilmRating: str
    smaisRating: str
    smsaRating: str
    tvpgRating: str
    ytRating: str


class ContentDetails(TypedDict):
    duration: str
    dimension: str
    definition: str
    caption: str
    licensedContent: bool
    regionRestriction: RegionRestriction
    contentRating: ContentRating
    projection: str
    hasCustomThumbnail: bool


class Status(TypedDict):
    uploadStatus: str
    failureReason: str
    rejectionReason: str
    privacyStatus: str
    publishAt: datetime
    license: str
    embeddable: bool
    publicStatsViewable: bool
    madeForKids: bool
    selfDeclaredMadeForKids: bool


class Statistics(TypedDict):
    viewCount: str
    likeCount: str
    dislikeCount: str
    favoriteCount: str
    commentCount: str


class PaidProductPlacementDetails(TypedDict):
    hasPaidProductPlacement: bool


class Player(TypedDict):
    embedHtml: str
    embedHeight: int
    embedWidth: int


class TopicDetails(TypedDict):
    topicIds: list[str]
    relevantTopicIds: list[str]
    topicCategories: list[str]


class RecordingDetails(TypedDict):
    recordingDate: datetime


class VideoStream(TypedDict):
    widthPixels: int
    heightPixels: int
    frameRateFps: float
    aspectRatio: float
    codec: str
    bitrateBps: int
    rotation: str
    vendor: str


class AudioStream(TypedDict):
    channelCount: int
    codec: str
    bitrateBps: int
    vendor: str


class FileDetails(TypedDict):
    fileName: str
    fileSize: int
    fileType: str
    container: str
    videoStreams: list[VideoStream]
    audioStreams: list[AudioStream]
    durationMs: int
    bitrateBps: int
    creationTime: str


class ProcessingProgress(TypedDict):
    partsTotal: int
    partsProcessed: int
    timeLeftMs: int


class ProcessingDetails(TypedDict):
    processingStatus: str
    processingProgress: ProcessingProgress
    processingFailureReason: str
    fileDetailsAvailability: str
    processingIssuesAvailability: str
    tagSuggestionsAvailability: str
    editorSuggestionsAvailability: str
    thumbnailsAvailability: str


class TagSuggestion(TypedDict):
    tag: str
    categoryRestricts: list[str]


class Suggestions(TypedDict):
    processingErrors: list[str]
    processingWarnings: list[str]
    processingHints: list[str]
    tagSuggestions: list[TagSuggestion]
    editorSuggestions: list[str]


class LiveStreamingDetails(TypedDict):
    actualStartTime: datetime
    actualEndTime: datetime
    scheduledStartTime: datetime
    scheduledEndTime: datetime
    concurrentViewers: int
    activeLiveChatId: str


class Localization(TypedDict):
    title: str
    description: str


# Example video data
example_video: dict[str, Any] = {
    "kind": "youtube#video",
    "etag": "1Vr41N5DHHEgH1LJRRsLfymxFtg",
    "id": "CULCbB18STM",
    "snippet": {
        "publishedAt": "2024-10-31T16:04:10Z",
        "channelId": "UCh8bTHe4T8o7RIU7R5EPX-w",
        "title": "WEEKENDJE WEG MET HET GEZIN ❤️ #4094 #4095 #4096",
        "description": (
            "Vorige video: https://youtu.be/EBezawFuHD0\nDeze video bevat de volgende vlogs: \n0:00 - Vlog #4094 \n32:37 - Vlog #4095  \n54:26 - Vlog #4096\n"
            "▬\nKnolpower kledinglijn ➜ www.knolpower.nl\nIk speel ook games! Die kan je hier vinden: http://bit.ly/EnzoKnolYoutube\n▬\nMijn naam is Enzo Knol en ik upload elke maandag en donderdag om 4 uur een weekvlog en elke zondag om 10 uur een extra video op mijn YouTube kanaal\nAbonneer je op mijn kanaal zodat je alles kan bekijken wat ik mee maak: http://bit.ly/AbonneerEnzoKnol\n▬\nVolg mij ook op social media: https://enzo.knolpower.nl\nBekijk de vlog afspeellijsten: https://www.youtube.com/@EnzoKnol/playlists\n▬\nEnzo Knol staat onder toezicht van het Commissariaat voor de Media.\nContact: zakelijk@knolpower.nl\n▬\n#Knolpower\nDikke vette peace ✌"
        ),
        "thumbnails": {
            "default": {
                "url": "https://i.ytimg.com/vi/CULCbB18STM/default.jpg",
                "width": 120,
                "height": 90,
            },
            "medium": {
                "url": "https://i.ytimg.com/vi/CULCbB18STM/mqdefault.jpg",
                "width": 320,
                "height": 180,
            },
            "high": {
                "url": "https://i.ytimg.com/vi/CULCbB18STM/hqdefault.jpg",
                "width": 480,
                "height": 360,
            },
            "standard": {
                "url": "https://i.ytimg.com/vi/CULCbB18STM/sddefault.jpg",
                "width": 640,
                "height": 480,
            },
            "maxres": {
                "url": "https://i.ytimg.com/vi/CULCbB18STM/maxresdefault.jpg",
                "width": 1280,
                "height": 720,
            },
        },
        "channelTitle": "EnzoKnol",
        "tags": [
            "enzoknol",
            "enzo knol",
            "enzoknol vlog",
            "enzoknol minecraft",
            "enzo",
            "dee",
            "knol",
            "HD",
            "NL",
            "bumper",
            "vlog",
            "knolpower",
            "minecraft enzoknol",
            "enzoknol minigames",
            "minecraft survival enzoknol",
            "entertainment",
            "voor kinderen",
            "kinderen",
            "2020",
            "myron",
            "enzo myron",
            "myron enzo",
        ],
        "categoryId": "24",
        "liveBroadcastContent": "none",
        "localized": {
            "title": "WEEKENDJE WEG MET HET GEZIN ❤️ #4094 #4095 #4096",
            "description": (
                "Vorige video: https://youtu.be/EBezawFuHD0\nDeze video bevat de volgende vlogs: \n0:00 - Vlog #4094 "
                "\n32:37 - "
                "Vlog #4095  \n54:26 - Vlog #4096\n"
                "▬\nKnolpower kledinglijn ➜ www.knolpower.nl\nIk speel ook games! Die kan je hier vinden: "
                "http://bit.ly/EnzoKnolYoutube\n▬\nMijn naam is Enzo Knol en ik upload elke maandag en donderdag om 4 uur "
                "een weekvlog en elke zondag om 10 uur een extra video op mijn YouTube kanaal\nAbonneer je op mijn kanaal "
                "zodat je alles kan bekijken wat ik mee maak: http://bit.ly/AbonneerEnzoKnol\n▬\nVolg mij ook op social "
                "media: https://enzo.knolpower.nl\nBekijk de vlog afspeellijsten: https://www.youtube.com/@EnzoKnol/playlists"
                "\n▬\nEnzo Knol staat onder toezicht van het Commissariaat voor de Media.\nContact: zakelijk@knolpower.nl\n▬"
                "\n#Knolpower\nDikke vette peace ✌"
            ),
        },
    },
    "contentDetails": {
        "duration": "PT1H11M58S",
        "dimension": "2d",
        "definition": "hd",
        "caption": "false",
        "licensedContent": True,
        "contentRating": {},
        "projection": "rectangular",
    },
    "statistics": {
        "viewCount": "240821",
        "likeCount": "5156",
        "favoriteCount": "0",
        "commentCount": "392",
    },
}


class Video(TypedDict):
    kind: str
    etag: str
    id: str
    snippet: Snippet
    contentDetails: ContentDetails
    status: Status
    statistics: Statistics
    paidProductPlacementDetails: PaidProductPlacementDetails
    player: Player
    topicDetails: TopicDetails
    recordingDetails: RecordingDetails
    fileDetails: FileDetails
    processingDetails: ProcessingDetails
    suggestions: Suggestions
    liveStreamingDetails: LiveStreamingDetails
    localizations: dict[str, Localization]


class VideoListResponsePageInfo(TypedDict):
    totalResults: int
    resultsPerPage: int


class VideoListResponse(TypedDict):
    kind: str
    etag: str
    nextPageToken: str
    prevPageToken: str
    pageInfo: VideoListResponsePageInfo
    items: list[Video]
