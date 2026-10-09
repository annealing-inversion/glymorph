"""Only two opt-in operations: terminal length adjustment and isotropic scaling."""

from dataclasses import asdict, dataclass
import hashlib
import math
import random

from .font import Glyph
from .geometry import contact_interval, densify, extend, length, outward, trim_start


@dataclass(frozen=True)
class Options:
    length: bool = False
    length_min: float = .85
    length_max: float = 1.15
    length_ends: str = 'both'
    junction_tolerance: float = .002
    scale: bool = False
    scale_mode: str = 'local'
    scale_min: float = .75
    scale_max: float = 1.25
    scale_center: str = 'random'
    scale_radius: float = .35
    scale_step: float = .01

    def validate(self):
        if not self.length and not self.scale:
            raise ValueError('请至少启用 --length 或 --scale；两项可同时启用')
        for key, value in asdict(self).items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f'{key} 必须是有限数值')
        if not 0 < self.length_min <= self.length_max:
            raise ValueError('长度倍数必须满足 0 < length-min <= length-max')
        if not 0 < self.scale_min <= self.scale_max:
            raise ValueError('缩放倍数必须满足 0 < scale-min <= scale-max')
        if self.length_ends not in ('both', 'start', 'end'):
            raise ValueError('未知的笔端选择')
        if self.scale_mode not in ('local', 'global') or self.scale_center not in ('random', 'center'):
            raise ValueError('未知的缩放方式或缩放中心')
        if self.junction_tolerance < 0:
            raise ValueError('交接保护距离不能小于 0')
        if self.scale_radius <= 0 or self.scale_step <= 0:
            raise ValueError('局部缩放半径和采样间隔必须大于 0')
        # For this Gaussian radial map, the radial derivative is positive when
        # s < 1 + exp(1.5)/2. Prevent a continuous local map from folding over.
        if self.scale and self.scale_mode == 'local' and self.scale_max >= 1 + math.exp(1.5)/2:
            raise ValueError('局部缩放上限必须小于 3.2408，以避免变形折叠')


def rng_for(seed, variant, char, operation):
    # Independent streams: enabling scale must not change the length samples.
    digest = hashlib.sha256(f'{seed}|{variant}|{ord(char)}|{operation}'.encode()).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def glyph_size(glyph):
    x0, y0, x1, y1 = glyph.bounds()
    return max(x1-x0, y1-y0)


@dataclass(frozen=True)
class LengthPlan:
    total: float
    shrink: tuple[float, float]
    grow: tuple[float, float]


def plan_length(glyph, options):
    """Protect contact regions and cap extensions before they hit another path.

    Geometric paths are kept separate: no guessed semantic stroke merging,
    pen-order change, smoothing, or removal of existing pen lifts.
    """
    tolerance = options.junction_tolerance * glyph_size(glyph)
    all_segments = [(i, j, a, b) for i, stroke in enumerate(glyph.strokes)
                    for j, (a, b) in enumerate(zip(stroke, stroke[1:]))]
    # Singleton paths also participate in contact protection.
    all_segments += [(i, 0, s[0], s[0]) for i, s in enumerate(glyph.strokes) if len(s) == 1]
    plans = []
    for index, stroke in enumerate(glyph.strokes):
        total = length(stroke)
        low, high, travelled = total, 0., 0.
        for j, (a, b) in enumerate(zip(stroke, stroke[1:])):
            segment_length = math.dist(a, b)
            for other, k, c, d in all_segments:
                if other == index and abs(j-k) <= 1:
                    continue
                hit = contact_interval(a, b, c, d, tolerance)
                if hit:
                    low = min(low, travelled + hit[0]*segment_length)
                    high = max(high, travelled + hit[1]*segment_length)
            travelled += segment_length
        shrink = [low, total-high]
        if total == 0 or (len(stroke) > 2 and math.dist(stroke[0], stroke[-1]) <= tolerance):
            shrink = [0., 0.]
        if options.length_ends == 'start':
            shrink[1] = 0.
        elif options.length_ends == 'end':
            shrink[0] = 0.
        free = [distance > 1e-9 for distance in shrink]
        maximum = max(0., options.length_max-1)*total / max(1, sum(free))
        grow = [0., 0.]
        for tip_index, at_start in enumerate((True, False)):
            if not free[tip_index] or maximum == 0:
                continue
            a = stroke[0] if at_start else stroke[-1]
            dx, dy = outward(stroke, at_start)
            b = a[0]+dx*maximum, a[1]+dy*maximum
            limit = 1.
            terminal_segment = 0 if at_start else len(stroke)-2
            for other, k, c, d in all_segments:
                if other == index and k == terminal_segment:
                    continue
                hit = contact_interval(a, b, c, d, tolerance)
                if hit:
                    limit = min(limit, hit[0])
            grow[tip_index] = max(0., maximum*limit - (1e-8*max(1., total) if limit < 1 else 0.))
        plans.append(LengthPlan(total, tuple(shrink), tuple(grow)))
    return tuple(plans)


