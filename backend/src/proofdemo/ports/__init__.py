"""Application-owned ports implemented by infrastructure adapters."""

from proofdemo.ports.audio import (
    AudioInfo,
    AudioMixCue,
    AudioMixError,
    AudioMixPort,
    AudioUnavailableError,
)
from proofdemo.ports.browser import (
    AppStateObservation,
    BrowserActionError,
    BrowserLogEntry,
    BrowserPort,
    BrowserSessionArtifacts,
    BrowserUnavailableError,
    DownloadObservation,
)
from proofdemo.ports.partial_render import PartialRenderPort, VideoSegment
from proofdemo.ports.planner import (
    PlannerCandidate,
    PlannerPort,
    PlannerResponseError,
    PlannerUnavailableError,
)
from proofdemo.ports.render import (
    MediaInfo,
    RenderFailedError,
    RenderPort,
    RenderSettings,
    RenderUnavailableError,
)
from proofdemo.ports.repair import (
    RepairCandidate,
    RepairPort,
    RepairResponseError,
    RepairUnavailableError,
)
from proofdemo.ports.speech import (
    SpeechDescriptor,
    SpeechPort,
    SpeechSynthesisError,
    SpeechUnavailableError,
)

__all__ = [
    "AppStateObservation",
    "AudioInfo",
    "AudioMixCue",
    "AudioMixError",
    "AudioMixPort",
    "AudioUnavailableError",
    "BrowserActionError",
    "BrowserLogEntry",
    "BrowserPort",
    "BrowserSessionArtifacts",
    "BrowserUnavailableError",
    "DownloadObservation",
    "MediaInfo",
    "PartialRenderPort",
    "PlannerCandidate",
    "PlannerPort",
    "PlannerResponseError",
    "PlannerUnavailableError",
    "RenderFailedError",
    "RenderPort",
    "RenderSettings",
    "RenderUnavailableError",
    "RepairCandidate",
    "RepairPort",
    "RepairResponseError",
    "RepairUnavailableError",
    "SpeechDescriptor",
    "SpeechPort",
    "SpeechSynthesisError",
    "SpeechUnavailableError",
    "VideoSegment",
]
