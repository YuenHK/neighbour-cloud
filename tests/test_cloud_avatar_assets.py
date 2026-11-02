import asyncio
import copy
import hashlib
import io
import json
import sqlite3
import threading
import zipfile
from contextlib import closing

import pytest
from fastapi import HTTPException
from PIL import Image

from deploy.cloud.avatar_api import AvatarWork, ModelBytes
from deploy.cloud.avatar_assets import AvatarAssets, install, validate_archive
from deploy.cloud.presentation import Presentation, PresentationEdit
from deploy.cloud.presentation import install as install_presentation
from deploy.cloud.sql_snapshot import snapshot
from edge_hub.estate_services import EstateStore


def model_zip(extra=None, refs=None):
    png = io.BytesIO()
    Image.new('RGB', (8, 8), 'green').save(png, format='PNG')
    config = {'Version': 3, 'FileReferences': refs or {'Moc': 'body.moc3', 'Textures': ['texture.png']}}
    files = {'avatar.model3.json': json.dumps(config).encode(), 'body.moc3': b'MOC3synthetic', 'texture.png': png.getvalue()}
    files.update(extra or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def store(path):
    def connect(readonly):
        return sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True)
    return AvatarAssets(connect)


def test_archive_is_immutable_idempotent_and_survives_independent_reader_snapshot(tmp_path):
    path = tmp_path / 'estate.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        install(db)
        install(db)
    content = model_zip()
    identity = 'cloud-live2d-' + hashlib.sha256(content).hexdigest()
    assets = store(path)
    first = assets.put(identity, '公開合成模型.zip', content)
    assert assets.put(identity, '不應覆寫舊名稱', content) == first
    assert store(path).get(identity) == content
    assert len(assets.catalog()) == 1
    restored = tmp_path / 'recovery.sqlite3'
    with closing(sqlite3.connect(path)) as reader:
        snapshot(reader, restored)
    assert store(restored).get(identity) == content
    assert store(restored).catalog() == assets.catalog()


@pytest.mark.parametrize('extra,refs', [
    ({'../outside.txt': b'x'}, None), ({'run.js': b'alert(1)'}, None),
    ({'second.model3.json': b'{}'}, None), ({'warning.wav': b'RIFF'}, None),
    (None, {'Moc': 'https://outside.invalid/a.moc3', 'Textures': ['texture.png']}),
    (None, {'Moc': 'body.moc3', 'Textures': ['missing.png']}),
])
def test_archive_rejects_external_missing_executable_and_ambiguous_inputs(extra, refs):
    with pytest.raises(ValueError):
        validate_archive(model_zip(extra, refs))


def test_publishing_requires_uploaded_content_and_preserves_old_profile_on_failure(tmp_path):
    estate = EstateStore(tmp_path / 'estate.sqlite3')
    try:
        install_presentation(estate.db)
        install(estate.db)
        profile = Presentation(estate)
        before = profile.current()
        content = model_zip()
        identity = 'cloud-live2d-' + hashlib.sha256(content).hexdigest()
        body = copy.deepcopy({key: value for key, value in before.items() if key != 'revision'})
        body['airi']['stage_model'] = identity
        with pytest.raises(HTTPException) as failure:
            profile.save(PresentationEdit(expected_revision=1, **body))
        assert failure.value.status_code == 422
        assert profile.current(refresh=True) == before
        store(estate.path).put(identity, '公開模型', content)
        result = profile.save(PresentationEdit(expected_revision=1, **body))
        assert result['airi']['stage_model'] == identity
        # A deliberate rollback selects the original built-in, never deletes bytes.
        body['airi']['stage_model'] = 'preset-live2d-2'
        profile.save(PresentationEdit(expected_revision=2, **body))
        assert store(estate.path).get(identity) == content
    finally:
        estate.close()


def test_disconnected_upload_remains_owned_until_ack_for_backup_and_shutdown():
    entered, release = threading.Event(), threading.Event()
    class Assets:
        def put(self, *args):
            entered.set()
            release.wait(5)
            return {'saved': True}
    async def scenario():
        work = AvatarWork()
        request = asyncio.create_task(work.save(Assets(), 'synthetic'))
        await asyncio.to_thread(entered.wait, 2)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert len(work.pending) == 1
        shutdown = asyncio.create_task(work.close())
        await asyncio.sleep(.01)
        assert not shutdown.done()
        release.set()
        await shutdown
        await asyncio.sleep(0)
        assert not work.pending
    asyncio.run(scenario())


def test_cancel_before_first_download_chunk_releases_slot_once():
    released = []
    source = ModelBytes(b'public test', lambda: released.append(True))
    source.close()
    source.close()
    assert list(source) == [] and released == [True]


def test_inventory_full_never_deletes_or_replaces_previous_bytes(tmp_path, monkeypatch):
    import deploy.cloud.avatar_assets as module
    path = tmp_path / 'estate.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        install(db)
    original = model_zip()
    identity = 'cloud-live2d-' + hashlib.sha256(original).hexdigest()
    assets = store(path)
    assets.put(identity, 'original', original)
    monkeypatch.setattr(module, 'MAX_TOTAL', len(original))
    other = model_zip({'NOTICE.txt': b'another public version'})
    with pytest.raises(ValueError, match='64 MB'):
        assets.put('cloud-live2d-' + hashlib.sha256(other).hexdigest(), 'new', other)
    assert len(assets.catalog()) == 1
    assert store(path).get(identity) == original


def test_corrupt_or_missing_chunk_cannot_be_rendered(tmp_path):
    path = tmp_path / 'estate.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        install(db)
    content = model_zip()
    identity = 'cloud-live2d-' + hashlib.sha256(content).hexdigest()
    store(path).put(identity, 'public', content)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('UPDATE cloud_avatar_model_chunks SET content=?', (b'broken',))
    with pytest.raises(ValueError, match='digest_mismatch'):
        store(path).get(identity)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('DELETE FROM cloud_avatar_model_chunks')
    with pytest.raises(ValueError, match='parts_incomplete'):
        store(path).get(identity)
