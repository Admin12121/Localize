"""Locally approved, bounded asynchronous commands. No shell-string execution."""
import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from workspace import WorkspaceError, Workspace, MAX_FILE, sha
from process_group import WindowsGroup,kill_posix_group

def container_arguments(name,stage,image,argv,network=False,cwd=''):
    return ['run','--rm','--pull=never','--name',name,'--init','--read-only',
            '--network=bridge' if network else '--network=none','--cap-drop=ALL',
            '--security-opt=no-new-privileges','--pids-limit=128','--memory=512m','--cpus=1',
            '--user','65534:65534','--tmpfs','/tmp:rw,nosuid,nodev,size=128m',
            '--mount',f'type=bind,source={Path(stage).resolve()},target=/workspace',
            '--workdir','/workspace'+('/'+cwd if cwd else ''),'--entrypoint',argv[0],image,*argv[1:]]

def minimal_environment():
    result={key:value for key,value in os.environ.items() if key.upper() in ('PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','LANG','LC_ALL','USERPROFILE','HOME','APPDATA','LOCALAPPDATA','TEMP','TMP')}
    result.update({'PYTHONNOUSERSITE':'1','PYTHONIOENCODING':'utf-8'})
    return result

class Jobs:
    def __init__(self,runtime,lock,valid):
        self.runtime=Path(runtime);self.runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=lock;self.valid=valid;self.items={};self.project=None;self.docker_context=None;self.docker=shutil.which('docker')
        self.session_id=secrets.token_hex(16);self.receipt_path=self.runtime/'command-receipts.sqlite3'
        with self.database() as db:
            db.execute("CREATE TABLE IF NOT EXISTS receipts (job_id TEXT PRIMARY KEY, key_hash TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL, settled INTEGER NOT NULL, submitted REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0, workspace_scope TEXT NOT NULL DEFAULT '', recovery_required INTEGER NOT NULL DEFAULT 0, summary TEXT)")
            columns={row[1] for row in db.execute('PRAGMA table_info(receipts)')}
            migration=False
            for name,declaration in (('workspace_scope',"TEXT NOT NULL DEFAULT ''"),('recovery_required','INTEGER NOT NULL DEFAULT 0'),('summary','TEXT')):
                if name not in columns:
                    db.execute('ALTER TABLE receipts ADD COLUMN '+name+' '+declaration);migration=True
            db.execute('CREATE INDEX IF NOT EXISTS receipt_recovery_scope ON receipts(workspace_scope,recovery_required)')
            # Receipts are evidence only. Never deserialize live work or signal a saved PID.
            condition='' if migration else ' WHERE settled=0 OR summary IS NULL'
            for key,raw,settled,scope,required in db.execute('SELECT job_id,result,settled,workspace_scope,recovery_required FROM receipts'+condition).fetchall():
                result=json.loads(raw)
                if not settled:
                    previous=result['state']
                    result.update(previous_state=previous,state='interrupted',success=False,outcome_unknown=True,cleanup_pending=False,
                        recovery_note='The companion stopped before execution cleanup was confirmed. Review the recorded command, execution identity, workspace changes and any retained snapshot locally. Confirm this command is stopped and reviewed in local controls before further changes; this receipt will never run automatically.')
                    result['recovered_at']=time.time()
                    required=previous in ('approved','running') or bool(result.get('execution'))
                    stage=self.runtime/('job-'+key)
                    if stage.is_dir() and not stage.is_symlink():
                        result['snapshot']={**(result.get('snapshot') or {}),'retained_locally':True,'artifact_id':key}
                elif 'recovery_required' not in result:
                    required=bool(result.get('outcome_unknown') and (result.get('previous_state') in ('approved','running') or result.get('execution')))
                if result.get('recovery_acknowledged'):required=False
                scope=result.get('workspace_scope') or scope or ''
                result.update(workspace_scope=scope,recovery_required=bool(required))
                db.execute('UPDATE receipts SET result=?,settled=1,workspace_scope=?,recovery_required=?,summary=? WHERE job_id=?',
                    (json.dumps(result),scope,int(required),json.dumps(self.summary(result)),key))
            self.compact(db)

    def workspace_scope(self,workspace):
        workspace.check_root()
        return sha(os.path.normcase(str(workspace.root)).encode())

    def unresolved(self,workspace):
        """Bounded evidence for prior work that could still mutate this project."""
        scope=self.workspace_scope(workspace)
        with self.lock,self.database() as db:
            rows=db.execute("SELECT summary FROM receipts WHERE recovery_required=1 AND (workspace_scope=? OR workspace_scope='') ORDER BY submitted LIMIT 100",(scope,)).fetchall()
            return [{'job_id':item['job_id'],'execution':item.get('execution'),'recovery_note':item.get('recovery_note','Review this interrupted execution locally.'),
                     'workspace_scope':item.get('workspace_scope',''),'recovery_required':True} for item in (json.loads(row[0]) for row in rows)]

    def acknowledge_recovery(self,key,workspace,allow_unbound=False):
        """Owner confirmation only: never infer process death or signal a saved PID."""
        if type(allow_unbound) is not bool:raise WorkspaceError('Legacy recovery acknowledgement must be explicitly true or false.')
        scope=self.workspace_scope(workspace)
        with self.lock,self.database() as db:
            row=db.execute('SELECT result,workspace_scope FROM receipts WHERE job_id=?',(key,)).fetchone()
            if not row:raise WorkspaceError('Unknown command receipt in this local companion.')
            result=json.loads(row[0]);recorded=result.get('workspace_scope') or row[1] or ''
            if (recorded and recorded!=scope) or (not recorded and not allow_unbound):
                raise WorkspaceError('This recovery receipt is not bound to the selected project. Review its original project locally; unbound legacy receipts require explicit local migration confirmation.')
            if key in self.items or result.get('session_id')==self.session_id or result.get('state')!='interrupted' or not result.get('outcome_unknown'):
                raise WorkspaceError('Only interrupted historical commands can be acknowledged for recovery.')
            if not result.get('recovery_acknowledged'):
                result['recovery_acknowledged']={'confirmed_at':time.time(),'confirmation':'stopped/reviewed','legacy_unbound':not bool(recorded)}
            result['recovery_required']=False
            db.execute('UPDATE receipts SET result=?,recovery_required=0,summary=? WHERE job_id=?',(json.dumps(result),json.dumps(self.summary(result)),key))
            return result

    def summary(self,result):
        request=result['request']
        label=result.get('label') or request.get('command')
        if not label:label=' '.join([Path(request['argv'][0]).name,*request['argv'][1:]]) if request.get('argv') else 'Archived command'
        row={'job_id':result['job_id'],'state':result['state'],'label':label[:160],'environment':request['environment'],
             'output_length':len(result['output']),'exit_code':result.get('exit_code'),'session_id':result['session_id'],
             'workspace_scope':result.get('workspace_scope',''),'recovery_required':bool(result.get('recovery_required'))}
        for name in ('outcome_unknown','history_archived','recovery_acknowledged','recovery_note','execution'):
            if name in result:row[name]=dict(result[name]) if isinstance(result[name],dict) else result[name]
        return row

    @contextmanager
    def database(self):
        # Connections never outlive one short operation, including worker cleanup.
        db=None
        try:
            db=sqlite3.connect(self.receipt_path,timeout=10)
            db.execute('PRAGMA synchronous=FULL')
            with db:yield db
        except sqlite3.Error:
            raise WorkspaceError('Command receipt storage is unavailable. Check local runtime storage and review any existing command outcome before retrying.') from None
        finally:
            if db is not None:db.close()

    def close(self):
        # No shared database handle can race an in-flight command finalizer.
        pass

    def result(self,job):
        result=copy.deepcopy({k:job[k] for k in ('job_id','state','request','output','truncated','changes','snapshot','submitted_at','started_at','finished_at','execution','success','session_id','workspace_scope')})
        result['recovery_required']=False
        result['cleanup_pending']=not job['settled'].is_set() and job['state'] in ('cancelled','timed_out')
        if 'exit_code' in job:result['exit_code']=job['exit_code']
        return result

    def persist(self,job,settled=None):
        result=self.result(job)
        result['output']=result['output'][:64_000]
        # Proposal content remains in workspace approvals, not execution history.
        result['change_summary']={'count':len(result['changes']),'unapplied_count':sum('error' in item for item in result['changes'])}
        result['changes']=[{k:v for k,v in item.items() if k in ('path','edit_id','operation_id','category','error','approval_required','count')} for item in result['changes'][:64]]
        result['label']=(result['request'].get('command') or (' '.join([Path(result['request']['argv'][0]).name,*result['request']['argv'][1:]])))[:160]
        confirmed=job['settled'].is_set() if settled is None else settled
        if confirmed:result['cleanup_pending']=False
        with self.database() as db:
            db.execute('INSERT INTO receipts(job_id,key_hash,fingerprint,result,settled,submitted,workspace_scope,recovery_required,summary) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET result=excluded.result,settled=excluded.settled,summary=excluded.summary',
                (job['job_id'],job['key_hash'],job['fingerprint'],json.dumps(result),int(confirmed),job['submitted_at'],job['workspace_scope'],0,json.dumps(self.summary(result))))
            self.compact(db)

    def compact(self,db):
        # Keep full bounded output for the newest 160 receipts. Tombstone keys
        # and execution evidence are never deleted, so rotation cannot replay work.
        rows=db.execute('SELECT job_id,result FROM receipts WHERE settled=1 AND archived=0 AND job_id NOT IN (SELECT job_id FROM receipts ORDER BY submitted DESC LIMIT 160)').fetchall()
        for key,raw in rows:
            result=json.loads(raw)
            snapshot=result.get('snapshot')
            retained={k:v for k,v in snapshot.items() if k in ('retained_locally','artifact_id')} if snapshot and snapshot.get('retained_locally') else None
            result.update(output='',changes=[],snapshot=retained,history_archived=True)
            result['request']={k:v for k,v in result['request'].items() if k in ('environment','generation')}
            db.execute('UPDATE receipts SET result=?,archived=1,summary=? WHERE job_id=?',(json.dumps(result),json.dumps(self.summary(result)),key))

    def stored(self,key):
        with self.database() as db:
            row=db.execute('SELECT fingerprint,result FROM receipts WHERE job_id=?',(key,)).fetchone()
        if row:return {'fingerprint':row[0],'result':json.loads(row[1])}
        raise WorkspaceError('Unknown command receipt in this local companion.')


    def container_ready(self,image):
        if not self.docker:raise WorkspaceError('Docker is not installed; isolated execution is unavailable.')
        try:
            docker_env=minimal_environment();docker_env.update({k:v for k,v in os.environ.items() if k in ('DOCKER_CONTEXT','DOCKER_CONFIG')})
            options={'capture_output':True,'text':True,'timeout':8,'env':docker_env,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {})}
            selected=subprocess.run([self.docker,'context','show'],**options)
            if selected.returncode:raise WorkspaceError('Unable to resolve your local Docker context.')
            self.docker_context=selected.stdout.strip()
            context=subprocess.run([self.docker,'context','inspect',self.docker_context,'--format','{{.Endpoints.docker.Host}}'],**options)
            if context.returncode or not context.stdout.strip().startswith(('unix://','npipe://')):raise WorkspaceError('Use a local Docker engine for isolated commands.')
            engine=subprocess.run([self.docker,'--context',self.docker_context,'info','--format','{{.OSType}}'],**options)
            if engine.returncode or engine.stdout.strip()!='linux':raise WorkspaceError('Start Docker with Linux containers before enabling isolated commands.')
            result=subprocess.run([self.docker,'--context',self.docker_context,'image','inspect',image,'--format','{{.Id}}'],**options)
            if result.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}',result.stdout.strip()):raise WorkspaceError('Prepare the selected container image locally first. No image was pulled.')
            return result.stdout.strip()
        except (OSError,subprocess.TimeoutExpired):raise WorkspaceError('Docker readiness check failed or timed out; no host fallback was used.') from None

    def request(self,argv,cwd,timeout,environment,idempotency_key,workspace,generation,network,image,auto=False,write=False,auto_write=False,metadata=None):
        if not isinstance(argv,list) or not 1<=len(argv)<=50 or any(not isinstance(x,str) or len(x)>(30000 if metadata and metadata.get('command') is not None else 4096) or '\0' in x for x in argv) or not argv[0]: raise WorkspaceError('Use an executable and up to 49 bounded string arguments.')
        if environment not in ('host','container','docker'): raise WorkspaceError('Choose container or host execution.')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=3600: raise WorkspaceError('Timeout must be 1–3600 seconds within your local profile limit.')
        if not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',idempotency_key): raise WorkspaceError('Use a unique 8–100 character idempotency key.')
        workspace.parts(cwd,True)
        with workspace.parent(workspace.parts(cwd,True)): pass
        request={'argv':list(argv),'cwd':cwd,'timeout':timeout,'environment':environment,'generation':generation,'network':network,'image':image}
        request.update(metadata or {})
        binding={'request':request,'workspace_root':os.path.normcase(str(workspace.root)),'workspace_identity':workspace.identity,
                 'session_id':self.session_id,'auto':auto,'write':write,'auto_write':auto_write}
        fingerprint=sha(json.dumps(binding,sort_keys=True).encode());key_hash=sha(idempotency_key.encode())
        with self.lock:
            with self.database() as db:
                previous=db.execute('SELECT job_id,fingerprint FROM receipts WHERE key_hash=?',(key_hash,)).fetchone()
            if previous:
                key,old_fingerprint=previous
                if old_fingerprint!=fingerprint:raise WorkspaceError('An idempotency key cannot be reused for a changed command, workspace, policy or companion session. Review the original local receipt before preparing a new request.')
                return self.status(key)
            if sum(item['state'] in ('pending','approved','running') for item in self.items.values())>=30: raise WorkspaceError('Thirty commands are active; wait for completion or cancel one.')
            if len(self.items)>=200:
                for old_key,old_job in list(self.items.items()):
                    if old_job['settled'].is_set():
                        del self.items[old_key]
                        if len(self.items)<160:break
            if environment=='host':
                executable=shutil.which(argv[0],path=minimal_environment().get('PATH')) if not os.path.isabs(argv[0]) else argv[0]
                if not executable or not Path(executable).is_file(): raise WorkspaceError('Executable is not available on this computer.')
                if Path(executable).suffix.lower() in ('.bat','.cmd'): raise WorkspaceError('Batch files require an explicitly approved cmd.exe invocation.')
                request['argv'][0]=str(Path(executable).resolve())
            elif environment=='container':
                request['image_id']=self.container_ready(image);request['docker_context']=self.docker_context
            else:
                if not self.project:raise WorkspaceError('Configure a Docker project locally first.')
                self.project.validate_workspace(workspace)
            key=secrets.token_hex(16)
            self.items[key]={'job_id':key,'state':'pending','request':request,'fingerprint':fingerprint,'key_hash':key_hash,'session_id':self.session_id,'workspace_scope':self.workspace_scope(workspace),'expires':time.monotonic()+300,'workspace':workspace,'write':write,'auto_write':auto_write,'output':'','process':None,'group':None,'container':None,'changes':[],'truncated':False,'snapshot':None,'submitted_at':time.time(),'started_at':None,'finished_at':None,'execution':None,'success':None,'settled':threading.Event()}
            try:self.persist(self.items[key])
            except Exception:
                del self.items[key]
                raise
            if auto and environment in ('container','docker'): self.approve(key,True)
            return self.status(key)

    def expire(self,job):
        if job['state']=='pending' and time.monotonic()>job['expires']:
            job.update(state='expired',success=False,finished_at=time.time())
            self.persist(job,settled=True);job['settled'].set()

    def summaries(self):
        """Read compact dashboard rows without loading historical command output."""
        with self.lock:
            for job in self.items.values():self.expire(job)
            with self.database() as db:
                saved=db.execute('SELECT job_id,summary FROM receipts ORDER BY submitted DESC LIMIT 200').fetchall()
            return [self.summary(self.items[key]) if key in self.items else json.loads(raw) for key,raw in saved]

    def pending_count(self):
        with self.lock:
            for job in self.items.values():self.expire(job)
            return sum(job['state']=='pending' for job in self.items.values())

    def status(self,key,output_offset=0):
        with self.lock:
            job=self.items.get(key)
            if job:
                self.expire(job);result=self.result(job)
            else:result=self.stored(key)['result']
            output=result['output']
            if type(output_offset) is not int or not 0<=output_offset<=len(output):raise WorkspaceError('Invalid output offset.')
            result.update(output=output[output_offset:],output_offset=output_offset,next_output_offset=len(output))
            return result

    def approve(self,key,allow):
        with self.lock:
            status=self.status(key)
            if key not in self.items:raise WorkspaceError('Historical command receipts cannot be approved. Review the prior outcome locally before creating a new request.')
            job=self.items[key]
            if status['state']!='pending' or not self.valid(job['request']['generation']): raise WorkspaceError('Command approval is expired, revoked, or already used.')
            if allow and self.unresolved(job['workspace']):
                raise WorkspaceError('An interrupted command may still be running for this project. Review it and confirm it is stopped in local controls before starting another command.')
            if allow and getattr(self,'on_approve',None):self.on_approve(key)
            job['state']='approved' if allow else 'denied'
            if not allow:job.update(success=False,finished_at=time.time())
            try:self.persist(job,settled=not allow)
            except Exception:
                job['state']='pending'
                if allow and getattr(self,'on_finish',None):
                    try:self.on_finish(key)
                    except ValueError:pass
                raise
            if not allow:job['settled'].set()
            if allow: threading.Thread(target=self.run,args=(key,),daemon=True).start()
            return self.status(key)

    def cancel(self,key,reason='cancelled'):
        with self.lock:
            self.status(key)
            if key not in self.items:return self.status(key)
            job=self.items[key]
            if job['state'] not in ('pending','approved','running'): return self.status(key)
            previous_state=job['state'];job['state']=reason;job['success']=False;job['finished_at']=time.time(); process=job['process'];container=job['container']
            receipt_error=None
            try:self.persist(job,settled=previous_state=='pending')
            except WorkspaceError as exc:receipt_error=exc
            if previous_state=='pending':job['settled'].set()
        if job['request']['environment']=='docker' and self.project:self.project.cancel(key)
        if container and self.docker:
            try: subprocess.run([self.docker,'--context',job['request'].get('docker_context','default'),'rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
            except (OSError,subprocess.TimeoutExpired): pass
        if process:
            try:
                if os.name=='nt' and job['group']:job['group'].kill()
                elif os.name!='nt':kill_posix_group(process.pid)
                elif process.poll() is None:process.kill()
            except OSError:
                if process.poll() is None:process.kill()
        with self.lock:self.persist(job)
        if receipt_error:raise receipt_error
        return self.status(key)

    def revoke(self):
        failure=None
        for key in list(self.items):
            try:self.cancel(key)
            except WorkspaceError as exc:failure=exc
        if failure:raise failure

    def run(self,key):
        job=self.items[key]; request=job['request'];workspace=job['workspace'];stage=self.runtime/('job-'+key)
        timer=None
        try:
            snapshot=None
            with self.lock:
                if job['state']!='approved' or not self.valid(request['generation']):return
            if request['environment']=='container':
                if sum(p.is_dir() for p in self.runtime.glob('job-*'))>=10:raise WorkspaceError('Ten retained command snapshots exist. Inspect/discard them in local controls before more snapshot jobs.')
                snapshot=workspace.snapshot(stage)
                # Docker's unprivileged user must be able to traverse its isolated copy.
                for folder,dirs,files in os.walk(stage):
                    os.chmod(folder,0o777)
                    for name in files:
                        relative=(Path(folder)/name).relative_to(stage).as_posix()
                        os.chmod(Path(folder)/name,0o777 if snapshot['modes'].get(relative,0)&0o111 or name.endswith('.sh') else 0o666)
                argv=[self.docker,'--context',request['docker_context'],*container_arguments('web-bridge-'+key,stage,request['image_id'],request['argv'],request['network'],request['cwd'])]
                cwd=self.runtime
            elif request['environment']=='docker':
                self.project.validate_workspace(workspace)
                argv=self.project.build_command(key,request['argv'],request['cwd']);cwd=self.runtime
            else:
                argv=request['argv'];cwd=workspace.root.joinpath(*workspace.parts(request['cwd'],True))
            with self.lock:
                if job['state']!='approved' or not self.valid(request['generation']): return
                job['container']='web-bridge-'+key if snapshot is not None else None
                if os.name=='nt' and request['environment']=='host' and request.get('shell')=='cmd':
                    argv=subprocess.list2cmdline([argv[0]])+' /d /s /c '+chr(34)+request['command']+chr(34)
                process=subprocess.Popen(argv,cwd=cwd,env=minimal_environment(),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**({'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|0x4} if os.name=='nt' else {'start_new_session':True}))
                job['process']=process;job['state']='running';job['started_at']=time.time()
                job['execution']={'pid':process.pid,'environment':request['environment'],'container':job['container'],'docker_context':request.get('docker_context'),'started_at':job['started_at']}
                if request['environment']=='docker':
                    identity=self.project._jobs.get(key,{})
                    job['execution'].update(container=identity.get('container_id'),docker_context=identity.get('context'),execution_id=key)
                if snapshot is not None:job['snapshot']={k:snapshot[k] for k in ('files','bytes','omitted_count','omitted_paths','exclusions')}
                try:
                    self.persist(job)
                    job['group']=WindowsGroup(process) if os.name=='nt' else None
                except Exception:process.kill();process.wait();raise
            timer=threading.Timer(request['timeout'],lambda:self.cancel(key,'timed_out'));timer.daemon=True;timer.start()
            captured=bytearray()
            while True:
                block=process.stdout.read1(4096)
                if not block: break
                with self.lock:
                    room=64_000-len(captured)
                    if room>0:captured.extend(block[:room]);job['output']=captured.decode('utf-8',errors='replace')
                    if len(block)>room:job['truncated']=True
                    if room>0 or not job.get('output_saved'):self.persist(job);job['output_saved']=True
            process.wait()
            with self.lock:
                job['exit_code']=process.returncode
                if job['state'] in ('cancelled','timed_out') or not self.valid(request['generation']): return
                if snapshot is not None:
                    staged=Workspace(stage,'staged')
                    remaining=set(snapshot['hashes']);changed_count=0;omissions=[]
                    for name in staged.walk(omissions):
                        remaining.discard(name)
                        try:
                            raw=staged._read(name)
                            if raw is not None and sha(raw)==snapshot['hashes'].get(name):continue
                            changed_count+=1
                            if changed_count>20:continue
                            if not job['write']:raise WorkspaceError('File synchronization is disabled locally; inspect the retained snapshot.')
                            changed=staged.read(name)
                            proposal=workspace.propose(name,changed['text'],snapshot['hashes'].get(name))
                            if job['auto_write']:proposal['result']=workspace.apply(proposal['edit_id']);proposal['approval_required']=False
                            job['changes'].append(proposal)
                        except WorkspaceError as exc: job['changes'].append({'path':name,'category':'unapplied','error':str(exc)})
                    if changed_count>20:job['changes'].append({'error':'More than 20 changed files; remaining changes were not proposed.'})
                    if omissions:job['changes'].append({'category':'excluded','paths':omissions[:100],'count':len(omissions),'truncated':len(omissions)>100,'error':'Excluded/unsafe staged outputs were not synchronized.'})
                    if len(remaining)>20:job['changes'].append({'category':'deleted_unapplied','count':len(remaining)-20,'error':'Deletion proposal limit reached; remaining deletions were not applied.'})
                    for name in sorted(remaining)[:20]:
                        try:
                            target=stage.joinpath(*name.split('/'))
                            if target.exists() or target.is_symlink():raise WorkspaceError('Staged path changed type or became excluded; host file preserved.')
                            if not job['write']:raise WorkspaceError('File synchronization is disabled locally.')
                            if not getattr(self,'file_operations',None):raise WorkspaceError('Deletion requires a filesystem approval.')
                            job['changes'].append(self.file_operations.propose('delete',name,expected_sha256=snapshot['hashes'][name]))
                        except WorkspaceError as exc:job['changes'].append({'path':name,'error':str(exc)})
                    if any('error' in item for item in job['changes']):job['artifact_retained']=True;job['snapshot']['retained_locally']=True;job['snapshot']['artifact_id']=key
                job['success']=process.returncode==0
                job['terminal_state']='completed' if job['success'] else 'failed'
                job['finished_at']=time.time()
        except Exception as exc:
            if stage.exists():
                job['artifact_retained']=True
                if job['snapshot'] is None:job['snapshot']={}
                job['snapshot'].update(retained_locally=True,artifact_id=key)
            with self.lock:
                if job['state'] not in ('cancelled','timed_out'):
                    job['terminal_state']='failed';job['success']=False;job['finished_at']=time.time()
                    if isinstance(exc,WorkspaceError):job['output']=str(exc)
                    elif isinstance(exc,(OSError,subprocess.SubprocessError)):
                        job['output']='Command launch/execution failed: '+type(exc).__name__+' (OS error '+str(getattr(exc,'winerror',None) or getattr(exc,'errno',None))+'). Check executable, working directory and local permissions.'
                    else:job['output']='Command failed ('+type(exc).__name__+'). Check local prerequisites and logs.'
        finally:
            if timer:timer.cancel()
            if job['group']:job['group'].close()
            elif os.name!='nt' and job['process']:kill_posix_group(job['process'].pid)
            if request['environment']=='docker' and self.project:self.project.finish(key)
            if getattr(self,'on_finish',None):
                try:self.on_finish(key)
                except ValueError:pass
            if stage.exists() and not job.get('artifact_retained'):shutil.rmtree(stage,ignore_errors=True)
            with self.lock:
                if job['state'] not in ('cancelled','timed_out') and job.get('terminal_state'):job['state']=job.pop('terminal_state')
                try:self.persist(job,settled=True)
                finally:job['settled'].set()
