#!/usr/bin/env python3
"""Run private local history by directory, retaining aggregate evidence only."""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import time
from corpus_source import partition


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent,
                                     prefix='.checkpoint-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


parser=argparse.ArgumentParser()
parser.add_argument('--binary',required=True,type=Path)
parser.add_argument('--validator',required=True,type=Path)
parser.add_argument('--out',required=True,type=Path)
parser.add_argument('--root',action='append',required=True,help='agent=directory')
parser.add_argument('--retry',action='store_true',help='Retry only failed batches from an earlier run')
parser.add_argument('--jobs',type=int,default=1,help='Maximum independent batches running at once')
parser.add_argument('--max-files-per-batch',type=int,default=128,help='Target file count, keeping each native session together')
args=parser.parse_args()
if args.jobs<1:parser.error('--jobs must be positive')
if args.max_files_per_batch<1:parser.error('--max-files-per-batch must be positive')
os.umask(0o077)
args.out.mkdir(mode=0o700,parents=True,exist_ok=True)
os.chmod(args.out,0o700)
results_path=args.out/'counts.json'
results=json.loads(results_path.read_text()) if results_path.exists() else {}
started=time.monotonic()
batches=[]
manifest_path=args.out/'batches.json'
if manifest_path.exists():
    manifest=json.loads(manifest_path.read_text())
    if manifest['roots']!=args.root:parser.error('use a fresh output directory for a different root selection')
    batches=[(key,agent,Path(directory),files) for key,agent,directory,files in manifest['batches']]
else:
    for selection in args.root:
        agent,root=selection.split('=',1)
        for directory,dirs,files in os.walk(root,followlinks=False):
            files=[name for name in files if name.endswith(('.jsonl','.jsonl.zst','.jsonl.zstd'))]
            if not files:continue
            key=agent+'-'+hashlib.sha256(os.fsencode(directory)).hexdigest()[:20]
            if key in results or len(files)<=args.max_files_per_batch:
                batches.append((key,agent,Path(directory),files))
                continue
            for chunk in partition(agent,directory,files,args.max_files_per_batch):
                fingerprint=hashlib.sha256(b'\0'.join(os.fsencode(name) for name in sorted(chunk))).hexdigest()[:12]
                batches.append((key+'-'+fingerprint,agent,Path(directory),chunk))
    write_json(manifest_path,{'roots':args.root,'batches':[(key,agent,str(directory),files) for key,agent,directory,files in batches]})
def check_batch(batch):
    key,agent,directory,files=batch
    with tempfile.TemporaryDirectory(prefix='.input-',dir=args.out) as temporary:
        for name in files:
            Path(temporary,name).symlink_to((directory/name).resolve())
        out=args.out/key
        converted=subprocess.run([str(args.binary.resolve()),'convert','--agent',agent,temporary,'--out',str(out)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        entry={'agent':agent,'native_files':len(files),'success':converted.returncode==0,'conversion_exit':converted.returncode}
        if converted.returncode in (0,1):
            try:
                entry['conversion']=json.loads(converted.stdout)
            except ValueError:
                entry['success']=False
        if converted.returncode==0:
            checked=subprocess.run(['node',str(args.validator.resolve()),'--summary','--json',str(out)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            entry['validation_exit']=checked.returncode
            try:
                validation=json.loads(checked.stdout)
                entry['validation']={k:v for k,v in validation.items() if k in ('valid','files','records','errors','warnings','inputFailures','counts')}
                entry['success'] &= checked.returncode==0
            except ValueError:
                entry['success']=False
        return entry

pending=[(index,batch) for index,batch in enumerate(sorted(batches),1)
         if batch[0] not in results or (args.retry and not results[batch[0]].get('success'))]
with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
    futures={executor.submit(check_batch,batch):(index,batch) for index,batch in pending}
    for future in concurrent.futures.as_completed(futures):
        index,(key,agent,directory,files)=futures[future]
        entry=future.result()
        results[key]=entry
        write_json(results_path,results)
        print(json.dumps({'batch':index,'batches':len(batches),'agent':agent,'success':entry['success'],'elapsed_seconds':round(time.monotonic()-started)}),flush=True)
counts=collections.Counter()
conversion_counts=collections.Counter()
totals=collections.Counter()
by_agent={}
for entry in results.values():
    agent=entry['agent']
    group=by_agent.setdefault(agent,collections.Counter())
    group['batches']+=1
    group['native_files']+=entry['native_files']
    group['failed_batches']+=not entry['success']
    for key,value in entry.get('conversion',{}).items():
        if isinstance(value,int):group['conversion_'+key]+=value
    for key,value in entry.get('validation',{}).items():
        if key in ('files','records','errors','warnings','inputFailures'):group[key]+=value
    counts.update(entry.get('validation',{}).get('counts',{}))
    conversion_counts.update(entry.get('conversion',{}).get('diagnostics',{}))
summary={'batches':len(results),'failed_batches':sum(not e['success'] for e in results.values()),'by_agent':by_agent,'validation_codes':counts,'conversion_codes':conversion_counts,'wall_seconds':round(time.monotonic()-started),'max_child_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
write_json(args.out/'summary.json',summary)
print(json.dumps(summary,indent=2),flush=True)
raise SystemExit(1 if summary['failed_batches'] else 0)
