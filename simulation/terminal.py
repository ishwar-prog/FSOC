"""
simulation/terminal.py — Terminal A (host platform) & Terminal B (mobile remote terminal).

Terminal A: Stationary platform at origin (0, 0, 0). Owns the pan/tilt virtual camera.
Terminal B: Mobile FSOC terminal. Hosts the optical beacon. Low-poly mesh for visualization.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class TerminalA:
    """Stationary FSOC host terminal at world origin.

    Holds the pan/tilt gimbal camera. Terminal A does NOT move.
    """
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
    label: str = "Terminal A (Host)"

    def __post_init__(self):
        # Always fix at origin
        self.position = np.array([0.0, 0.0, 0.0], dtype=float)

    def get_mesh_vertices(self) -> List[np.ndarray]:
        """Low-poly box representing ground terminal structure (for world map)."""
        # Simple 4-vertex box footprint in XZ plane (Y=0)
        hs = 15.0  # half-size
        return [
            np.array([-hs, 0.0, -hs]),
            np.array([ hs, 0.0, -hs]),
            np.array([ hs, 0.0,  hs]),
            np.array([-hs, 0.0,  hs]),
        ]


@dataclass
class TerminalB:
    """Mobile remote FSOC terminal. Moves through the virtual world.

    Hosts the optical beacon that Terminal A must acquire and track.
    Has a low-poly satellite/terminal body for visualization.
    """
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 100.0, 1000.0]))
    label: str = "Terminal B (Mobile)"

    def __post_init__(self):
        self.position = np.array(self.position, dtype=float)

    def update_position(self, new_pos: np.ndarray) -> None:
        """Update terminal B world position from motion module."""
        self.position = np.array(new_pos, dtype=float)

    def get_mesh_vertices_3d(self) -> dict:
        """Low-poly satellite/terminal mesh vertices relative to terminal center.

        Returns a dict with:
          'body': 8 corner vertices of the central rectangular body
          'wing_l': 4 vertices of left solar panel
          'wing_r': 4 vertices of right solar panel
        """
        # Central body box (6x6x12 units)
        bx, by, bz = 6.0, 6.0, 12.0
        body = [
            np.array([-bx, -by, -bz]),
            np.array([ bx, -by, -bz]),
            np.array([ bx,  by, -bz]),
            np.array([-bx,  by, -bz]),
            np.array([-bx, -by,  bz]),
            np.array([ bx, -by,  bz]),
            np.array([ bx,  by,  bz]),
            np.array([-bx,  by,  bz]),
        ]

        # Left wing panel (extends in -X direction)
        ww, wh = 28.0, 10.0  # width, height
        wing_l = [
            np.array([-bx,      -1.0, -wh / 2]),
            np.array([-bx - ww, -1.0, -wh / 2]),
            np.array([-bx - ww, -1.0,  wh / 2]),
            np.array([-bx,      -1.0,  wh / 2]),
        ]

        # Right wing panel (extends in +X direction)
        wing_r = [
            np.array([bx,      -1.0, -wh / 2]),
            np.array([bx + ww, -1.0, -wh / 2]),
            np.array([bx + ww, -1.0,  wh / 2]),
            np.array([bx,      -1.0,  wh / 2]),
        ]

        return {"body": body, "wing_l": wing_l, "wing_r": wing_r}

    def get_world_mesh_vertices(self) -> dict:
        """Get mesh vertices translated to current world position."""
        local = self.get_mesh_vertices_3d()
        p = self.position
        return {
            key: [p + v for v in verts]
            for key, verts in local.items()
        }
