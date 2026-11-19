import io
import zipfile
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from range_zip import RangeReader


class RangeTests(unittest.TestCase):
    def test_cache_survives_reader_restart_and_rejects_corruption(self):
        payload=b'abcdefgh'*1024
        class Reply(io.BytesIO):status=206
        requests=[]
        def get(request,timeout):
            start,end=map(int,request.get_header('Range')[6:].split('-'))
            requests.append((start,end))
            response=Reply(payload[start:end+1]);response.headers={'Content-Range':f'bytes {start}-{end}/{len(payload)}'}
            return response
        with tempfile.TemporaryDirectory() as folder,patch('range_zip.urllib.request.urlopen',side_effect=get),patch.object(RangeReader,'BLOCK',4096):
            with RangeReader('https://test.invalid/file',cache_dir=folder) as reader:
                self.assertEqual(reader.read(100),payload[:100])
            requests.clear()
            with RangeReader('https://test.invalid/file',cache_dir=folder) as reader:
                self.assertEqual(reader.read(100),payload[:100])
            self.assertEqual(requests,[(0,0)])
            next(Path(folder).rglob('*.bin')).write_bytes(b'corrupt')
            requests.clear()
            with RangeReader('https://test.invalid/file',cache_dir=folder) as reader:
                self.assertEqual(reader.read(100),payload[:100])
            self.assertIn((0,4095),requests)

    def test_zip_seek_reads_only_requested_ranges(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_STORED) as z:
            z.writestr('large.bin',b'x'*(1024*1024))
            z.writestr('selected.txt',b'hello')
        payload=buffer.getvalue()
        requested=[]
        class Reply(io.BytesIO):
            status=206
        def get(request,timeout):
            start,end=map(int,request.get_header('Range')[6:].split('-'))
            requested.append((start,end))
            response=Reply(payload[start:end+1])
            response.headers={'Content-Range':f'bytes {start}-{end}/{len(payload)}'}
            return response
        with patch('range_zip.urllib.request.urlopen',side_effect=get),patch.object(RangeReader,'BLOCK',4096):
            with RangeReader('https://test.invalid/archive') as reader,zipfile.ZipFile(reader) as z:
                self.assertEqual(z.read('selected.txt'),b'hello')
        self.assertLess(sum(b-a+1 for a,b in requested),32768)

    def test_reject_server_ignoring_range(self):
        class Reply(io.BytesIO):
            status=200
            headers={}
        with patch('range_zip.urllib.request.urlopen',side_effect=lambda *a,**kw:Reply(b'wrong')),patch('range_zip.time.sleep'):
            with self.assertRaisesRegex(ValueError,'did not honor'):
                RangeReader('https://test.invalid/archive')


if __name__=='__main__':unittest.main()
