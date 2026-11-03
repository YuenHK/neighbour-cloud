"""Small cloud-supported avatar/persona preferences, separate from estate facts.

Installation is an explicit stopped-writer migration, never an HTTP operation
or runtime bootstrap. Native AIRI preferences and provider keys are untouched.
"""
import copy
import json
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from deploy.cloud.airi_runtime import AiriRuntime

PUBLIC_PATH = '/api/v1/resident/presentation'
STAFF_PATH = '/api/v1/service-desk/presentation'
DEFAULT = {'name': '鄰伴', 'greeting': '查資料、傾偈、跟進事情，直接同我講就得。',
           'persona': '', 'background': 'mint'}


class AiriCharacter(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default='', max_length=1200)
    personality: str = Field(default='', max_length=1200)
    scenario: str = Field(default='', max_length=1200)
    system_prompt: str = Field(default='', max_length=4000)


class AiriPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    stage_model: str = Field(default='preset-live2d-2', pattern=r'^(?:preset-(?:live2d|vrm)-[12]|cloud-(?:live2d|vrm)-[a-f0-9]{64})$')
    scene_background: Literal['none', 'builtin:cozy-tea-corner', 'builtin:cute-streaming-room'] = 'none'
    card: AiriCharacter | None = None
    runtime: AiriRuntime = Field(default_factory=AiriRuntime)


class PresentationEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=40)
    greeting: str = Field(min_length=1, max_length=200)
    persona: str = Field(max_length=1200)
    background: Literal['mint', 'sky', 'warm']
    airi: AiriPreferences = Field(default_factory=AiriPreferences)
    robot_remote_url: str = Field(default='', max_length=180)

    @field_validator('robot_remote_url')
    @classmethod
    def robot_url(cls, value):
        if value and not re.fullmatch(r'https://[a-z0-9-]+\.ngrok-free\.(app|dev)', value):
            raise ValueError('approved_free_robot_endpoint_required')
        return value

    @field_validator('name', 'greeting', 'persona')
    @classmethod
    def text(cls, value):
        if '\x00' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError('invalid_presentation_text')
        return value


def install(db):
    """Explicit additive migration; never change resident data or reseed a row."""
    if db.in_transaction:
        raise ValueError('presentation_migration_requires_dedicated_connection')
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS cloud_presentation ('
                   'id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL)')
        row = db.execute('SELECT revision,payload FROM cloud_presentation WHERE id=1').fetchone()
        if row is None:
            db.execute('INSERT INTO cloud_presentation VALUES(1,1,?)', (json.dumps(DEFAULT, ensure_ascii=True),))
        else:
            PresentationEdit(expected_revision=row[0], **json.loads(row[1]))


class Presentation:
    def __init__(self, estate):
        self.estate = estate
        self._cached = None
        self.current(refresh=True)

    def _read(self):
        row = self.estate.db.execute('SELECT revision,payload FROM cloud_presentation WHERE id=1').fetchone()
        if row is None:
            raise OSError('cloud_presentation_missing')
        try:
            value = PresentationEdit(expected_revision=row[0], **json.loads(row[1])).model_dump()
            value['revision'] = value.pop('expected_revision')
            return value
        except (ValueError, TypeError):
            raise OSError('cloud_presentation_invalid') from None

    def current(self, *, refresh=False):
        with self.estate.lock:
            if self._cached is None or refresh:
                self._cached = self._read()
            return copy.deepcopy(self._cached)

    def public(self):
        value = {key: value for key, value in self.current().items() if key not in ('persona', 'robot_remote_url')}
        value['airi'] = {key: item for key, item in value['airi'].items() if key != 'card'}
        return value

    def prompt(self):
        value = self.current()
        card = value['airi'].get('card')
        character = '\n'.join(card[key] for key in ('description', 'personality', 'scenario', 'system_prompt')) if card else ''
        return ('你的稱呼是「' + value['name'] + '」。' + value['persona']
                + ('\nAIRI 角色設定（語氣及背景，不代表已完成現實操作）：\n' + character if character else ''))

    def runtime(self):
        return self.current()['airi']['runtime']

    def save(self, edit):
        with self.estate.lock:
            try:
                with self.estate.db:
                    self.estate.db.execute('BEGIN IMMEDIATE')
                    existing = self._read()
                    if existing['revision'] != edit.expected_revision:
                        raise HTTPException(409, '設定已有更新，請重新查看後再儲存。')
                    payload = edit.model_dump(exclude={'expected_revision'})
                    if 'airi' not in edit.model_fields_set:
                        payload['airi'] = existing['airi']
                    elif 'runtime' not in edit.airi.model_fields_set:
                        # A previously open editor must not reset new module settings.
                        payload['airi']['runtime'] = existing['airi']['runtime']
                    if 'robot_remote_url' not in edit.model_fields_set:
                        payload['robot_remote_url'] = existing['robot_remote_url']
                    model = payload['airi']['stage_model']
                    if model.startswith(('cloud-live2d-', 'cloud-vrm-')):
                        from deploy.cloud.avatar_assets import model_digest
                        uploaded = self.estate.db.execute('SELECT entrypoint FROM cloud_avatar_models WHERE digest=?', (model_digest(model),)).fetchone()
                        if not uploaded or (uploaded[0] == 'model.vrm') != model.startswith('cloud-vrm-'):
                            raise HTTPException(422, '請先完成模型上載；原有設定保留。')
                    self.estate.db.execute('UPDATE cloud_presentation SET revision=revision+1,payload=? WHERE id=1',
                                          (json.dumps(payload, ensure_ascii=True),))
                self._cached = {**payload, 'revision': edit.expected_revision + 1}
            except BaseException:
                self._cached = None  # Unknown acknowledgement must be read back, not guessed.
                raise
            return dict(self._cached)
