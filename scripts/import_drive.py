"""Stream a reviewed Drive ZIP into content-addressed draft release assets.

Only allowlisted game/patch paths are uploaded. No career saves, backups, or APKs.
The ZIP stays on disk; members are read one at a time without full extraction.
"""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
import zipfile
from range_zip import RangeReader

REPO='Moatezsager/pes26ar-updates'
CHUNK=16*1024*1024
HERE=Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(*args):
    process=subprocess.run(['gh',*args],text=True,encoding='utf-8',capture_output=True)
    if process.returncode:
        raise RuntimeError(process.stderr.strip())
    return process.stdout


def api(path):
    return json.loads(run('api',path))


def canonical(name):
    if '\\' in name or '\x00' in name or name.startswith('/'):
        raise ValueError('Unsafe ZIP path')
    parts=PurePosixPath(name).parts
    if '..' in parts:
        raise ValueError('ZIP traversal path')
    for i,part in enumerate(parts):
        if part.casefold() in ('game','patches'):
            return '/'.join(parts[i:])
    return None


def locate(archive,expected):
    members={}
    names={n.casefold():n for n in expected}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name=names.get((canonical(info.filename) or '').casefold())
        if name is None:
            continue
        if name in members or info.flag_bits&1:
            raise ValueError('Duplicate or encrypted ZIP member: '+str(name))
        if info.file_size!=expected[name]['size']:
            raise ValueError('ZIP member size differs from reviewed copy: '+name)
        members[name]=info
    missing=set(expected)-set(members)-{'Game/img/dt05_a.img'}
    if 'Game/img/dt05_a.img' in members:
        missing.discard('Game/img/dt05_e.img')
    if missing:
        raise ValueError('Source ZIP missing required files: '+', '.join(sorted(missing)))
    return members


def selected_files(expected,members):
    # The working Arabic phone package does not require an English menu archive.
    result=dict(expected)
    if 'Game/img/dt05_e.img' not in members and 'Game/img/dt05_a.img' in members:
        result.pop('Game/img/dt05_e.img',None)
    return result


def checkpoint_valid(row,expected,remote,base_url):
    if not isinstance(row,dict) or any(row.get(k)!=expected[k] for k in ('path','size','sha256','component')):
        return False
    offset=0
    for chunk in row.get('chunks',[]):
        if not isinstance(chunk,dict):return False
        digest=chunk.get('sha256','')
        size=chunk.get('size',0)
        if not re.fullmatch('[0-9a-f]{64}',digest) or not isinstance(size,int) or not 0<size<=CHUNK:
            return False
        if chunk.get('offset')!=offset or chunk.get('urls')!=[base_url+digest+'.bin']:
            return False
        if not matches(remote.get(digest+'.bin',{}),size,digest):return False
        offset+=size
    return offset==expected['size']


def apply_visuals(data,bundle):
    plan=json.loads(bundle.read('delta.json'))
    approved=json.loads((HERE/'visual-update.json').read_text())
    if plan!=approved or len(data)!=plan['source_bytes'] or sha(data)!=plan['source_sha256']:
        raise ValueError('Visual update requires the exact reviewed dt06.img')
    result=bytearray(data)
    result.extend(bundle.read('tail.bin'))
    for edit in plan['edits']:
        offset=edit['offset']
        if offset<8 or offset>8+1442*8 or len(bytes.fromhex(edit['hex']))!=8:
            raise ValueError('Invalid AFS index delta')
        result[offset:offset+8]=bytes.fromhex(edit['hex'])
    if len(result)!=plan['output_bytes'] or sha(result)!=plan['output_sha256']:
        raise ValueError('Visual update output verification failed')
    return bytes(result)


def assets(release_id):
    pages=json.loads(run('api','--paginate','--slurp',f'repos/{REPO}/releases/{release_id}/assets?per_page=100'))
    return {item['name']:item for page in pages for item in page}


def matches(asset,size,digest):
    return asset.get('state')=='uploaded' and asset.get('size')==size and asset.get('digest')=='sha256:'+digest


