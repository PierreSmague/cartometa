"""Local frame, zones and regional gain of a tag — pure numpy, no I/O.

Everything here is computed per (source file, country), on the country's
points only. Ported from the design prototype
(docs/specs/2026-11-18-carmeta-spike/zones.py), which produced the figures the
maintainer validated: a change of behaviour here is a change of verdicts.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import MultiPoint

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON = 111.320

# Analysis cell: D/60, kept between these bounds (km).
CELL_MIN_KM, CELL_MAX_KM = 1.5, 25.0
# Regional radius, as a share of the coverage size D.
REGION_RATIO = 0.10
# Link distance of the zones: this many times the sampling spacing, 1 km at least.
LINK_SPACINGS = 3.0
LINK_MIN_KM = 1.0
SPACING_SAMPLE = 300
HULL_SAMPLE = 20_000
# A cell whose regional share is below this fraction of the tag's best region
# is drawn as "eliminated" on the report maps.
ELIMINATED_RATIO = 12 / 255


@dataclass
class Frame:
    """The country's points of one file, projected, with their analysis grid."""

    x: np.ndarray
    y: np.ndarray
    lat0: float
    kx: float
    # True when 360 was added to the negative longitudes (antimeridian).
    wrapped: bool
    size_km: float
    spacing_km: float
    link_km: float
    cell_km: float
    x0: float
    y0: float
    width: int
    height: int
    # Analysis cell of each point, and number of points per cell.
    flat: np.ndarray
    total: np.ndarray
    _regional_total: np.ndarray | None = field(default=None, repr=False)

    @property
    def radius_cells(self) -> float:
        return REGION_RATIO * self.size_km / self.cell_km

    @property
    def regional_total(self) -> np.ndarray:
        if self._regional_total is None:
            self._regional_total = disc_sum(self.total, self.radius_cells)
        return self._regional_total


@dataclass
class Zones:
    """The zones of one tag: chains of at least `min_zone_points` points."""

    # Indexes, in the frame, of the tag's points that fall in a zone.
    points: np.ndarray
    # Zone of each of those points, 0-based, largest zone first.
    labels: np.ndarray
    sizes: list[int]
    capture: float
    # Occupied cells of the link grid, one row per cell: (row, column, zone).
    cells: np.ndarray

    @property
    def count(self) -> int:
        return len(self.sizes)


def disc_sum(array: np.ndarray, radius: float) -> np.ndarray:
    """Sum of `array` over the disc of `radius` cells around each cell."""
    height, width = array.shape
    reach = int(math.floor(radius))
    if reach <= 0:
        return array.copy()
    padded = np.pad(array, reach)
    out = np.zeros_like(array)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dx * dx + dy * dy <= radius * radius:
                out += padded[reach + dy:reach + dy + height,
                              reach + dx:reach + dx + width]
    return out


def _spacing(x: np.ndarray, y: np.ndarray) -> float:
    """Median nearest-neighbour distance, on a fixed-seed sample.

    The seed is fixed because the link distance derives from it: two runs on
    the same file must cut the same zones.
    """
    count = len(x)
    if count < 2:
        return LINK_MIN_KM
    rng = np.random.default_rng(0)
    sample = rng.choice(count, size=min(SPACING_SAMPLE, count), replace=False)
    nearest = []
    for start in range(0, len(sample), 10):
        chunk = sample[start:start + 10]
        d2 = (x[None, :] - x[chunk, None]) ** 2 + (y[None, :] - y[chunk, None]) ** 2
        d2[np.arange(len(chunk)), chunk] = np.inf
        nearest.extend(np.sqrt(d2.min(axis=1)).tolist())
    return float(np.median(nearest))