def adjust_length(glyph, options, plans, rng):
    strokes = []
    tolerance = options.junction_tolerance * glyph_size(glyph)
    stats = {'paths_extended': 0, 'paths_shortened': 0, 'paths_unchanged': 0,
             'paths_limited': 0}
    for stroke, plan in zip(glyph.strokes, plans):
        factor = rng.uniform(options.length_min, options.length_max)
        delta = (factor-1)*plan.total
        free = [cap > 1e-9 for cap in plan.shrink]
        if delta == 0 or not any(free):
            strokes.append(stroke)
            stats['paths_unchanged'] += 1
            continue
        requested = abs(delta) / sum(free)
        caps = plan.grow if delta > 0 else plan.shrink
        amounts = [min(requested, cap) if allowed else 0.
                   for cap, allowed in zip(caps, free)]
        if delta > 0:
            # Earlier paths may also have grown. Check the newly extended tips
            # against their final positions, not only the original font paths.
            for tip_index, at_start in enumerate((True, False)):
                amount = amounts[tip_index]
                if amount <= 0:
                    continue
                a = stroke[0] if at_start else stroke[-1]
                dx, dy = outward(stroke, at_start)
                b = a[0]+dx*amount, a[1]+dy*amount
                limit = 1.
                for previous in strokes:
                    segments = zip(previous, previous[1:]) if len(previous) > 1 else [(previous[0], previous[0])]
                    for c, d in segments:
                        hit = contact_interval(a, b, c, d, tolerance)
                        if hit:
                            limit = min(limit, hit[0])
                if limit < 1:
                    amounts[tip_index] = max(0., amount*limit - 1e-8*max(1., plan.total))
        if sum(amounts) + 1e-8 < abs(delta):
            stats['paths_limited'] += 1
        if sum(amounts) <= 1e-9:
            result = stroke
        elif delta > 0:
            result = extend(stroke, *amounts)
        else:
            result = trim_start(stroke, amounts[0])
            result = tuple(reversed(trim_start(tuple(reversed(result)), amounts[1])))
        stats['paths_unchanged' if result == stroke else
              'paths_extended' if delta > 0 else 'paths_shortened'] += 1
        strokes.append(result)
    return glyph.with_strokes(strokes), stats


def scale_glyph(glyph, options, rng):
    factor = rng.uniform(options.scale_min, options.scale_max)
    if factor == 1. or not glyph.points:
        return glyph
    x0, y0, x1, y1 = glyph.bounds()
    if options.scale_center == 'random':
        center = rng.uniform(x0, x1), rng.uniform(y0, y1)
    else:
        center = (x0+x1)/2, (y0+y1)/2
    size = glyph_size(glyph)
    if size == 0:
        return glyph
    radius = options.scale_radius * size

    def transform(p):
        dx, dy = p[0]-center[0], p[1]-center[1]
        multiplier = factor
        if options.scale_mode == 'local':
            multiplier = 1 + (factor-1)*math.exp(-.5*((dx/radius)**2 + (dy/radius)**2))
        return center[0]+multiplier*dx, center[1]+multiplier*dy

    strokes = glyph.strokes
    if options.scale_mode == 'local':
        step = min(options.scale_step*size, radius/8)
        estimated = sum(max(1, math.ceil(math.dist(a, b)/step))
                        for s in strokes for a, b in zip(s, s[1:]))
        if estimated > 1_000_000:
            raise ValueError('局部缩放采样过密；请增大 --scale-step 或 --scale-radius')
        strokes = tuple(densify(s, step) for s in strokes)
    return glyph.with_strokes(tuple(tuple(transform(p) for p in s) for s in strokes))


def transform_glyph(glyph: Glyph, options: Options, seed: int, variant: int, plans=None):
    result, stats = glyph, {}
    if options.length:
        plans = plan_length(glyph, options) if plans is None else plans
        result, stats = adjust_length(result, options, plans,
                                      rng_for(seed, variant, glyph.char, 'length'))
    if options.scale:
        result = scale_glyph(result, options, rng_for(seed, variant, glyph.char, 'scale'))
    return result, stats
