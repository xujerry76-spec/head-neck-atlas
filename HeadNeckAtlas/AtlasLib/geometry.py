"""Physical-coordinate slice sampling; array order is KJI, coordinates RAS."""
from collections import deque
import numpy as np


def valid_affine(matrix):
    matrix = np.asarray(matrix, dtype=float)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1])
            or abs(np.linalg.det(matrix[:3, :3])) < 1e-10):
        raise ValueError('无效影像几何：需要有限、可逆的仿射矩阵。')
    return matrix


def sample_slice(mask_kji, ijk_to_ras, xy_to_ras, width, height):
    affine = valid_affine(ijk_to_ras)
    xy = valid_affine(xy_to_ras)
    if mask_kji.ndim != 3 or width <= 0 or height <= 0:
        raise ValueError('需要三维分割和有效视图大小。')
    yy, xx = np.indices((height, width))
    screen = np.stack((xx.ravel(), yy.ravel(), np.zeros(xx.size), np.ones(xx.size)))
    ijk = (np.linalg.inv(affine) @ xy @ screen)[:3]
    # Nearest neighbor, excluding out-of-FOV points rather than clipping them.
    ijk = np.floor(ijk + .5).astype(np.int64)
    bounds = np.array(mask_kji.shape[::-1])[:, None]
    inside = ((ijk >= 0) & (ijk < bounds)).all(axis=0)
    result = np.zeros(xx.size, dtype=bool)
    i, j, k = ijk[:, inside]
    result[inside] = mask_kji[k, j, i] != 0
    return result.reshape(height, width)


def interior_anchor(mask_yx):
    """Find a point in the largest 4-connected component, never in its hole."""
    mask = np.asarray(mask_yx, dtype=bool)
    if mask.ndim != 2:
        raise ValueError('需要二维截面。')
    remaining = set(map(tuple, np.argwhere(mask)))
    largest = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        queue, component = deque([seed]), []
        while queue:
            y, x = queue.popleft()
            component.append((y, x))
            for point in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                if point in remaining:
                    remaining.remove(point)
                    queue.append(point)
        if len(component) > len(largest):
            largest = component
    if not largest:
        return None
    coords = np.asarray(largest)
    center = coords.mean(axis=0)
    y, x = coords[np.argmin(((coords - center) ** 2).sum(axis=1))]
    return int(x), int(y)


def layout_labels(items, width, height, offsets=None):
    offsets = offsets or {}
    box_width, gap = min(140, max(1, width // 2)), 24
    capacity = max(0, (height - 8) // gap)
    result = []
    for side in (0, 1):
        group = sorted((item for item in items if int(item['anchor'][0] >= width/2) == side),
                       key=lambda item: (item['anchor'][1], item['id']))
        previous = -gap
        visible = group[:capacity]
        for index, item in enumerate(group):
            entry = dict(item, hidden=index >= capacity)
            if not entry['hidden']:
                dx, dy = offsets.get(item['id'], (0, 0))
                x = np.clip((4 if side == 0 else width-box_width-4) + dx, 0, width-box_width)
                upper = height-gap-(len(visible)-index-1)*gap
                y = np.clip(item['anchor'][1] + dy, max(0, previous+gap), upper)
                entry['position'] = (float(x), float(y))
                entry['size'] = (box_width, gap)
                previous = y
            result.append(entry)
    return result


def volume_ml(mask, ijk_to_ras):
    return float(np.count_nonzero(mask) * abs(np.linalg.det(valid_affine(ijk_to_ras)[:3, :3])) / 1000)
