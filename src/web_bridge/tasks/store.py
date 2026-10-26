"""Local durable task records and cross-client mutation leases; never replay jobs."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time


class TaskStoreError(ValueError):
    pass


STATUSES = {'queued', 'running', 'partial', 'blocked', 'awaiting_approval', 'completed', 'cancelled'}


def bounded_json(value, limit, label):
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise TaskStoreError(f'{label} must contain ordinary JSON values.') from None
    if len(encoded) > limit:
        raise TaskStoreError(f'{label} exceeds the local storage limit.')
    return json.loads(encoded)


def text(value, label, limit=16000, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise TaskStoreError(f'Invalid {label}.')
    return value


def workspace_identity(workspace):
    if not isinstance(workspace, dict):
        raise TaskStoreError('A current workspace identity is required.')
    result = bounded_json(workspace, 8000, 'workspace')
    text(result.get('workspace_id'), 'workspace identity', 256)
    if 'root' in result:
        text(result['root'], 'workspace root', 4096)
    return result


def workspace_key(workspace):
    workspace = workspace_identity(workspace)
    # A new revision/session of the same folder must still contend for one writer.
    root = workspace.get('root')
    identity = os.path.normcase(os.path.abspath(root)) if root else workspace['workspace_id']
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def lease_args(owner, ttl):
    text(owner, 'lease owner', 256)
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or not 0 < ttl <= 86400:
        raise TaskStoreError('Lease duration must be between zero and 86400 seconds.')


def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:return True
    if pid==os.getpid():return True
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];api.WaitForSingleObject.restype=wintypes.DWORD
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenProcess(0x00100000,False,pid)
        if not handle:return ctypes.get_last_error()!=87
        try:return api.WaitForSingleObject(handle,0)!=0
        finally:api.CloseHandle(handle)
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except (PermissionError,OSError):return True
    return True


class TaskStore:
    def __init__(self, runtime):
        self.runtime = Path(runtime).resolve()
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.runtime / 'tasks.sqlite3', timeout=10, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS leases (key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL)')
        columns={row[1] for row in self.db.execute('PRAGMA table_info(tasks)')}
        for name,definition in [('summary',"TEXT NOT NULL DEFAULT '{}'"),('scope',"TEXT NOT NULL DEFAULT ''"),('touched','REAL NOT NULL DEFAULT 0')]:
            if name not in columns:self.db.execute('ALTER TABLE tasks ADD COLUMN '+name+' '+definition)
        for task_id,document in self.db.execute("SELECT id,document FROM tasks WHERE summary='{}'").fetchall():
            task=json.loads(document)
            self.db.execute('UPDATE tasks SET summary=?,scope=?,touched=? WHERE id=?',(json.dumps(self.summary(task)),workspace_key(task['workspace']),task['updated_at'],task_id))
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_scope_updated ON tasks(scope,touched DESC)')
        lease_columns={row[1] for row in self.db.execute('PRAGMA table_info(leases)')}
        if 'owner_pid' not in lease_columns:self.db.execute('ALTER TABLE leases ADD COLUMN owner_pid INTEGER NOT NULL DEFAULT 0')
        self.db.commit()
        self.claims = set()
        self.workspace_claims = set()
        self.closed = False

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.closed:
                raise TaskStoreError('Task store is closed.')
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def _load(self, task_id):
        text(task_id, 'task id', 128)
        row = self.db.execute('SELECT document FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise TaskStoreError('Unknown task.')
        task = json.loads(row[0])
        lease = task.get('lease')
        if lease and (lease['expires_at'] <= time.time() or not process_alive(lease.get('process_id'))):
            task['lease'] = None
            if task['status'] == 'running':
                task['status'] = 'partial'
                task['detail'] = 'Writer lease expired. Inspect saved evidence; uncertain side effects must not be replayed.'
            self._save(task)
        return task

    def _save(self, task):
        task['revision'] += 1
        task['updated_at'] = time.time()
        encoded = json.dumps(task, ensure_ascii=True, allow_nan=False)
        self.db.execute('UPDATE tasks SET document=?,summary=?,scope=?,touched=? WHERE id=?', (encoded,json.dumps(self.summary(task)),workspace_key(task['workspace']),task['updated_at'],task['task_id']))

    def create(self, intent, checks, workspace):
        text(intent, 'intent')
        workspace = workspace_identity(workspace)
        root = workspace.get('root')
        if root and (self.runtime == Path(root).resolve() or Path(root).resolve() in self.runtime.parents):
            raise TaskStoreError('Task runtime must be outside the selected source workspace.')
        checks = self._checks(checks)
        now = time.time()
        task = {'task_id': secrets.token_urlsafe(18), 'intent': intent, 'checks': checks,
                'workspace': workspace, 'status': 'queued', 'evidence': [], 'handoff': '',
                'detail': '', 'checkpoints': [], 'operations': [], 'revision': 0, 'lease': None,
                'created_at': now, 'updated_at': now}
        with self.transaction():
            if self.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] >= 1000:
                raise TaskStoreError('Local task limit reached (1000).')
            self.db.execute('INSERT INTO tasks(id,document,summary,scope,touched) VALUES (?,?,?,?,?)', (task['task_id'],json.dumps(task),json.dumps(self.summary(task)),workspace_key(workspace),now))
        return task

    @staticmethod
    def _checks(checks):
        if not isinstance(checks, list) or len(checks) > 100 or any(not isinstance(item, (str, dict)) for item in checks):
            raise TaskStoreError('Checks must be a list of at most 100 checklist entries.')
        return bounded_json(checks, 16000, 'checks')

    @staticmethod
    def summary(task):
        return {'task_id':task['task_id'],'intent':task['intent'][:500],'status':task['status'],
                'handoff':task['handoff'][:1000],'revision':task['revision'],'updated_at':task['updated_at']}

    def summaries(self,workspace,limit=20):
        if type(limit) is not int or not 1<=limit<=100:raise TaskStoreError('Invalid task summary limit.')
        with self.transaction():
            rows=self.db.execute('SELECT id,summary FROM tasks WHERE scope=? ORDER BY touched DESC LIMIT ?',(workspace_key(workspace),limit)).fetchall()
            result=[]
            for task_id,encoded in rows:
                item=json.loads(encoded)
                if item['status']=='running':item=self.summary(self._load(task_id))
                result.append(item)
            return result

    def list(self):
        with self.transaction():
            ids = [row[0] for row in self.db.execute('SELECT id FROM tasks')]
            tasks = [self._load(task_id) for task_id in ids]
            return sorted(tasks, key=lambda task: task['updated_at'], reverse=True)

    def read(self, task_id):
        with self.transaction():
            return self._load(task_id)

    def checkpoint(self, task_id, *, status=None, checks=None, evidence=None,
                   handoff=None, detail=None, owner=None, expected_revision=None):
        if status is not None and status not in STATUSES:
            raise TaskStoreError('Unknown task status.')
        if checks is not None:
            checks = self._checks(checks)
        if evidence is not None:
            if not isinstance(evidence, list) or len(evidence) > 100:
                raise TaskStoreError('Evidence must be a list of at most 100 entries.')
            evidence = bounded_json(evidence, 64000, 'evidence')
        if handoff is not None:
            text(handoff, 'handoff', empty=True)
        if detail is not None:
            text(detail, 'checkpoint detail', empty=True)
        if owner is not None:
            text(owner, 'lease owner', 256)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise TaskStoreError('Invalid expected revision.')
        with self.transaction():
            task = self._load(task_id)
            if expected_revision is not None and expected_revision != task['revision']:
                raise TaskStoreError('Task revision changed; read the latest checkpoint.')
            lease = task.get('lease')
            if lease and lease['owner'] != owner:
                raise TaskStoreError('Task writer lease belongs to another owner.')
            if task['status'] in ('cancelled', 'completed'):
                raise TaskStoreError('Terminal task cannot be changed.')
            if owner is not None and (not lease or lease['owner'] != owner):
                raise TaskStoreError('Task writer lease expired; claim again before writing.')
            if status == 'running' and not lease:
                raise TaskStoreError('A writer lease is required to run a task.')
            if status == 'completed' and not (evidence or task['evidence']):
                raise TaskStoreError('Completion requires verification evidence.')
            for key, value in [('status', status), ('checks', checks), ('evidence', evidence),
                               ('handoff', handoff), ('detail', detail)]:
                if value is not None:
                    task[key] = value
            task['checkpoints'].append({'at': time.time(), 'status': task['status'],
                                        'detail': task['detail'], 'handoff': task['handoff'],
                                        'evidence': task['evidence']})
            task['checkpoints'] = task['checkpoints'][-20:]
            self._save(task)
            return task

    def claim(self, task_id, owner, ttl=60):
        lease_args(owner, ttl)
        with self.transaction():
            task = self._load(task_id)
            if task['status'] in ('cancelled', 'completed'):
                raise TaskStoreError('Terminal task cannot be claimed.')
            if task.get('lease') and task['lease']['owner'] != owner:
                raise TaskStoreError('Task writer lease belongs to another owner.')
            task['lease'] = {'owner': owner, 'expires_at': time.time() + ttl,'process_id':os.getpid()}
            self._save(task)
            self.claims.add((task_id, owner))
            return task

    def release(self, task_id, owner):
        text(owner, 'lease owner', 256)
        with self.transaction():
            task = self._load(task_id)
            if not task.get('lease') or task['lease']['owner'] != owner:
                return False
            task['lease'] = None
            if task['status'] == 'running':
                task['status'] = 'partial'
                task['detail'] = 'Writer released its lease. Inspect execution evidence before resuming.'
            self._save(task)
            self.claims.discard((task_id, owner))
            return True

    def renew(self, task_id, owner, ttl=60):
        """Extend a live lease only; never reclaim an expired or revoked writer."""
        lease_args(owner, ttl)
        with self.transaction():
            task = self._load(task_id)
            if not task.get('lease') or task['lease']['owner'] != owner:
                return False
            task['lease']['expires_at'] = time.time() + ttl
            self._save(task)
            return True

    def cancel(self, task_id):
        with self.transaction():
            task = self._load(task_id)
            if task['status'] != 'completed':
                task['status'] = 'cancelled'
                task['detail'] = 'Cancelled locally. Inspect existing job evidence before resuming work.'
                self._save(task)
            # Keep a live writer lease until its in-flight callback exits.
            return task

    def reserve_operation(self, task_id, operation, owner,request=None):
        """Record before invoking a mutation; an ambiguous attempt cannot be replayed."""
        if request is not None:request=bounded_json(request,8000,'operation request preview')
        text(operation, 'operation fingerprint', 64)
        if len(operation) != 64 or any(c not in '0123456789abcdef' for c in operation):
            raise TaskStoreError('Invalid operation fingerprint.')
        with self.transaction():
            task = self._load(task_id)
            if task['status'] in ('cancelled', 'completed') or not task.get('lease') or task['lease']['owner'] != owner:
                raise TaskStoreError('A live task writer lease is required before invoking a mutation.')
            operations = task.setdefault('operations', [])
            if operation in operations:
                return False
            if len(operations) >= 1000:
                raise TaskStoreError('Task operation limit reached. Start a new reviewed task.')
            operations.append(operation)
            if request is not None:
                records=task.setdefault('operation_requests',[])
                records.append({'operation':operation,'request':request,'state':'outcome_unknown','submitted_at':time.time()})
                task['operation_requests']=records[-50:]
            self._save(task)
            return True

    def resolve_operation(self,task_id,operation,owner,result):
        with self.transaction():
            task=self._load(task_id)
            if not task.get('lease') or task['lease']['owner']!=owner:raise TaskStoreError('Task writer lease changed before recording the result.')
            for record in task.get('operation_requests',[]):
                if record['operation']==operation:
                    record['state']=str(result.get('state') or ('returned' if not result.get('error') else 'failed'))[:80]
                    record['returned_at']=time.time()
                    for key in ('job_id','edit_id','success','applied'):
                        value=result.get(key)
                        if isinstance(value,(str,bool)) or value is None:record[key]=value
                    break
            self._save(task)

    def rebind(self, task_id, workspace, expected_revision=None):
        """Local-owner operation after review, never a model or remote permission grant."""
        workspace = workspace_identity(workspace)
        with self.transaction():
            task = self._load(task_id)
            if expected_revision is not None and expected_revision != task['revision']:
                raise TaskStoreError('Task revision changed; read before rebinding.')
            if task.get('lease'):
                raise TaskStoreError('Cannot rebind a task with a live writer lease.')
            if task['status'] in ('completed', 'cancelled'):
                raise TaskStoreError('Terminal task cannot be rebound.')
            if workspace_key(task['workspace']) != workspace_key(workspace):
                raise TaskStoreError('Resume must select the same workspace root.')
            task['workspace'] = workspace
            task['status'] = 'partial'
            task['detail'] = 'Workspace rebound locally. Inspect saved evidence against the current revision before continuing.'
            self._save(task)
            return task

    def claim_workspace(self, workspace, owner, ttl=60):
        lease_args(owner, ttl)
        key = workspace_key(workspace)
        with self.transaction():
            row = self.db.execute('SELECT owner,expires,owner_pid FROM leases WHERE key=?', (key,)).fetchone()
            if row and row[1] > time.time() and row[0] != owner and process_alive(row[2]):
                raise TaskStoreError('Workspace mutation lease belongs to another writer.')
            expires = time.time() + ttl
            self.db.execute('INSERT OR REPLACE INTO leases(key,owner,expires,owner_pid) VALUES (?,?,?,?)', (key, owner, expires,os.getpid()))
            self.workspace_claims.add((key, owner))
            return {'owner': owner, 'expires_at': expires, 'workspace': workspace_identity(workspace)}

    def release_workspace(self, workspace, owner):
        text(owner, 'lease owner', 256)
        key = workspace_key(workspace)
        with self.transaction():
            changed = self.db.execute('DELETE FROM leases WHERE key=? AND owner=?', (key, owner)).rowcount
            self.workspace_claims.discard((key, owner))
            return bool(changed)

    def renew_workspace(self, workspace, owner, ttl=60):
        lease_args(owner, ttl)
        key = workspace_key(workspace)
        now = time.time()
        with self.transaction():
            return bool(self.db.execute('UPDATE leases SET expires=? WHERE key=? AND owner=? AND expires>?',
                                        (now + ttl, key, owner, now)).rowcount)

    def invalidate_workspace(self, workspace):
        with self.transaction():
            self.db.execute('DELETE FROM leases WHERE key=?', (workspace_key(workspace),))

    def close(self):
        with self.lock:
            if self.closed:
                return
            with self.transaction():
                for task_id, owner in self.claims:
                    task = self._load(task_id)
                    if task.get('lease') and task['lease']['owner'] == owner:
                        if task['status'] == 'running':
                            task['status'] = 'partial'
                            task['detail'] = 'Writer interrupted. Inspect saved evidence; no jobs were replayed.'
                        task['lease'] = None
                        self._save(task)
                for key, owner in self.workspace_claims:
                    self.db.execute('DELETE FROM leases WHERE key=? AND owner=?', (key, owner))
            self.db.close()
            self.closed = True
