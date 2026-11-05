"""Analyse saved JPEGs or create printable ArUco markers; never opens devices."""
import argparse
import json
from pathlib import Path

from edge_hub.fiducial_localisation import Calibration, MarkerLocaliser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    marker = commands.add_parser('marker', help='write a marker with a white quiet border')
    marker.add_argument('--id', type=int, choices=range(50), required=True)
    marker.add_argument('--output', type=Path, required=True)
    analyse = commands.add_parser('analyse', help='calibrated pose from a previously saved frame')
    analyse.add_argument('--calibration', type=Path, required=True)
    analyse.add_argument('--jpeg', type=Path, required=True)
    analyse.add_argument('--captured-at-ms', type=int, required=True)
    analyse.add_argument('--now-ms', type=int, required=True)
    analyse.add_argument('--fixed-camera-confirmed', action='store_true')
    analyse.add_argument('--method', choices=('single', 'board'), default='single',
                         help='board jointly fits at least two surveyed markers; no automatic fallback')
    args = parser.parse_args()
    if args.command == 'marker':
        import cv2
        from PIL import Image
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        pixels = cv2.aruco.generateImageMarker(dictionary, args.id, 600)
        image = Image.new('L', (800, 800), 255)
        image.paste(Image.fromarray(pixels), (100, 100))
        with args.output.open('xb') as stream:
            image.save(stream, format='PNG')
        print('Print without distortion; measure the black marker square in metres after printing.')
        return
    if args.calibration.stat().st_size > 40_000 or args.jpeg.stat().st_size > 1_500_000:
        raise ValueError('input_bound_exceeded')
    config = Calibration.parse(json.loads(args.calibration.read_text(encoding='utf-8')))
    localiser = MarkerLocaliser
    if args.method == 'board':
        from edge_hub.board_localisation import BoardLocaliser
        localiser = BoardLocaliser
    result = localiser(config).estimate(args.jpeg.read_bytes(), frame_key='saved-frame',
        captured_at_ms=args.captured_at_ms, now_ms=args.now_ms, camera_fixed=args.fixed_camera_confirmed)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
