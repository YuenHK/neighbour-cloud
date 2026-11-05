"""Reproducible synthetic localisation benchmark; no camera, SDK or network."""
import argparse
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from edge_hub.board_localisation import BoardLocaliser, world_corners
from edge_hub.fiducial_localisation import Calibration, MarkerLocaliser


def synthetic_calibration(*, nonplanar=False):
    face = np.array([[0., 0, -1], [-1, 0, 0], [0, 1, 0]])
    anchors = []
    for identifier, lateral in ((7, -.45), (8, .45)):
        transform = np.eye(4)
        transform[:3, :3] = face
        transform[:3, 3] = [2.5, lateral, .4]
        if nonplanar and identifier == 8:
            yaw = .3
            transform[:3, :3] = np.array([[math.cos(yaw), -math.sin(yaw), 0],
                [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]]) @ face
            transform[0, 3] = 2.8
        anchors.append({'id': identifier, 'size_m': .4, 'world_from_marker': transform.tolist()})
    return {'format': 'neighbour-aruco-pinhole-v1', 'image_size': [640, 360],
        'camera_matrix': [[600, 0, 320], [0, 600, 180], [0, 0, 1]], 'distortion': [0, 0, 0, 0, 0],
        'base_from_camera': [[0, 0, 1, .05], [-1, 0, 0, 0], [0, -1, 0, .25], [0, 0, 0, 1]],
        'anchors': anchors, 'map_sha256': 'a'*64}


def render_frame(value, *, x=0., y=0., yaw=0., visible=(7, 8), seed=0, noise=0., labels=None):
    """Project real dictionary pixels through the exact synthetic camera model."""
    config = Calibration.parse(value)
    world_base = np.eye(4)
    world_base[:2, :2] = [[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]]
    world_base[:2, 3] = [x, y]
    camera_world = np.linalg.inv(config.base_from_camera) @ np.linalg.inv(world_base)
    rotation = cv2.Rodrigues(camera_world[:3, :3])[0]
    canvas = np.full((config.height, config.width), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    source = np.array([[0, 0], [299, 0], [299, 299], [0, 299]], np.float32)
    for identifier in visible:
        pixels = cv2.projectPoints(world_corners(config, identifier), rotation, camera_world[:3, 3],
            config.camera, config.distortion)[0].reshape(4, 2).astype(np.float32)
        marker = cv2.aruco.generateImageMarker(dictionary, (labels or {}).get(identifier, identifier), 300)
        warped = cv2.warpPerspective(marker, cv2.getPerspectiveTransform(source, pixels),
            (config.width, config.height), borderValue=255)
        canvas = np.minimum(canvas, warped)
    if noise:
        canvas = np.clip(canvas.astype(np.float64)+np.random.default_rng(seed).normal(0, noise, canvas.shape), 0, 255).astype(np.uint8)
    return cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def benchmark():
    rows = []
    # A fixed matrix, not a favourable hand-selected frame or any real camera.
    for nonplanar in (False, True):
        config = synthetic_calibration(nonplanar=nonplanar)
        single, joint = MarkerLocaliser(Calibration.parse(config)), BoardLocaliser(Calibration.parse(config))
        for x in (0., .3, .6):
            for y in (-.12, 0., .12):
                for yaw in (-.04, 0., .04):
                    seed = len(rows)
                    frame = render_frame(config, x=x, y=y, yaw=yaw, seed=seed, noise=1.5)
                    result = {'nonplanar': nonplanar, 'true_x_m': x, 'true_y_m': y, 'true_yaw_rad': yaw,
                              'frame_sha256': hashlib.sha256(frame).hexdigest()}
                    for name, localiser in (('single', single), ('joint', joint)):
                        started = time.perf_counter()
                        pose = localiser.estimate(frame, frame_key=f'synthetic-{seed}', captured_at_ms=1000,
                            now_ms=1100, camera_fixed=True)
                        row = {'state': pose['state'], 'reason': pose.get('reason'),
                               'elapsed_ms': (time.perf_counter()-started)*1000}
                        if pose['state'] == 'located':
                            row.update(error_m=math.hypot(pose['x_m']-x, pose['y_m']-y),
                                yaw_error_deg=math.degrees(abs((pose['yaw_rad']-yaw+math.pi) % (2*math.pi)-math.pi)),
                                reprojection_px=pose['reprojection_px'], markers=pose['marker_ids'])
                        result[name] = row
                    rows.append(result)
    summary = {}
    for name in ('single', 'joint'):
        accepted = [row[name] for row in rows if row[name]['state'] == 'located']
        errors = [row['error_m'] for row in accepted]
        summary[name] = {'frames': len(rows), 'located': len(accepted), 'rejected': len(rows)-len(accepted),
            'rejection_reasons': dict(Counter(row[name]['reason'] for row in rows if row[name]['state'] != 'located')),
            'mean_position_error_m': float(np.mean(errors)) if errors else None,
            'p95_position_error_m': float(np.percentile(errors, 95)) if errors else None,
            'maximum_position_error_m': max(errors) if errors else None,
            'mean_processing_ms': float(np.mean([row[name]['elapsed_ms'] for row in rows]))}
    both = [row for row in rows if row['single']['state'] == row['joint']['state'] == 'located']
    paired = {'same_accepted_frames': len(both),
        'single_mean_error_m': float(np.mean([row['single']['error_m'] for row in both])) if both else None,
        'joint_mean_error_m': float(np.mean([row['joint']['error_m'] for row in both])) if both else None}
    groups = {}
    for geometry in (False, True):
        group = [row for row in rows if row['nonplanar'] is geometry]
        groups['nonplanar' if geometry else 'planar'] = {name: {
            'frames': len(group), 'located': sum(row[name]['state'] == 'located' for row in group),
            'rejection_reasons': dict(Counter(row[name]['reason'] for row in group if row[name]['state'] != 'located'))}
            for name in ('single', 'joint')}
    return {'scope': '54 deterministic synthetic JPEG frames including zero-yaw planar ambiguity; exact synthetic calibration; not hardware accuracy or SLAM',
        'summary': summary, 'frames': rows, 'hardware_or_network_calls': 0,
        'motion_authorized': False, 'real_world_accuracy_guarantee': False,
        'paired_accepted_comparison': paired, 'geometry_groups': groups,
        'opencv_version': cv2.__version__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = benchmark()
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(value['summary']))


if __name__ == '__main__':
    main()
