#!/usr/bin/env python3
"""Owner-only local target maintenance. No remote registration tool is exposed."""
import argparse
import json
import os
import sys
from pathlib import Path
from web_bridge.web.client import Bridge

def main():
    parser=argparse.ArgumentParser(description='Maintain approved challenge origins locally, then restart the launcher')
    parser.add_argument('operation',choices=['list','add','remove'])
    parser.add_argument('name',nargs='?')
    parser.add_argument('origin',nargs='?')
    parser.add_argument('--file',default=str(Path(__file__).resolve().parent/'targets.json'))
    options=parser.parse_args()
    path=Path(options.file).expanduser().resolve()
    data=json.loads(path.read_text()) if path.exists() else {}
    if options.operation=='add':
        if not options.name or not options.origin: parser.error('add requires a name and an explicitly approved origin')
        data[options.name]=options.origin
    if options.operation=='remove':
        if not options.name: parser.error('remove requires a target name')
        data.pop(options.name,None)
    validated=Bridge(data)
    if options.operation!='list':
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.new')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream: json.dump(validated.targets,stream,indent=2);stream.write('\n')
        os.replace(temporary,path)
        print('Saved approved origins. Restart with CTF_CONFIG set to this file to apply them.')
    print(json.dumps(validated.list_targets(),indent=2))

if __name__=='__main__': main()
