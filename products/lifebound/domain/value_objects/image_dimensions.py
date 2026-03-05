"""
image_dimensions.py — Value Object
Dimensiones de un slot en píxeles.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ImageDimensions:
    width:  int
    height: int

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Dimensions must be positive: {self.width}x{self.height}")

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height

    def __repr__(self):
        return f"ImageDimensions({self.width}x{self.height})"
