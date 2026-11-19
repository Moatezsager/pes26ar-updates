"""Seekable, bounded HTTP Range reader for ZIP files; no full archive on disk."""
import io
import re
import time
import urllib.request
import hashlib
from pathlib import Path
import os
import shutil


class RangeReader(io.RawIOBase):
    BLOCK=8*1024*1024

    def __init__(self,url,cache_dir=None,cache_bytes=3500*1024**2):
        super().__init__()
        self.url=url
        self.position=0
        self.cache=b''
        self.cache_start=0
        self.total=None
        self._fetch(0,0)
        self.cache_dir=Path(cache_dir)/hashlib.sha256((url+str(self.total)).encode()).hexdigest() if cache_dir else None
        self.cache_bytes=cache_bytes
        if self.cache_dir:self.cache_dir.mkdir(parents=True,exist_ok=True)

    def _block(self,start,end):
        if self.cache_dir:
            for path in self.cache_dir.glob(f'{start}-*.bin'):
                if path.is_symlink():raise ValueError('Unsafe cache symlink')
                data=path.read_bytes()
                if len(data)==end-start+1 and hashlib.sha256(data).hexdigest()==path.stem.split('-',1)[1]:
                    path.touch()
                    return data
                path.unlink()
        data=self._fetch(start,end)
        if self.cache_dir:
            files=sorted(self.cache_dir.glob('*.bin'),key=lambda p:p.stat().st_mtime)
            used=sum(p.stat().st_size for p in files)
            for old in files:
                if used+len(data)<=self.cache_bytes and shutil.disk_usage(self.cache_dir).free>=len(data)+32*1024**2:break
                used-=old.stat().st_size
                old.unlink()
            if len(data)<=self.cache_bytes and shutil.disk_usage(self.cache_dir).free>=len(data)+32*1024**2:
                target=self.cache_dir/f'{start}-{hashlib.sha256(data).hexdigest()}.bin'
                temporary=target.with_suffix('.tmp')
                temporary.write_bytes(data)
                os.replace(temporary,target)
        return data

    def _fetch(self,start,end):
        for attempt in range(3):
            try:
                request=urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'})
                with urllib.request.urlopen(request,timeout=45) as response:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if response.status!=206 or not match:
                        raise ValueError('Drive did not honor HTTP Range; no full download was accepted')
                    a,b,total=map(int,match.groups())
                    if a!=start or b!=end or total<=b or self.total not in (None,total):
                        raise ValueError('Drive returned an unexpected range or changed file size')
                    self.total=total
                    data=response.read(end-start+2)
                    if len(data)!=end-start+1:
                        raise IOError('Truncated HTTP range')
                    return data
            except (OSError,ValueError):
                if attempt==2:raise
                time.sleep(attempt+1)

    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position

    def seek(self,offset,whence=io.SEEK_SET):
        target=offset if whence==io.SEEK_SET else self.position+offset if whence==io.SEEK_CUR else self.total+offset if whence==io.SEEK_END else -1
        if target<0:raise ValueError('Invalid ZIP seek')
        self.position=target
        return target

    def read(self,size=-1):
        if self.closed:raise ValueError('Reader closed')
        remaining=max(0,self.total-self.position)
        count=remaining if size is None or size<0 else min(size,remaining)
        pieces=[]
        while count:
            if not self.cache_start<=self.position<self.cache_start+len(self.cache):
                self.cache_start=self.position//self.BLOCK*self.BLOCK
                self.cache=self._block(self.cache_start,min(self.total-1,self.cache_start+self.BLOCK-1))
            start=self.position-self.cache_start
            take=min(count,len(self.cache)-start)
            pieces.append(self.cache[start:start+take])
            self.position+=take
            count-=take
        return b''.join(pieces)
