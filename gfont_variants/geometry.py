"""Polyline length and intersection helpers; all distances are font units."""

import math


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def lerp(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _linear_interval(value, delta, low, high):
    if abs(delta) < 1e-14:
        return (0., 1.) if low <= value <= high else None
    a, b = sorted(((low - value) / delta, (high - value) / delta))
    a, b = max(0., a), min(1., b)
    return (a, b) if a <= b else None


def contact_interval(a, b, c, d, tolerance):
    """Interval on AB lying within tolerance of segment CD (a closed capsule)."""
    if (max(a[0], b[0]) + tolerance < min(c[0], d[0])
            or min(a[0], b[0]) - tolerance > max(c[0], d[0])
            or max(a[1], b[1]) + tolerance < min(c[1], d[1])
            or min(a[1], b[1]) - tolerance > max(c[1], d[1])):
        return None
    wx, wy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    w2, v2 = wx*wx + wy*wy, vx*vx + vy*vy
    intervals = []
    if v2 > 0:
        projection = _linear_interval((a[0]-c[0])*vx + (a[1]-c[1])*vy,
                                      wx*vx + wy*vy, 0., v2)
        cross = _linear_interval((a[0]-c[0])*vy - (a[1]-c[1])*vx,
                                 wx*vy - wy*vx,
                                 -tolerance*math.sqrt(v2), tolerance*math.sqrt(v2))
        if projection and cross:
            lo, hi = max(projection[0], cross[0]), min(projection[1], cross[1])
            if lo <= hi:
                intervals.append((lo, hi))
    for center in (c, d):
        dx, dy = a[0]-center[0], a[1]-center[1]
        residual = dx*dx + dy*dy - tolerance*tolerance
        if w2 == 0:
            if residual <= 0:
                intervals.append((0., 1.))
            continue
        dot = dx*wx + dy*wy
        discriminant = dot*dot - w2*residual
        if discriminant >= 0:
            root = math.sqrt(discriminant)
            lo, hi = max(0., (-dot-root)/w2), min(1., (-dot+root)/w2)
            if lo <= hi:
                intervals.append((lo, hi))
    if not intervals:
        return None
    return min(i[0] for i in intervals), max(i[1] for i in intervals)


def trim_start(points, amount):
    if amount <= 0:
        return tuple(points)
    for index, (a, b) in enumerate(zip(points, points[1:])):
        segment = math.dist(a, b)
        if segment > amount:
            return (lerp(a, b, amount / segment),) + tuple(points[index+1:])
        amount -= segment
    return (points[-1],)


def outward(points, at_start):
    points = points if at_start else tuple(reversed(points))
    tip = points[0]
    for p in points[1:]:
        distance = math.dist(tip, p)
        if distance > 0:
            return (tip[0]-p[0])/distance, (tip[1]-p[1])/distance
    return 0., 0.


def extend(points, start, end):
    result = list(points)
    if start > 0:
        dx, dy = outward(points, True)
        result.insert(0, (points[0][0]+dx*start, points[0][1]+dy*start))
    if end > 0:
        dx, dy = outward(points, False)
        result.append((points[-1][0]+dx*end, points[-1][1]+dy*end))
    return tuple(result)


def densify(points, max_step):
    result = list(points[:1])
    for a, b in zip(points, points[1:]):
        count = max(1, math.ceil(math.dist(a, b) / max_step))
        result.extend(lerp(a, b, i/count) for i in range(1, count + 1))
    return tuple(result)
