"""Copy the pinned public game release server-to-server and optionally stream a split ZIP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
import urllib.request
import zipfile
from import_drive import REPO, CHUNK, api, assets, draft_release, matches, reuse_asset, run, sha

SOURCE='https://github.com/Moatezsager/pes26ar-updates/releases/download/data-2026.11.21.1/manifest.json'
SOURCE_SHA='220f9c06bafefff416bd4c1045746d4af33133bd8195f22babcf108657897e75'
MAX_VOLUME=1400*1024*1024

def fetch(url,limit):
    if not url.startswith('https://'):raise ValueError('HTTPS required')
    with urllib.request.urlopen(url,timeout=120) as response:
        if response.status!=200:raise ValueError('Unexpected source response')
        data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Source exceeded expected size')
    return data

def validate(manifest):
    if manifest.get('schema')!=1 or manifest.get('status')!='verified' or manifest.get('required_client_capability')!='chunk-download-v1':raise ValueError('Unsupported source manifest')
    files=manifest['files'];names=set();objects={}
    if not 1<=len(files)<=2000:raise ValueError('Invalid file count')
    for row in files:
        name=row['path'];path=PurePosixPath(name)
        if '\\' in name or path.is_absolute() or '..' in path.parts or name.casefold() in names:raise ValueError('Unsafe or duplicate path')
        names.add(name.casefold())
        game=name.startswith('Game/img/') and len(path.parts)==3 and path.suffix in ('.img','.sfd') or name=='Game/pes2013_limpo.exe'
        patch=name.startswith('Patches/ELENCOD2026_01/save/') and len(path.parts)==4 and re.fullmatch(r'[A-Za-z0-9_]+\.bin',path.name) and not re.fullmatch(r'(?:OPTION|REPLAY\d*|ML\d*|BL\d*)\.BIN',path.name.upper())
        if not (game or patch) or not re.fullmatch('[0-9a-f]{64}',row['sha256']) or not 0<row['size']<=8*1024**3:raise ValueError('Unapproved file')
        offset=0
        for part in row['chunks']:
            digest=part['sha256'];size=part['size']
            if not re.fullmatch('[0-9a-f]{64}',digest) or not 0<size<=CHUNK or part['offset']!=offset:raise ValueError('Invalid chunk')
            if not part['urls'] or any(not u.startswith(('https://gitlab.com/api/v4/projects/89205177/packages/generic/pes26ar-data/','https://github.com/Moatezsager/pes26ar-updates/releases/download/')) for u in part['urls']):raise ValueError('Unapproved source')
            if digest in objects and objects[digest]['size']!=size:raise ValueError('Conflicting chunk size')
            objects[digest]=part;offset+=size
        if offset!=row['size']:raise ValueError('Incomplete chunk layout')
    return objects

def download(part):
    error=None
    for attempt in range(5):
        for url in part['urls']:
            try:
                data=fetch(url,part['size'])
                if len(data)!=part['size'] or sha(data)!=part['sha256']:raise ValueError('Source SHA-256 mismatch')
                return data
            except (OSError,ValueError) as exc:error=exc
        time.sleep(min(20,2**attempt))
    raise RuntimeError('Source failed: '+part['sha256']) from error

def mirrored_manifest(source,version,base):
    result=json.loads(json.dumps(source));result['release']=version
    for row in result['files']:
        for part in row['chunks']:
            url=base+part['sha256']+'.bin'
            part['urls']=[url]+[u for u in part['urls'] if u!=url]
    validate(result)
    return result

class Volumes(io.RawIOBase):
    """Unseekable ZIP output, bounded disk, deterministic volumes for safe reruns."""
    def __init__(self,directory,prefix,put,limit=MAX_VOLUME):
        self.directory=directory;self.prefix=prefix;self.put=put;self.limit=limit;self.position=0;self.used=0;self.index=0;self.stream=None;self.parts=[]
    def writable(self):return True
    def seekable(self):return False
    def tell(self):return self.position
    def _finish(self):
        if self.stream is None:return
        self.stream.flush();os.fsync(self.stream.fileno());self.stream.close();self.stream=None
        with self.path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        self.put(self.path,digest);self.parts.append(dict(name=self.path.name,size=self.used,sha256=digest));self.path.unlink();self.used=0
    def write(self,data):
        size=len(data);view=memoryview(data)
        while view:
            if self.stream is None:
                self.index+=1;self.path=self.directory/f'{self.prefix}.zip.{self.index:03}';self.stream=self.path.open('xb')
            n=min(len(view),self.limit-self.used);self.stream.write(view[:n]);view=view[n:];self.used+=n;self.position+=n
            if self.used==self.limit:self._finish()
        return size
    def finish(self):self._finish();return self.parts

def archive(files,directory,prefix,put,get=download,limit=MAX_VOLUME):
    sink=Volumes(directory,prefix,put,limit)
    try:
        with zipfile.ZipFile(sink,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
            for number,row in enumerate(files,1):
                checksum=hashlib.sha256();info=zipfile.ZipInfo('PES 2013 Moderno/'+row['path'],(2026,11,23,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info._compresslevel=1
                with z.open(info,'w',force_zip64=True) as target:
                    for part in row['chunks']:
                        data=get(part)
                        if len(data)!=part['size'] or sha(data)!=part['sha256']:raise ValueError('Archive chunk changed')
                        checksum.update(data);target.write(data)
                if checksum.hexdigest()!=row['sha256']:raise ValueError('Archive whole-file SHA-256 mismatch: '+row['path'])
                print(f'ARCHIVE_FILE_VERIFIED {number}/{len(files)} {row["path"]}',flush=True)
        return sink.finish()
    finally:
        if sink.stream is not None:
            sink.stream.close();sink.stream=None;sink.path.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--release',default='2026.11.23.2');p.add_argument('--probe',action='store_true');p.add_argument('--manual-archive',action='store_true');args=p.parse_args()
    if not re.fullmatch(r'[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]+',args.release):p.error('Invalid immutable version')
    raw=fetch(SOURCE,4*1024*1024)
    if sha(raw)!=SOURCE_SHA:raise ValueError('Pinned source manifest changed')
    source=json.loads(raw);objects=validate(source)
    print(f'PINNED_SOURCE_OK files={len(source["files"])} chunks={len(objects)} bytes={sum(x["size"] for x in objects.values())}',flush=True)
    if args.probe:
        sample=min(objects.values(),key=lambda x:x['size']);download(sample);print('CLOUD_SOURCE_PROBE_OK; no bulk transfer');return
    if not os.environ.get('GH_TOKEN'):raise RuntimeError('Set masked GH_TOKEN with Contents write for pes26ar-updates only')
    tag='mirror-'+args.release;release=draft_release(tag,args.release);existing=assets(release['id']);written={};base=f'https://github.com/{REPO}/releases/download/{tag}/'
    with tempfile.TemporaryDirectory(prefix='pes-cloud-mirror-') as tmp:
        work=Path(tmp)
        def reuse(remote,name,size,digest):
            item=remote.get(name)
            if item and item.get('state')=='starter':
                if not api(f'repos/{REPO}/releases/{release["id"]}')['draft']:raise ValueError('Release already published')
                run('api','--method','DELETE',f'repos/{REPO}/releases/assets/{item["id"]}');remote.pop(name);return False
            return reuse_asset(remote,name,size,digest,release['id'])
        def put(path,digest):
            written[path.name]=(path.stat().st_size,digest)
            if reuse(existing,path.name,path.stat().st_size,digest):return
            for attempt in range(4):
                try:run('release','upload',tag,str(path),'--repo',REPO);return
                except RuntimeError:
                    remote=assets(release['id'])
                    if reuse(remote,path.name,path.stat().st_size,digest):return
                    if attempt==3:raise
                    time.sleep(5*(attempt+1))
        def copy(pair):
            digest,part=pair;name=digest+'.bin'
            if reuse(existing,name,part['size'],digest):return
            path=work/name;path.write_bytes(download(part))
            try:put(path,digest)
            finally:path.unlink(missing_ok=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for n,_ in enumerate(pool.map(copy,objects.items()),1):
                if n%10==0 or n==len(objects):print(f'MIRROR_CHUNKS {n}/{len(objects)}',flush=True)
        remote=assets(release['id'])
        if any(not matches(remote.get(d+'.bin',{}),part['size'],d) for d,part in objects.items()):raise ValueError('Server chunk verification failed')
        volumes=archive(source['files'],work,'PES26AR-'+args.release,put) if args.manual_archive else []
        result=mirrored_manifest(source,args.release,base);manifest=work/'manifest.json';manifest.write_text(json.dumps(result,separators=(',',':'))+'\n',encoding='utf-8');put(manifest,sha(manifest.read_bytes()))
        proof=dict(source_manifest_sha256=SOURCE_SHA,release=args.release,files=len(source['files']),objects=len(objects),manual_volumes=volumes,status='verified',manual_format='concatenated ZIP volumes; download all, open .zip.001 with 7-Zip or join before extracting')
        proof_file=work/'mirror-verification.json';proof_file.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8');put(proof_file,sha(proof_file.read_bytes()))
        if volumes:
            guide=work/'MANUAL-DOWNLOAD.txt';guide.write_text('Download ALL .zip.001, .zip.002, ... volumes to the same folder. Open .zip.001 using 7-Zip or join the volumes into one .zip first. Extract to phone storage; select PES 2013 Moderno/Game in the APK. Never extract over an active game. Career saves are not included.\n\n'+'\n'.join(base+x['name'] for x in volumes)+'\n',encoding='utf-8');put(guide,sha(guide.read_bytes()))
        remote=assets(release['id'])
        if any(not matches(remote.get(name,{}),size,digest) for name,(size,digest) in written.items()):raise ValueError('Server metadata/archive verification failed')
        # Do not activate the signed application channel from CI; its key remains on the owner's PC.
        run('release','edit',tag,'--repo',REPO,'--draft=false','--prerelease','--latest=false')
        print('CLOUD_MIRROR_COMPLETE '+base+'manifest.json',flush=True)

if __name__=='__main__':main()