def reuse_asset(existing,name,size,digest,release_id):
    asset=existing.get(name)
    if asset is None:
        return False
    if matches(asset,size,digest):
        return True
    if asset.get('state')=='starter' and asset.get('size')==size:
        if not api(f'repos/{REPO}/releases/{release_id}')['draft']:
            raise ValueError('Release is no longer a draft; refusing to remove incomplete asset')
        run('api','--method','DELETE',f'repos/{REPO}/releases/assets/{asset["id"]}')
        del existing[name]
        print('Retrying incomplete upload: '+name,flush=True)
        return False
    raise ValueError('Existing completed asset differs; it has not been removed: '+name)


def draft_release(tag,version):
    # Drafts with no published Git tag can return 404 from REST releases/tags.
    def view():
        return json.loads(run('release','view',tag,'--repo',REPO,'--json','databaseId,isDraft,tagName'))
    try:
        found=view()
    except RuntimeError as error:
        if 'release not found' not in str(error).lower() and '404' not in str(error):
            raise
        run('release','create',tag,'--repo',REPO,'--target','main','--draft','--title','PES 2026 data '+version,
            '--notes','Verified game data and visual update. Requires chunk-download-v1.')
        found=view()
    if not found['isDraft'] or found['tagName']!=tag:
        raise ValueError('Published releases are immutable; choose a new version')
    release=api(f'repos/{REPO}/releases/{found["databaseId"]}')
    if not release['draft'] or release['tag_name']!=tag:
        raise ValueError('Release state changed; refusing to upload')
    return release


