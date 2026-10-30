"""Opt-in local facts, not conversation logging, agents, tools or Codex memory."""
from __future__ import annotations

import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException


def remember_text(payload):
    messages = payload.get('messages')
    if not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict):
        return None
    message = messages[-1]
    # Only a direct, final user command; never a role/tool/context/quoted instruction.
    if message.get('role') != 'user':
        return None
    from edge_hub.chat_context import text_content
    content = message.get('content')
    if isinstance(content, list) and any(not isinstance(p, dict) or p.get('type') != 'text' for p in content):
        return None
    text = text_content(content)
    # Pinned AIRI prefixes each provider user message with a datetime. Strip
    # exactly that one transport prefix, never arbitrary quotes/context prose.
    text = re.sub(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] ', '', text, count=1)
    if text == '記住':
        raise HTTPException(400, '請用「記住：內容」，每項最多 1000 字')
    command = re.fullmatch(r'記住[：:,，\s]+(.+)', text, flags=re.DOTALL)
    if command is None or text.endswith(('?', '？')):
        return None
    fact = command[1].strip()
    if not 1 <= len(fact) <= 1000 or '\x00' in fact or any(0xD800 <= ord(c) <= 0xDFFF for c in fact):
        raise HTTPException(400, '請用「記住：內容」，每項最多 1000 字')
    return fact


class MemoryStore:
    """Lazy SQLite, max 100 current facts. No raw chat, embeddings or audit copies.

    SQL deletion is not erasure of existing browser history, backups or SSD cells.
    """
    def __init__(self, path, *, connection_factory=None):
        self.path = Path(path)
        self.lock = threading.Lock()
        self._connection_factory = connection_factory

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connect = sqlite3.connect if self._connection_factory is None else self._connection_factory
        db = connect(self.path, timeout=2)
        try:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('''CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, text TEXT NOT NULL UNIQUE,
                revision INTEGER NOT NULL, updated_ms INTEGER NOT NULL)''')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate(text):
        if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000
                or '\x00' in text or any(0xD800 <= ord(c) <= 0xDFFF for c in text)):
            raise HTTPException(422, 'invalid memory text')
        return text.strip()

    def items(self):
        with self.lock, self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                'SELECT id,text,revision,updated_ms FROM memories ORDER BY updated_ms DESC,id LIMIT 100')]

    def remember(self, text):
        text = self.validate(text)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM memories WHERE text=?', (text,)).fetchone()
            if existing:
                return existing[0]
            if db.execute('SELECT count(*) FROM memories').fetchone()[0] >= 100:
                raise HTTPException(409, 'memory capacity reached; remove an item first')
            identity = uuid4().hex
            db.execute('INSERT INTO memories VALUES (?,?,1,?)', (identity, text, int(time.time()*1000)))
            return identity

    def change(self, identity, revision, text=None):
        if type(revision) is not int or not 1 <= revision <= 2147483647:
            raise HTTPException(422, 'invalid memory revision')
        with self.lock, self.connect() as db:
            try:
                if text is None:
                    cursor = db.execute('DELETE FROM memories WHERE id=? AND revision=?', (identity, revision))
                else:
                    cursor = db.execute('UPDATE memories SET text=?,revision=revision+1,updated_ms=? '
                                        'WHERE id=? AND revision=?',
                                        (self.validate(text), int(time.time()*1000), identity, revision))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, 'memory already exists') from error
            if cursor.rowcount != 1:
                raise HTTPException(409, 'memory changed or no longer exists; refresh first')

    def context(self, question):
        words = set(re.findall(r'[a-zA-Z0-9]{2,}', question.lower()))
        words.update(question[i:i+2] for i in range(len(question)-1))
        rows = sorted(self.items(), key=lambda row: sum(word in row['text'].lower() for word in words),
                      reverse=True)
        chosen = []
        length = 0
        for row in rows[:8]:
            if length + len(row['text']) > 3000:
                break
            chosen.append(row['text'])
            length += len(row['text'])
        return chosen


class MemoryCapabilities:
    """RAM-only eight-hour memory scope; cannot satisfy robot/operator auth."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.tokens = {}
        self.lock = threading.Lock()

    def issue(self):
        with self.lock:
            now = self.clock()
            self.tokens = {key: until for key, until in self.tokens.items() if until > now}
            if len(self.tokens) >= 8:
                raise HTTPException(409, 'too many memory sessions; revoke sessions first')
            token = secrets.token_urlsafe(32)
            self.tokens[token] = now + 8*3600
            return token

    def valid(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return False
        with self.lock:
            return self.tokens.get(token, 0) > self.clock()

    def revoke(self):
        with self.lock:
            self.tokens.clear()
