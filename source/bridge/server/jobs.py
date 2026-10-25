"""Locally approved, bounded asynchronous commands. No shell-string execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
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
    result={key:value for key,value in os.environ.items() if key.upper() in ('PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','LANG','LC_ALL')}
    result.update({'PYTHONNOUSERSITE':'1','PYTHONIOENCODING':'utf-8'})
    return result

class Jobs:
    def __init__(self,runtime,lock,valid):
        self.runtime=Path(runtime);self.runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=lock;self.valid=valid;self.items={};self.keys={};self.docker=shutil.which('docker')

    def container_ready(self,image):
        if not self.docker:raise WorkspaceError('Docker is not installed; isolated execution is unavailable.')
        try:
            options={'capture_output':True,'text':True,'timeout':8,'env':minimal_environment(),**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {})}
            context=subprocess.run([self.docker,'context','inspect','--format','{{.Endpoints.docker.Host}}'],**options)
            if context.returncode or not context.stdout.strip().startswith(('unix://','npipe://')):raise WorkspaceError('Use a local Docker engine for isolated commands.')
            engine=subprocess.run([self.docker,'info','--format','{{.OSType}}'],**options)
            if engine.returncode or engine.stdout.strip()!='linux':raise WorkspaceError('Start Docker with Linux containers before enabling isolated commands.')
            result=subprocess.run([self.docker,'image','inspect',image,'--format','{{.Id}}'],**options)
            if result.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}',result.stdout.strip()):raise WorkspaceError('Prepare the selected container image locally first. No image was pulled.')
            return result.stdout.strip()
        except (OSError,subprocess.TimeoutExpired):raise WorkspaceError('Docker readiness check failed or timed out; no host fallback was used.') from None

    def request(self,argv,cwd,timeout,environment,idempotency_key,workspace,generation,network,image,auto=False,write=False,auto_write=False):
        if not isinstance(argv,list) or not 1<=len(argv)<=50 or any(not isinstance(x,str) or len(x)>4096 or '\0' in x for x in argv) or not argv[0]: raise WorkspaceError('Use an executable and up to 49 bounded string arguments.')
        if environment not in ('host','container'): raise WorkspaceError('Choose container or host execution.')
        if not isinstance(timeout,(int,float)) or not 1<=timeout<=120: raise WorkspaceError('Timeout must be 1–120 seconds.')
        if not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',idempotency_key): raise WorkspaceError('Use a unique 8–100 character idempotency key.')
        workspace.parts(cwd,True)
        with workspace.parent(workspace.parts(cwd,True)): pass
        request={'argv':list(argv),'cwd':cwd,'timeout':timeout,'environment':environment,'generation':generation,'network':network,'image':image}
        fingerprint=sha(json.dumps(request,sort_keys=True).encode())
        with self.lock:
            if idempotency_key in self.keys:
                key=self.keys[idempotency_key];old=self.items[key]
                if old['fingerprint']!=fingerprint: raise WorkspaceError('An idempotency key cannot be reused for a changed command or policy.')
                return self.status(key)
            if len(self.items)>=30: raise WorkspaceError('Session job limit reached; restart the companion to begin a new session.')
            if environment=='host':
                executable=shutil.which(argv[0],path=minimal_environment().get('PATH')) if not os.path.isabs(argv[0]) else argv[0]
                if not executable or not Path(executable).is_file(): raise WorkspaceError('Executable is not available on this computer.')
                if Path(executable).suffix.lower() in ('.bat','.cmd'): raise WorkspaceError('Batch files require an explicitly approved cmd.exe invocation.')
                request['argv'][0]=str(Path(executable).resolve())
            else:request['image_id']=self.container_ready(image)
            key=secrets.token_hex(16)
            self.items[key]={'job_id':key,'state':'pending','request':request,'fingerprint':fingerprint,'expires':time.monotonic()+300,'workspace':workspace,'write':write,'auto_write':auto_write,'output':'','process':None,'group':None,'container':None,'changes':[],'truncated':False,'snapshot':None}
            self.keys[idempotency_key]=key
            if auto and environment=='container': self.approve(key,True)
            return self.status(key)

    def expire(self,job):
        if job['state']=='pending' and time.monotonic()>job['expires']:job['state']='expired'

    def summaries(self):
        """Small local dashboard rows. Output and exact requests are fetched on demand."""
        with self.lock:
            rows=[]
            for job in reversed(list(self.items.values())):
                self.expire(job)
                rows.append({'job_id':job['job_id'],'state':job['state'],
                             'label':(' '.join([Path(job['request']['argv'][0]).name,*job['request']['argv'][1:]]))[:160],
                             'environment':job['request']['environment'],
                             'output_length':len(job['output']),'exit_code':job.get('exit_code')})
            return rows

    def pending_count(self):
        with self.lock:
            for job in self.items.values():self.expire(job)
            return sum(job['state']=='pending' for job in self.items.values())

    def status(self,key):
        with self.lock:
            job=self.items.get(key)
            if not job: raise WorkspaceError('Unknown job in this companion session.')
            self.expire(job)
            return copy.deepcopy({k:job[k] for k in ('job_id','state','request','output','truncated','changes','snapshot')}) | ({'exit_code':job['exit_code']} if 'exit_code' in job else {})

    def approve(self,key,allow):
        with self.lock:
            status=self.status(key);job=self.items[key]
            if status['state']!='pending' or not self.valid(job['request']['generation']): raise WorkspaceError('Command approval is expired, revoked, or already used.')
            job['state']='approved' if allow else 'denied'
            if allow: threading.Thread(target=self.run,args=(key,),daemon=True).start()
            return self.status(key)

    def cancel(self,key):
        with self.lock:
            self.status(key);job=self.items[key]
            if job['state'] not in ('pending','approved','running'): return self.status(key)
            job['state']='cancelled'; process=job['process'];container=job['container']
        if container and self.docker:
            try: subprocess.run([self.docker,'rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
            except (OSError,subprocess.TimeoutExpired): pass
        if process:
            try:
                if os.name=='nt' and job['group']:job['group'].kill()
                elif os.name!='nt':kill_posix_group(process.pid)
                elif process.poll() is None:process.kill()
            except OSError:
                if process.poll() is None:process.kill()
        return self.status(key)

    def revoke(self):
        for key in list(self.items): self.cancel(key)

    def run(self,key):
        job=self.items[key]; request=job['request'];workspace=job['workspace'];stage=self.runtime/('job-'+key)
        timer=None
        try:
            snapshot=None
            if request['environment']=='container':
                snapshot=workspace.snapshot(stage)
                # Docker's unprivileged user must be able to traverse its isolated copy.
                for folder,dirs,files in os.walk(stage):
                    os.chmod(folder,0o777)
                    for name in files:
                        relative=(Path(folder)/name).relative_to(stage).as_posix()
                        os.chmod(Path(folder)/name,0o777 if snapshot['modes'].get(relative,0)&0o111 or name.endswith('.sh') else 0o666)
                argv=[self.docker,*container_arguments('web-bridge-'+key,stage,request['image_id'],request['argv'],request['network'],request['cwd'])]
                cwd=self.runtime
            else:
                argv=request['argv'];cwd=workspace.root.joinpath(*workspace.parts(request['cwd'],True))
            with self.lock:
                if job['state']!='approved' or not self.valid(request['generation']): return
                job['container']='web-bridge-'+key if snapshot is not None else None
                process=subprocess.Popen(argv,cwd=cwd,env=minimal_environment(),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**({'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|0x4} if os.name=='nt' else {'start_new_session':True}))
                try:job['group']=WindowsGroup(process) if os.name=='nt' else None
                except Exception:process.kill();process.wait();raise
                job['process']=process;job['state']='running'
                if snapshot is not None:job['snapshot']={k:snapshot[k] for k in ('files','bytes','omitted_count','omitted_paths','exclusions')}
            timer=threading.Timer(request['timeout'],lambda:self.cancel(key));timer.daemon=True;timer.start()
            captured=bytearray()
            while True:
                block=process.stdout.read1(4096)
                if not block: break
                with self.lock:
                    room=64_000-len(captured)
                    if room>0:captured.extend(block[:room]);job['output']=captured.decode('utf-8',errors='replace')
                    if len(block)>room:job['truncated']=True
            process.wait()
            with self.lock:
                job['exit_code']=process.returncode
                if job['state']=='cancelled' or not self.valid(request['generation']): return
                if snapshot is not None and job['write']:
                    staged=Workspace(stage,'staged')
                    remaining=set(snapshot['hashes']);changed_count=0
                    for name in staged.walk():
                        remaining.discard(name)
                        try:
                            raw=staged._read(name)
                            if raw is not None and sha(raw)==snapshot['hashes'].get(name):continue
                            changed_count+=1
                            if changed_count>20:continue
                            changed=staged.read(name)
                            proposal=workspace.propose(name,changed['text'],snapshot['hashes'].get(name))
                            if job['auto_write']:proposal['result']=workspace.apply(proposal['edit_id']);proposal['approval_required']=False
                            job['changes'].append(proposal)
                        except WorkspaceError as exc: job['changes'].append({'path':name,'error':str(exc)})
                    if changed_count>20:job['changes'].append({'error':'More than 20 changed files; remaining changes were not proposed.'})
                    for name in sorted(remaining)[:20]:job['changes'].append({'path':name,'error':'File deleted in staged copy; deletion is not applied automatically.'})
                job['state']='completed'
        except Exception as exc:
            with self.lock:
                if job['state']!='cancelled':job['state']='failed';job['output']=str(exc) if isinstance(exc,WorkspaceError) else 'Command could not start or finish; check local prerequisites and permissions.'
        finally:
            if timer:timer.cancel()
            if job['group']:job['group'].close()
            elif os.name!='nt' and job['process']:kill_posix_group(job['process'].pid)
            if stage.exists():shutil.rmtree(stage,ignore_errors=True)
