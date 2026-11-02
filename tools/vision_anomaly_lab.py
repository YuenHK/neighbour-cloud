"""Anomalib shadow benchmark using ONLY generated floor images, never EP frames.

This is an installation/performance/false-positive experiment. Synthetic
separation is not evidence of fire, flood or electrical leakage accuracy.
Nothing from this lab is loaded by Render or the live patrol process.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import statistics
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(output / 'weights/huggingface')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    import numpy as np
    import torch
    from anomalib.models.image.patchcore.torch_model import PatchcoreModel
    from PIL import Image, ImageDraw

    torch.set_num_threads(2)
    torch.manual_seed(23)
    torch.hub.set_dir(str(output / 'weights/pytorch'))
    rng = np.random.default_rng(23)

    def floor(index, kind='normal'):
        pixels = np.clip(rng.normal(177 + index % 5, 2, (128, 128, 3)), 0, 255).astype('uint8')
        image = Image.fromarray(pixels)
        drawing = ImageDraw.Draw(image)
        for position in (16, 48, 80, 112):
            drawing.line((position, 0, position, 127), fill=(145, 145, 145), width=1)
            drawing.line((0, position, 127, position), fill=(145, 145, 145), width=1)
        if kind == 'shadow':
            drawing.polygon([(0, 0), (56, 0), (104, 127), (0, 127)], fill=(125, 125, 125))
        elif kind == 'reflection':
            drawing.ellipse((30, 24, 78, 116), fill=(218, 218, 218))
        elif kind == 'object':
            drawing.rectangle((45, 45, 69, 65), fill=(86, 49, 24))
        elif kind == 'blue-patch':
            drawing.ellipse((30, 56, 89, 82), fill=(65, 102, 140))
        elif kind == 'orange-patch':
            drawing.polygon([(54, 35), (73, 60), (58, 85), (40, 66)], fill=(245, 102, 25))
        target = output / 'synthetic-images' / f'{kind}-{index}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        tensor = torch.from_numpy(np.array(image).copy()).permute(2, 0, 1).float() / 255
        return (tensor - torch.tensor([.485, .456, .406])[:, None, None]) / torch.tensor([.229, .224, .225])[:, None, None]

    started = time.monotonic()
    model = PatchcoreModel(layers=('layer2', 'layer3'), backbone='resnet18', pre_trained=True, num_neighbors=3)
    model.train()
    with torch.inference_mode():
        for start in range(0, 16, 4):
            model(torch.stack([floor(index) for index in range(start, start + 4)]))
        model.subsample_embedding(.02)
    trained_ms = round((time.monotonic() - started)*1000)
    model.eval()
    samples = []
    for kind in ('normal', 'shadow', 'reflection', 'object', 'blue-patch', 'orange-patch'):
        for index in range(4):
            value = floor(20 + index, kind).unsqueeze(0)
            began = time.monotonic()
            with torch.inference_mode():
                result = model(value)
            samples.append({'kind': kind, 'score': float(result.pred_score[0]),
                            'inference_ms': round((time.monotonic() - began)*1000, 3)})
    threshold = max(row['score'] for row in samples if row['kind'] == 'normal') * 1.1
    for row in samples:
        row['flagged'] = row['score'] > threshold
    weights = []
    for path in (output / 'weights').rglob('*'):
        if path.is_file() and path.stat().st_size > 1_000_000:
            weights.append({'path': path.relative_to(output).as_posix(), 'bytes': path.stat().st_size,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    report = {'installed': {name: importlib.metadata.version(name) for name in ('anomalib', 'torch', 'torchvision', 'timm')},
        'model': 'PatchCore / pretrained ResNet18 / CPU / 128x128 / 2 threads',
        'training_ms': trained_ms, 'median_inference_ms': statistics.median(row['inference_ms'] for row in samples),
        'normal_only_threshold': threshold, 'samples': samples, 'weights': weights,
        'real_scene_accuracy_established': False, 'real_EP_images': False, 'production_enabled': False,
        'decision': 'Shadow research only: requires representative labelled site photos and negative lighting/reflection tests. Never confirms fire/flood/electrical leakage.'}
    (output / 'RESULT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('model', 'training_ms', 'median_inference_ms', 'production_enabled')}))


if __name__ == '__main__':
    main()
