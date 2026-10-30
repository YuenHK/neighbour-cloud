"""Cloud API imports must not require the local EP vision/ASR environment."""
import subprocess
import sys
from pathlib import Path


def test_cloud_import_and_unapproved_photo_rejection_without_local_engines():
    code = '''
import importlib.abc
import sys

blocked = {'cv2', 'onnxruntime', 'sklearn', 'torch', 'sherpa_onnx', 'av'}
class NoSiteEngines(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ImportError('site engine must not be imported: ' + fullname)

sys.meta_path.insert(0, NoSiteEngines())
from deploy.cloud import http_app
from edge_hub import patrol_cloud
assert patrol_cloud.review(b'unreviewed', {'litter'}) == ({'litter'}, 'privacy_review_required')
assert not blocked.intersection(sys.modules)
assert 'edge_hub.app' not in sys.modules
assert 'local_audio_gateway.app' not in sys.modules
print('cloud_import_without_site_engines')
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'cloud_import_without_site_engines'
