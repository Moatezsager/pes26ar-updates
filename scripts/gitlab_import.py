"""Import reviewed Drive files to GitLab Generic Packages using ephemeral CI credentials."""
import hashlib
import io
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from import_drive import sha,locate,selected_files,apply_visuals,CHUNK,HERE
from range_zip import RangeReader

VERSION='2026.11.20.1'
PACKAGE='pes26ar-data'
DRIVE='10k7_kP4bDIVGmJRetWI-8wswCqZrNSww'
INPUT='https://github.com/Moatezsager/pes26ar-updates/releases/download/build-input-2026.11.19/cloud-visual-input-20261119.zip'
INPUT_SHA='471a8e9242a8a47f49ba735edbb1c494d74fd268b342ad91002eb036b0422115'


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if urllib.parse.urlsplit(newurl).scheme!='https':raise ValueError('HTTPS redirect required')
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        if result is not None and urllib.parse.urlsplit(newurl).netloc!=urllib.parse.urlsplit(req.full_url).netloc:
            result.remove_header('Job-token')
        return result


def metadata_matches(item,size,digest):
    return item.get('size')==size and item.get('file_sha256')==digest


class Registry:
    def __init__(self):
        self.api=os.environ['CI_API_V4_URL']+'/projects/'+os.environ['CI_PROJECT_ID']
        if self.api!='https://gitlab.com/api/v4/projects/89205177':raise ValueError('Unexpected destination project')
        self.base=self.api+'/packages/generic/'+PACKAGE+'/'+VERSION+'/'
        self.token=os.environ['CI_JOB_TOKEN']
        self.opener=urllib.request.build_opener(SafeRedirect())
        self.existing=self.files()

    def request(self,url,data=None,method='GET'):
        if not url.startswith(self.api+'/'):raise ValueError('Unexpected authenticated destination')
        request=urllib.request.Request(url,data=data,method=method,headers={'JOB-TOKEN':self.token,'Content-Type':'application/octet-stream'})
        return self.opener.open(request,timeout=120)

    def pages(self,path):
        rows=[]
        for page in range(1,101):
            separator='&' if '?' in path else '?'
            with self.request(self.api+path+separator+f'per_page=100&page={page}') as response:
                batch=json.loads(response.read(4*1024*1024))
            if not isinstance(batch,list):raise ValueError('Invalid package API response')
            rows.extend(batch)
            if len(batch)<100:return rows
        raise ValueError('Package API pagination limit exceeded')

    def files(self):
        packages=self.pages('/packages?package_type=generic&package_name='+PACKAGE)
        packages=[p for p in packages if p.get('name')==PACKAGE and p.get('version')==VERSION]
        rows={}
        for package in packages:
            for item in self.pages(f'/packages/{package["id"]}/package_files'):
                name=item['file_name']
                if name in rows and not metadata_matches(rows[name],item['size'],item['file_sha256']):
                    raise ValueError('Conflicting package file: '+name)
                rows[name]=item
        return rows

    def put(self,name,data):
        digest=sha(data)
        for attempt in range(3):
            if name in self.existing:
                if not metadata_matches(self.existing[name],len(data),digest):
                    raise ValueError('Existing version differs; refusing replacement: '+name)
                return
            try:
                with self.request(self.base+name,data=data,method='PUT') as response:
                    if response.status!=201:raise ValueError('Package upload was not accepted')
                self.existing[name]=dict(size=len(data),file_sha256=digest)
                return
            except (OSError,ValueError):
                self.existing=self.files()
                if attempt==2:
                    if metadata_matches(self.existing.get(name,{}),len(data),digest):return
                    raise
                time.sleep(3*(attempt+1))


def main():
    registry=Registry()
    if 'manifest.json' in registry.existing:
        raise ValueError('This data version already has a manifest; review it instead of replacing it')
    with urllib.request.urlopen(INPUT,timeout=60) as response:
        visual_data=response.read(20*1024*1024+1)
    if len(visual_data)>20*1024*1024 or sha(visual_data)!=INPUT_SHA:raise ValueError('Visual input hash mismatch')
    expected={r['path']:r for r in json.loads((HERE/'expected-files.json').read_text())}
    manifest=dict(schema=1,release=VERSION,status='verified',required_client_capability='chunk-download-v1',chunk_size=CHUNK,files=[])
    objects={}
    with RangeReader('https://drive.usercontent.google.com/download?id='+DRIVE+'&export=download&confirm=t') as stream,zipfile.ZipFile(stream) as source,zipfile.ZipFile(io.BytesIO(visual_data)) as visual:
        members=locate(source,expected)
        expected=selected_files(expected,members)
        for number,name in enumerate(sorted(expected,key=lambda n:expected[n]['size']),1):
            row=expected[name]
            member=source.open(members[name]) if name in members else visual.open('fallback/dt05_a.img')
            size,digest=row['size'],row['sha256']
            if name=='Game/img/dt06.img':
                with member:original=member.read(size+1)
                member=io.BytesIO(apply_visuals(original,visual))
                plan=json.loads((HERE/'visual-update.json').read_text())
                size,digest=plan['output_bytes'],plan['output_sha256']
            offset=0
            full=hashlib.sha256()
            chunks=[]
            with member:
                while True:
                    block=member.read(CHUNK)
                    if not block:break
                    full.update(block)
                    checksum=sha(block)
                    filename=checksum+'.bin'
                    registry.put(filename,block)
                    objects[filename]=(len(block),checksum)
                    chunks.append(dict(offset=offset,size=len(block),sha256=checksum,urls=[registry.base+filename]))
                    offset+=len(block)
                    if len(chunks)%4==0:print(f'PARTS {name}: {offset}/{size} bytes',flush=True)
            if offset!=size or full.hexdigest()!=digest:raise ValueError('Source reference mismatch: '+name)
            manifest['files'].append(dict(path=name,component=row['component'],size=size,sha256=digest,chunks=chunks))
            print(f'VERIFIED {number}/{len(expected)}: {name}; {len(objects)} unique objects',flush=True)
    remote=registry.files()
    if not all(metadata_matches(remote.get(name,{}),size,digest) for name,(size,digest) in objects.items()):
        raise ValueError('Final registry SHA-256 audit failed; manifest not published')
    encoded=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    registry.put('manifest.json',encoded)
    channel=dict(schema=1,release=VERSION,manifest_url=registry.base+'manifest.json',manifest_sha256=sha(encoded),required_client_capability='chunk-download-v1')
    registry.put('channel.json',(json.dumps(channel,indent=2)+'\n').encode())
    print('IMPORT_COMPLETE: all source files and remote object hashes verified',flush=True)
    print(json.dumps(channel),flush=True)


if __name__=='__main__':main()
