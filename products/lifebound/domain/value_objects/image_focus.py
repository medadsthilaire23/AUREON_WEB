from enum import Enum

class ImageFocus(Enum):
    TOP    = "top"
    CENTER = "center"
    BOTTOM = "bottom"
    LEFT   = "left"
    RIGHT  = "right"

    @classmethod
    def from_string(cls, value: str) -> "ImageFocus":
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.CENTER
