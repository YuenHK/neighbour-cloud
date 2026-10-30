"""Resolve imported Notebook ASR assets without another user's legacy paths."""
import json
import os
from pathlib import Path

SENSEVOICE_DIRECTORY = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09'


def sensevoice_root(project, environ=None):
    environ = os.environ if environ is None else environ
    explicit = environ.get('ZHIWEI_SENSEVOICE_ROOT')
    if explicit:
        return Path(explicit)
    project = Path(project)
    try:
        receipt = json.loads((project/'IMPORT-RECEIPT.json').read_text(encoding='utf-8-sig'))
        candidate = Path(receipt['resources'])/'Models/speech'/SENSEVOICE_DIRECTORY
        if all((candidate/name).is_file() for name in ('model.int8.onnx', 'tokens.txt')):
            return candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Explicitly unavailable until assets are installed; never borrow another user's directory.
    return project/'models/speech'/SENSEVOICE_DIRECTORY
