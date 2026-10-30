"""Authenticated staging updates for an already provisioned owned Render host.

The existing staging writer credential is transport key material only. Its SQL
access may be revoked after rotation; it must remain confidential in the host's
secret storage until this acceptance deployment is retired. No plaintext values
are emitted to orchestration output, committed, or sent through a clipboard.
This is not a production cutover or a replacement for provider secret storage.
"""
import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from deploy.cloud.database_profile import unique_object

VARIABLE = 'NEIGHBOUR_STAGE_ENVELOPE'
FORMAT = 'neighbour-stage-envelope-v1'
FIELDS = {'format', 'service_id', 'origin', 'salt', 'nonce', 'ciphertext'}
KEYS = {'NEIGHBOUR_CREDENTIAL_BACKEND', 'NEIGHBOUR_SETTINGS_ROOT',
        'NEIGHBOUR_CLOUD_CONFIG', 'NEIGHBOUR_MANAGED_STAGE',
        'NEIGHBOUR_SECRET_TURSO_DATA', 'NEIGHBOUR_SECRET_TURSO_READ',
        'NEIGHBOUR_SECRET_RETENTION_LEDGER'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def key_material(bootstrap, salt, binding):
    if (not isinstance(bootstrap, str) or not 16 <= len(bootstrap) <= 4096
            or not bootstrap.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in bootstrap)):
        raise ValueError('stage_envelope_unavailable')
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b'neighbour-render-stage-transport-v1:' + binding).derive(bootstrap.encode('ascii'))


def validate_values(values):
    if (not isinstance(values, dict) or set(values) != KEYS
            or any(not isinstance(v, str) or not v or len(v) > 32768 or '\x00' in v for v in values.values())
            or values['NEIGHBOUR_CREDENTIAL_BACKEND'] != 'managed-environment'):
        raise ValueError('stage_envelope_unavailable')
    return values


def seal(values, bootstrap, *, service_id, origin):
    """Return ciphertext only; destination and authenticated mode are fixed."""
    validate_values(values)
    binding = canonical({'format': FORMAT, 'service_id': service_id, 'origin': origin})
    salt, nonce = os.urandom(32), os.urandom(12)
    cipher = AESGCM(key_material(bootstrap, salt, binding)).encrypt(nonce, canonical(values), binding)
    return canonical({'format': FORMAT, 'service_id': service_id, 'origin': origin,
        'salt': base64.b64encode(salt).decode('ascii'), 'nonce': base64.b64encode(nonce).decode('ascii'),
        'ciphertext': base64.b64encode(cipher).decode('ascii')}).decode('ascii')


def open_envelope(value, bootstrap, *, service_id, origin):
    """No mutations until decryption and all environment names are validated."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 65536:
            raise ValueError('invalid')
        data = json.loads(value, object_pairs_hook=unique_object)
        if (not isinstance(data, dict) or set(data) != FIELDS or data['format'] != FORMAT
                or data['service_id'] != service_id or data['origin'] != origin):
            raise ValueError('invalid')
        salt, nonce, cipher = (base64.b64decode(data[name], validate=True)
                               for name in ('salt', 'nonce', 'ciphertext'))
        if len(salt) != 32 or len(nonce) != 12 or not 16 <= len(cipher) <= 48000:
            raise ValueError('invalid')
        binding = canonical({'format': FORMAT, 'service_id': service_id, 'origin': origin})
        plain = AESGCM(key_material(bootstrap, salt, binding)).decrypt(nonce, cipher, binding)
        return validate_values(json.loads(plain, object_pairs_hook=unique_object))
    except (InvalidTag, OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError('stage_envelope_unavailable') from None
