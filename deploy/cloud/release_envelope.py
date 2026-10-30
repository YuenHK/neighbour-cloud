"""Service-bound authenticated transfer for a verified formal release.

Separate purpose/format/key derivation from staging. Carries only approved
runtime references, metadata and service secrets; never source data/SQLite or
arbitrary environment overrides. The existing owned host secret is bootstrap
material, not a newly exposed credential. No plaintext orchestration output.
"""
import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from deploy.cloud.database_profile import unique_object

VARIABLE = 'NEIGHBOUR_RELEASE_ENVELOPE'
FORMAT = 'neighbour-release-envelope-v1'
FIELDS = {'format', 'service_id', 'origin', 'salt', 'nonce', 'ciphertext'}
KEYS = {'NEIGHBOUR_CREDENTIAL_BACKEND', 'NEIGHBOUR_SETTINGS_ROOT', 'NEIGHBOUR_CLOUD_CONFIG',
        'NEIGHBOUR_MANAGED_RELEASE', 'NEIGHBOUR_SECRET_TURSO_DATA', 'NEIGHBOUR_SECRET_TURSO_READ',
        'NEIGHBOUR_SECRET_RETENTION_LEDGER', 'NEIGHBOUR_SECRET_CLOUDFLARE_GEMMA',
        'NEIGHBOUR_SECRET_AZURE_SPEECH_F0', 'NEIGHBOUR_SECRET_TAVILY'}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def validate(values):
    if (not isinstance(values, dict) or set(values) != KEYS
            or any(not isinstance(value, str) or not value or '\x00' in value or len(value) > 65536 for value in values.values())
            or values['NEIGHBOUR_CREDENTIAL_BACKEND'] != 'managed-environment'):
        raise ValueError('release_envelope_unavailable')
    return values


def key(bootstrap, salt, binding):
    if (not isinstance(bootstrap, str) or not 16 <= len(bootstrap) <= 4096 or not bootstrap.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 for char in bootstrap)):
        raise ValueError('release_envelope_unavailable')
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b'neighbour-render-formal-release-v1:' + binding).derive(bootstrap.encode('ascii'))


def seal(values, bootstrap, *, service_id, origin):
    validate(values)
    binding = canonical({'format': FORMAT, 'service_id': service_id, 'origin': origin})
    salt, nonce = os.urandom(32), os.urandom(12)
    plain = canonical(values)
    if len(plain) > 98304 - 16:
        raise ValueError('release_envelope_unavailable')
    cipher = AESGCM(key(bootstrap, salt, binding)).encrypt(nonce, plain, binding)
    return canonical({'format': FORMAT, 'service_id': service_id, 'origin': origin,
                      'salt': base64.b64encode(salt).decode(), 'nonce': base64.b64encode(nonce).decode(),
                      'ciphertext': base64.b64encode(cipher).decode()}).decode()


def open_envelope(value, bootstrap, *, service_id, origin):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 131072:
            raise ValueError('invalid')
        data = json.loads(value, object_pairs_hook=unique_object)
        if (not isinstance(data, dict) or set(data) != FIELDS or data['format'] != FORMAT
                or data['service_id'] != service_id or data['origin'] != origin):
            raise ValueError('invalid')
        salt, nonce, cipher = (base64.b64decode(data[name], validate=True) for name in ('salt', 'nonce', 'ciphertext'))
        if len(salt) != 32 or len(nonce) != 12 or not 16 <= len(cipher) <= 98304:
            raise ValueError('invalid')
        binding = canonical({'format': FORMAT, 'service_id': service_id, 'origin': origin})
        plain = AESGCM(key(bootstrap, salt, binding)).decrypt(nonce, cipher, binding)
        return validate(json.loads(plain, object_pairs_hook=unique_object))
    except (InvalidTag, OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError('release_envelope_unavailable') from None
