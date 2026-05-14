from .base import Mode
from .solid import SolidMode
from .pulse import PulseMode
from .strobe import StrobeMode

MODES: dict[str, type[Mode]] = {
    "solid": SolidMode,
    "pulse": PulseMode,
    "strobe": StrobeMode,
}
