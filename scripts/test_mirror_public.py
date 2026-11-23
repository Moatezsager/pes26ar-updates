import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import mirror_public as m

def row(path,data):
    sha=m.sha(data)
    return dict(path=path,size=len(data),sha256=sha,chunks=[dict(offset=0,size=len(data),sha256=sha,urls=['https://gitlab.com/api/v4/projects/89205177/packages/generic/pes26ar-data/test/'+sha+'.bin'])])
def manifest(files):return dict(schema=1,status='verified',required_client_capability='chunk-download-v1',release='test',files=files)

class MirrorTests(unittest.TestCase):
    def test_original_hashes_layout_and_sources_preserved(self):
        source=manifest([row('Game/img/dt01.img',b'game')]);original=copy.deepcopy(source)
        new=m.mirrored_manifest(source,'2026.11.23.2','https://github.com/Moatezsager/pes26ar-updates/releases/download/test/')
        self.assertEqual(source,original)
        a,b=source['files'][0],new['files'][0]
        self.assertEqual({k:v for k,v in a.items() if k!='chunks'},{k:v for k,v in b.items() if k!='chunks'})
        self.assertEqual(b['chunks'][0]['urls'][1:],a['chunks'][0]['urls'])
        self.assertEqual(b['chunks'][0]['size'],a['chunks'][0]['size'])
    def test_unsafe_paths_and_career_saves_rejected(self):
        for name in ['Game/../secrets','/Game/img/dt01.img','Game\\img\\dt01.img','Patches/ELENCOD2026_01/save/BL01.bin','Patches/ELENCOD2026_01/save/OPTION.bin']:
            with self.subTest(name=name),self.assertRaises(ValueError):m.validate(manifest([row(name,b'x')]))
    def test_duplicate_names_chunk_gaps_and_size_conflicts_rejected(self):
        a=row('Game/img/dt01.img',b'x')
        with self.assertRaises(ValueError):m.validate(manifest([a,a]))
        b=copy.deepcopy(a);b['chunks'][0]['offset']=1
        with self.assertRaises(ValueError):m.validate(manifest([b]))
        b=copy.deepcopy(a);b['path']='Game/img/dt02.img';b['size']=2;b['chunks'][0]['size']=2
        with self.assertRaises(ValueError):m.validate(manifest([a,b]))
    def test_split_archive_extracts_exact_files_with_small_disk_bound(self):
        data=bytes(range(256))*13;files=[row('Game/img/dt01.img',data),row('Patches/ELENCOD2026_01/save/ST_ROOF_F01.bin',b'roof')];objects={f['sha256']:v for f,v in zip(files,[data,b'roof'])};parts=[]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            def put(p,digest):
                value=p.read_bytes();self.assertEqual(m.sha(value),digest);self.assertLessEqual(len(value),200);self.assertLessEqual(sum(f.stat().st_size for f in folder.iterdir()),200);parts.append(value)
            volumes=m.archive(files,folder,'test',put,get=lambda p:objects[p['sha256']],limit=200)
            self.assertGreater(len(volumes),1)
            self.assertEqual(list(folder.iterdir()),[])
        with zipfile.ZipFile(io.BytesIO(b''.join(parts))) as z:
            self.assertIsNone(z.testzip());self.assertEqual(z.read('PES 2013 Moderno/Game/img/dt01.img'),data)
            self.assertEqual(z.read('PES 2013 Moderno/Patches/ELENCOD2026_01/save/ST_ROOF_F01.bin'),b'roof')
    def test_bad_whole_file_hash_never_completes_archive(self):
        a=row('Game/img/dt01.img',b'x');a['sha256']='0'*64
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):m.archive([a],Path(tmp),'bad',lambda p,d:None,get=lambda p:b'x')
    def test_unapproved_source_rejected(self):
        a=row('Game/img/dt01.img',b'x');a['chunks'][0]['urls']=['https://other.example/file']
        with self.assertRaises(ValueError):m.validate(manifest([a]))
    def test_archive_is_deterministic_for_resume(self):
        def once():
            parts=[]
            with tempfile.TemporaryDirectory() as tmp:m.archive([row('Game/img/dt01.img',b'game')],Path(tmp),'test',lambda p,d:parts.append(p.read_bytes()),get=lambda p:b'game',limit=100)
            return parts
        self.assertEqual(once(),once())

if __name__=='__main__':unittest.main()
