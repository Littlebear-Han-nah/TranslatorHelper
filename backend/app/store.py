"""Small single-instance persistent job store, private to each browser session."""
import json
import sqlite3
import time
from .config import DATA_DIR

DB_PATH = DATA_DIR / 'jobs.sqlite3'

def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    return db

def initialize():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, extension TEXT NOT NULL, created_at REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL)')
        for row in db.execute('SELECT id, body FROM tasks').fetchall():
            task = json.loads(row['body'])
            if task['stage'] not in ('completed', 'failed', 'cancelled'):
                task.update(stage='failed', message='服务重启中断了任务，请重新翻译。已上传文件仍保留。')
                db.execute('UPDATE tasks SET body=? WHERE id=?', (json.dumps(task, ensure_ascii=False), row['id']))

def save_file(id, owner, name, extension):
    with connect() as db:
        db.execute('INSERT INTO files VALUES (?, ?, ?, ?, ?)', (id, owner, name, extension, time.time()))

def get_file(id, owner):
    with connect() as db:
        row = db.execute('SELECT * FROM files WHERE id=? AND owner=?', (id, owner)).fetchone()
        return dict(row) if row else None

def put_task(task, owner):
    with connect() as db:
        db.execute('INSERT INTO tasks VALUES (?, ?, ?)', (task['task_id'], owner, json.dumps(task, ensure_ascii=False)))

def get_task(id, owner=None):
    with connect() as db:
        row = db.execute('SELECT body FROM tasks WHERE id=?' + (' AND owner=?' if owner else ''), (id, owner) if owner else (id,)).fetchone()
        return json.loads(row['body']) if row else None

def update(id, **changes):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT body FROM tasks WHERE id=?', (id,)).fetchone()
        if not row:
            return
        task = json.loads(row['body'])
        # Cancellation is terminal, including races with the background worker.
        if task['stage'] == 'cancelled':
            return
        task.update(changes)
        db.execute('UPDATE tasks SET body=? WHERE id=?', (json.dumps(task, ensure_ascii=False), id))

def list_tasks(owner):
    with connect() as db:
        rows = db.execute('SELECT body FROM tasks WHERE owner=? ORDER BY rowid DESC LIMIT 50', (owner,)).fetchall()
        return [json.loads(row['body']) for row in rows]