def download_archive(archive_path,drive_id):
    complete=archive_path.is_file() and zipfile.is_zipfile(archive_path)
    minimum=(512*1024**2) if complete else (11*1024**3)
    if shutil.disk_usage('.').free<minimum:
        raise RuntimeError('Insufficient temporary disk; existing download has not been removed')
    if complete:
        print('Reusing completed source.zip; no Drive download needed. Member CRC and SHA-256 checks still follow.',flush=True)
        return
    import gdown
    for attempt in range(3):
        try:
            result=gdown.download(id=drive_id,output=str(archive_path),quiet=False,resume=True,use_cookies=False)
            if not result or not zipfile.is_zipfile(archive_path):
                raise RuntimeError('Google did not return a complete ZIP archive')
            return
        except Exception:
            if attempt==2:
                raise
            time.sleep(5)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--drive-id',required=True)
    parser.add_argument('--release',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,100}',args.drive_id) or not re.fullmatch(r'\d+(?:\.\d+){3}',args.release):
        raise ValueError('Invalid input')
    import fcntl
    # Retain this handle throughout the run; never delete the lock inode on exit.
    task_lock=open('.import.lock','a+')
    try:
        fcntl.flock(task_lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another import is running in this session; do not start a second process')
    archive_path=Path('source.zip')
    if archive_path.is_file() and zipfile.is_zipfile(archive_path):
        source_archive=archive_path
        print('Reusing completed source.zip; no Drive download needed.',flush=True)
    else:
        if shutil.disk_usage('.').free<512*1024**2:
            raise RuntimeError('At least 512 MiB temporary disk is required')
        source_archive=RangeReader('https://drive.usercontent.google.com/download?id='+args.drive_id+'&export=download&confirm=t',
                                   cache_dir=Path.home()/'.cache/pes26ar-drive')
        print('Reading ZIP directly from Drive with HTTP Range; no full ZIP download to temporary disk.',flush=True)
    expected={f['path']:f for f in json.loads((HERE/'expected-files.json').read_text())}
    if sum(math.ceil(f['size']/CHUNK) for f in expected.values())+3>1000:
        raise ValueError('Release asset count would exceed GitHub limit')
    tag='data-'+args.release
    release=draft_release(tag,args.release)
    existing=assets(release['id'])
    uploaded={}

    def put(path,digest):
        nonlocal existing
        size=path.stat().st_size
        if reuse_asset(existing,path.name,size,digest,release['id']):
            return
        for attempt in range(3):
            try:
                run('release','upload',tag,str(path),'--repo',REPO)
                existing[path.name]=dict(size=size,digest='sha256:'+digest,state='uploaded')
                return
            except RuntimeError:
                existing=assets(release['id'])
                if reuse_asset(existing,path.name,size,digest,release['id']):
                    return
                if attempt==2:
                    raise
                time.sleep(5*(attempt+1))

    base_url=f'https://github.com/{REPO}/releases/download/{tag}/'
    checkpoint=Path.home()/'.local/state/pes26ar'/args.release/'completed-files.json'
    checkpoint.parent.mkdir(parents=True,exist_ok=True)
    completed=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if not isinstance(completed,dict):raise ValueError('Invalid local checkpoint')
    manifest=dict(schema=1,release=args.release,status='verified',required_client_capability='chunk-download-v1',
                  chunk_size=CHUNK,files=[])
    with zipfile.ZipFile(source_archive) as archive,zipfile.ZipFile('visual-input.zip') as bundle:
        members=locate(archive,expected)
        expected=selected_files(expected,members)
        language='Game/img/dt05_a.img' if 'Game/img/dt05_a.img' in members else 'Game/img/dt05_e.img'
        with archive.open(members[language]) as menu:
            row=expected[language]
            if sha(menu.read(row['size']+1))!=row['sha256']:
                raise ValueError('Menu file differs from the reviewed Arabic/English reference: '+language)
        print('Menu profile verified: '+language,flush=True)
        for index,name in enumerate(sorted(expected,key=lambda n:expected[n]['size'])):
            row=expected[name]
            approved=dict(row)
            if name=='Game/img/dt06.img':
                visual=json.loads((HERE/'visual-update.json').read_text())
                approved.update(size=visual['output_bytes'],sha256=visual['output_sha256'])
            if checkpoint_valid(completed.get(name),approved,existing,base_url):
                manifest['files'].append(completed[name])
                for chunk in completed[name]['chunks']:
                    uploaded[chunk['sha256']+'.bin']=(chunk['size'],chunk['sha256'])
                print(f'Resumed verified file {index+1}/{len(expected)}: {name}',flush=True)
                continue
            source=archive.open(members[name]) if name in members else bundle.open('fallback/dt05_a.img')
            expected_hash=row['sha256']
            size=row['size']
            if name=='Game/img/dt06.img':
                with source:
                    original=source.read(size+1)
                source=io.BytesIO(apply_visuals(original,bundle))
                visual=json.loads((HERE/'visual-update.json').read_text())
                size=visual['output_bytes']
                expected_hash=visual['output_sha256']
            digest=hashlib.sha256()
            offset=0
            chunks=[]
            with source:
                while True:
                    block=source.read(CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    checksum=sha(block)
                    key=checksum+'.bin'
                    if key not in uploaded:
                        path=Path(key)
                        path.write_bytes(block)
                        put(path,checksum)
                        uploaded[key]=(len(block),checksum)
                        path.unlink()
                    chunks.append(dict(offset=offset,size=len(block),sha256=checksum,urls=[base_url+key]))
                    offset+=len(block)
                    if len(chunks)%8==0:
                        print(f'Parts checked: {name} {offset}/{size} bytes',flush=True)
            if offset!=size or digest.hexdigest()!=expected_hash:
                raise ValueError('Source file SHA-256 differs from reviewed copy: '+name)
            manifest['files'].append(dict(path=name,component=row['component'],size=size,sha256=expected_hash,chunks=chunks))
            completed[name]=manifest['files'][-1]
            temporary=checkpoint.with_suffix('.tmp')
            temporary.write_text(json.dumps(completed),encoding='utf-8')
            os.replace(temporary,checkpoint)
            print(f'Verified {index+1}/{len(expected)}: {name}; {len(uploaded)} unique chunks',flush=True)
    remote=assets(release['id'])
    if not all(matches(remote.get(n,{}),s,h) for n,(s,h) in uploaded.items()):
        raise ValueError('Final GitHub asset digest verification failed')
    encoded=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    Path('manifest.json').write_bytes(encoded)
    put(Path('manifest.json'),sha(encoded))
    channel=dict(schema=1,release=args.release,manifest_url=base_url+'manifest.json',manifest_sha256=sha(encoded),
                 required_client_capability='chunk-download-v1')
    Path('staging-channel.json').write_text(json.dumps(channel,indent=2)+'\n',encoding='utf-8')
    put(Path('staging-channel.json'),sha(Path('staging-channel.json').read_bytes()))
    print('DRAFT COMPLETE; all source files and GitHub object digests verified; not published',flush=True)
    print(json.dumps(channel),flush=True)


if __name__=='__main__':
    main()