def build_frame(lat: np.ndarray, lng: np.ndarray) -> Frame:
    if len(lat) == 0:
        raise ValueError("no points: nothing to analyse")
    lat = np.asarray(lat, dtype=np.float64)
    lng = np.asarray(lng, dtype=np.float64).copy()
    wrapped = bool(lng.max() - lng.min() > 300)
    if wrapped:
        lng[lng < 0] += 360
    lat0 = float(lat.mean())
    kx = KM_PER_DEG_LON * math.cos(math.radians(lat0))
    x, y = lng * kx, lat * KM_PER_DEG_LAT
    step = max(1, len(x) // HULL_SAMPLE)
    hull = MultiPoint(np.column_stack([x, y])[::step]).convex_hull
    size = math.sqrt(max(hull.area, 1.0))
    cell = min(CELL_MAX_KM, max(CELL_MIN_KM, size / 60))
    x0, y0 = float(x.min()), float(y.min())
    ix = ((x - x0) // cell).astype(np.int64)
    iy = ((y - y0) // cell).astype(np.int64)
    width, height = int(ix.max()) + 1, int(iy.max()) + 1
    flat = iy * width + ix
    total = np.bincount(flat, minlength=height * width).reshape(height, width)
    spacing = _spacing(x, y)
    return Frame(
        x=x, y=y, lat0=lat0, kx=kx, wrapped=wrapped, size_km=size,
        spacing_km=spacing, link_km=max(LINK_SPACINGS * spacing, LINK_MIN_KM),
        cell_km=cell, x0=x0, y0=y0, width=width, height=height, flat=flat,
        total=total.astype(np.float64),
    )


_STRIDE = 1_000_003
_NEIGHBOURS = [dy * _STRIDE + dx for dy in (-1, 0, 1) for dx in (-1, 0, 1)
               if (dy, dx) != (0, 0)]


def tag_zones(frame: Frame, members: np.ndarray, min_zone_points: int) -> Zones:
    """Chains of the tag's points, linked through a hash grid of side `link_km`.

    A real coverage forms continuous stretches of road; a classification
    mistake is a lone point. Components of 8-connected occupied cells holding
    at least `min_zone_points` points are zones, the rest is ignored.
    """
    members = np.asarray(members, dtype=np.int64)
    empty = Zones(points=members[:0], labels=members[:0], sizes=[], capture=0.0,
                  cells=np.zeros((0, 3), dtype=np.int64))
    if len(members) == 0:
        return empty
    link = frame.link_km
    column = np.floor(frame.x[members] / link).astype(np.int64)
    row = np.floor(frame.y[members] / link).astype(np.int64)
    row0, column0 = int(row.min()), int(column.min())
    # One integer per cell rather than a (row, column) pair: `np.unique` on
    # scalars is what keeps a 100 000-point tag fast. The stride is far wider
    # than any country measured in link cells, so neighbours never alias.
    keys, inverse, counts = np.unique(
        (row - row0) * _STRIDE + (column - column0), return_inverse=True,
        return_counts=True)
    position = {int(key): i for i, key in enumerate(keys)}
    component = np.full(len(keys), -1, dtype=np.int64)
    weights: list[int] = []
    for start in range(len(keys)):
        if component[start] >= 0:
            continue
        current = len(weights)
        component[start] = current
        stack, weight = [start], 0
        while stack:
            i = stack.pop()
            weight += int(counts[i])
            key = int(keys[i])
            for offset in _NEIGHBOURS:
                j = position.get(key + offset)
                if j is not None and component[j] < 0:
                    component[j] = current
                    stack.append(j)
        weights.append(weight)
    weights_array = np.array(weights)
    good = np.nonzero(weights_array >= min_zone_points)[0]
    if len(good) == 0:
        return empty
    # Largest first, ties broken by discovery order: a stable numbering.
    order = good[np.argsort(-weights_array[good], kind="stable")]
    rank = np.full(len(weights), -1, dtype=np.int64)
    rank[order] = np.arange(len(order))
    point_zone = rank[component[inverse]]
    inside = point_zone >= 0
    cell_zone = rank[component]
    kept = cell_zone >= 0
    return Zones(
        points=members[inside],
        labels=point_zone[inside],
        sizes=[int(weights_array[i]) for i in order],
        capture=float(inside.sum() / len(members)),
        cells=np.column_stack([
            keys[kept] // _STRIDE + row0, keys[kept] % _STRIDE + column0,
            cell_zone[kept],
        ]),
    )


def _regional_share(frame: Frame, zone_points: np.ndarray):
    """(share of the tag's zone points within R of each cell, known cells)."""
    count = np.bincount(
        frame.flat[zone_points], minlength=frame.height * frame.width
    ).reshape(frame.height, frame.width).astype(np.float64)
    regional = frame.regional_total
    known = (frame.total > 0) & (regional >= 30)
    share = np.where(
        known,
        disc_sum(count, frame.radius_cells) / np.where(regional > 0, regional, 1),
        0.0,
    )
    return share, known, count


def regional_gain(frame: Frame, zone_points: np.ndarray) -> float:
    """The share of the country one rules out on seeing the tag.

    1 − 2^(−KL), KL being the divergence between the tag's regional share and
    a uniform presence over the known cells. A tag confined to half the country
    gives 0.5; present everywhere, or sprinkled everywhere at the scale of R,
    it gives 0 whatever its surface.
    """
    if len(zone_points) == 0:
        return 0.0
    share, known, _ = _regional_share(frame, zone_points)
    values = share[known]
    total = values.sum()
    if total <= 0:
        return 0.0
    q = values / total
    positive = q > 0
    divergence = float((q[positive] * np.log2(q[positive] * known.sum())).sum())
    return float(1 - 2 ** (-divergence))


def representative(frame: Frame, zones: Zones) -> int:
    """Frame index of the point of the largest zone nearest to its centre."""
    biggest = zones.points[zones.labels == 0]
    cx, cy = frame.x[biggest].mean(), frame.y[biggest].mean()
    nearest = np.argmin((frame.x[biggest] - cx) ** 2 + (frame.y[biggest] - cy) ** 2)
    return int(biggest[int(nearest)])


def coverage_b64(frame: Frame) -> str:
    """Bitmap of the cells holding at least one point, row by row."""
    return base64.b64encode(np.packbits(frame.total.ravel() > 0).tobytes()).decode()


def cell_states_b64(frame: Frame, zone_points: np.ndarray) -> str:
    """Two bits per covered cell for the report maps: 1 zone, 2 eliminated."""
    share, _, count = _regional_share(frame, zone_points)
    covered = frame.total > 0
    values = share[covered]
    states = np.zeros(len(values), dtype=np.uint8)
    best = values.max() if len(values) else 0.0
    if best > 0:
        states[values <= ELIMINATED_RATIO * best] = 2
    states[count[covered] > 0] = 1
    packed = bytearray((len(states) + 3) // 4)
    for i, value in enumerate(states.tolist()):
        packed[i >> 2] |= value << ((i & 3) * 2)
    return base64.b64encode(bytes(packed)).decode()
