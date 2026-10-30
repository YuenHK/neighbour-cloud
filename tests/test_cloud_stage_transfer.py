import ctypes
import json
import struct

import pytest
from test_cloud_profile_provenance import api_manifest

from deploy.cloud.stage_transfer import WindowsClipboard, clipboard_formats, dotenv, prepare


def transfer_fixture(tmp_path):
    render = tmp_path / 'render-service-20261030'
    turso = tmp_path / 'turso-provisioning'
    render.mkdir()
    turso.mkdir()
    resource = {'plan': 'free', 'region': 'singapore', 'workspace': 'tea-daadio4s728c73836hag',
        'service_id': 'srv-dbi41m2fngtc73c82fq0', 'url': 'https://neighbour-yuenhk.onrender.com'}
    (render / 'RESOURCE.json').write_text(json.dumps(resource))
    login = {'format': 'neighbour-google-login-v1', 'origin': resource['url'],
        'google_client_id': '123456789-synthetic.apps.googleusercontent.com', 'accounts': {'synthetic-staff': 'staff'}}
    profile = api_manifest()
    for role, entry in profile['databases'].items():
        entry['url'] = 'libsql://neighbour-stage-' + role.replace('_', '-') + '.turso.io'
    (turso / 'stage-database-profile.json').write_text(json.dumps(profile))
    plaintext = {'google-login.dpapi': json.dumps(login).encode(),
        'turso-data-token.dpapi': b'PUBLIC-SYNTHETIC-WRITER-TOKEN',
        'turso-read-token.dpapi': b'PUBLIC-SYNTHETIC-READER-TOKEN',
        'stage-ledger-key.dpapi': bytes(range(32))}
    return resource, profile, lambda path: plaintext[path.name]


def test_prepare_is_memory_only_and_never_contains_native_provider_keys_or_data(tmp_path):
    _, _, decrypt = transfer_fixture(tmp_path)
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    values = prepare(tmp_path, decrypt=decrypt)
    assert values['NEIGHBOUR_SECRET_TURSO_READ'] == 'PUBLIC-SYNTHETIC-READER-TOKEN'
    assert values['NEIGHBOUR_SECRET_RETENTION_LEDGER'].startswith('base64:')
    assert not any(name in values for name in ('NEIGHBOUR_SECRET_CLOUDFLARE_GEMMA',
                                              'NEIGHBOUR_SECRET_AZURE_SPEECH_F0', 'NEIGHBOUR_SECRET_TAVILY'))
    metadata = json.loads(values['NEIGHBOUR_MANAGED_STAGE'])
    assert metadata['accounts'] == {'synthetic-staff': 'staff'}
    assert metadata['format'] == 'neighbour-managed-stage-v1'
    text = dotenv(values)
    assert text.count('\n') == 7 and 'NEIGHBOUR_MANAGED_STAGE={' in text
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('change', ['paid', 'other-service', 'production-database'])
def test_paid_unowned_or_nonstaging_targets_reject_before_credential_export(tmp_path, change):
    resource, profile, _ = transfer_fixture(tmp_path)
    if change == 'paid':
        resource['plan'] = 'starter'
    elif change == 'other-service':
        resource['service_id'] = 'srv-other-service'
    else:
        profile['databases']['cases']['url'] = 'libsql://formal-private.turso.io'
    (tmp_path / 'render-service-20261030/RESOURCE.json').write_text(json.dumps(resource))
    (tmp_path / 'turso-provisioning/stage-database-profile.json').write_text(json.dumps(profile))

    def decrypt(path):
        assert path.name == 'google-login.dpapi'
        return json.dumps({'format': 'neighbour-google-login-v1', 'origin': resource['url']}).encode()
    with pytest.raises(ValueError, match='verified_owned_free_staging_resources_required'):
        prepare(tmp_path, decrypt=decrypt)


@pytest.mark.parametrize('value', ['', 'has space', 'a\nb', 'a#comment', '非ASCII', '"quoted"'])
def test_dotenv_refuses_ambiguous_or_multiline_values(value):
    with pytest.raises(ValueError):
        dotenv({'SYNTHETIC': value})


def test_clipboard_privacy_markers_precede_any_plaintext_and_disable_history_and_sync():
    formats = clipboard_formats('PUBLIC-SYNTHETIC-ONLY')
    assert [item[0] for item in formats] == ['ExcludeClipboardContentFromMonitorProcessing',
        'CanIncludeInClipboardHistory', 'CanUploadToCloudClipboard', 13]
    assert formats[1][1] == struct.pack('<I', 0) == formats[2][1]
    assert formats[-1][1].decode('utf-16-le') == 'PUBLIC-SYNTHETIC-ONLY\x00'


class FakeNative:
    def __init__(self, *, fail_guard=False):
        self.buffers, self.writes, self.sequence, self.emptied, self.next_id = {}, [], 5, 0, 20
        self.fail_guard = fail_guard

    def OpenClipboard(self, _window):
        return True

    def CloseClipboard(self):
        pass

    def EmptyClipboard(self):
        self.emptied += 1
        self.sequence += 1
        return True

    def RegisterClipboardFormatW(self, name):
        return 0 if self.fail_guard and name == 'CanUploadToCloudClipboard' else 123

    def GlobalAlloc(self, _flags, size):
        self.next_id += 1
        self.buffers[self.next_id] = ctypes.create_string_buffer(size)
        return self.next_id

    def GlobalLock(self, handle):
        return ctypes.addressof(self.buffers[handle])

    def GlobalUnlock(self, _handle):
        pass

    def GlobalFree(self, _handle):
        pass

    def SetClipboardData(self, kind, handle):
        self.writes.append((kind, self.buffers[handle].raw))
        self.sequence += 1
        return handle

    def GetClipboardSequenceNumber(self):
        return self.sequence


def clipboard(native):
    instance = object.__new__(WindowsClipboard)
    instance.user = instance.kernel = native
    instance.window = 1
    return instance


def test_failed_clipboard_guard_never_publishes_plaintext_no_real_clipboard_used():
    native = FakeNative(fail_guard=True)
    with pytest.raises(OSError):
        clipboard(native).publish(clipboard_formats('PUBLIC-SYNTHETIC'))
    assert not any(kind == 13 for kind, _ in native.writes)
    assert native.emptied == 2


def test_cleanup_preserves_a_newer_user_clipboard_item_no_real_clipboard_used():
    native = FakeNative()
    item = clipboard(native)
    sequence = item.publish(clipboard_formats('PUBLIC-SYNTHETIC'))
    native.sequence += 1
    assert item.clear_if_current(sequence) is False and native.emptied == 1
    native.sequence = sequence
    assert item.clear_if_current(sequence) is True and native.emptied == 2
