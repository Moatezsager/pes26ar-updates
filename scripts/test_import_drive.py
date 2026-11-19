import unittest
import zipfile
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from import_drive import canonical,locate,matches,draft_release,download_archive,selected_files,reuse_asset


class ImportTests(unittest.TestCase):
    def test_incomplete_draft_asset_retries_without_deleting_completed_assets(self):
        complete=dict(id=1,state='uploaded',size=3,digest='sha256:good')
        pending=dict(id=2,state='starter',size=3)
        existing={'complete.bin':complete,'pending.bin':pending}
        with patch('import_drive.api',return_value=dict(draft=True)) as api,patch('import_drive.run') as run:
            self.assertTrue(reuse_asset(existing,'complete.bin',3,'good',42))
            run.assert_not_called()
            self.assertFalse(reuse_asset(existing,'pending.bin',3,'good',42))
            run.assert_called_once_with('api','--method','DELETE','repos/Moatezsager/pes26ar-updates/releases/assets/2')
        self.assertEqual(existing,{'complete.bin':complete})
        with patch('import_drive.run') as run:
            with self.assertRaises(ValueError):reuse_asset(existing,'complete.bin',3,'different',42)
            run.assert_not_called()
        with patch('import_drive.api',return_value=dict(draft=False)),patch('import_drive.run') as run:
            with self.assertRaises(ValueError):reuse_asset({'pending.bin':pending},'pending.bin',3,'good',42)
            run.assert_not_called()

    def test_arabic_only_package_does_not_require_english_menus(self):
        a,e,game='Game/img/dt05_a.img','Game/img/dt05_e.img','Game/img/dt01.img'
        expected={name:dict(size=3) for name in (a,e,game)}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('phone/'+a,b'ara')
            z.writestr('phone/'+game,b'dat')
        with zipfile.ZipFile(stream) as z:
            members=locate(z,expected)
            self.assertEqual(set(selected_files(expected,members)),{a,game})
        self.assertIn(e,expected)

    def test_missing_language_or_game_file_is_still_rejected(self):
        a,e,game='Game/img/dt05_a.img','Game/img/dt05_e.img','Game/img/dt01.img'
        expected={name:dict(size=3) for name in (a,e,game)}
        for name in (a,game):
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:z.writestr(name,b'abc')
            with zipfile.ZipFile(stream) as z:
                with self.assertRaisesRegex(ValueError,'missing required files'):
                    locate(z,expected)

    def test_existing_draft_uses_database_id_not_rest_tag_endpoint(self):
        result=dict(id=42,draft=True,tag_name='data-2026.11.19.1')
        with patch('import_drive.run',return_value=json.dumps(dict(databaseId=42,isDraft=True,tagName=result['tag_name']))) as run:
            with patch('import_drive.api',return_value=result) as api:
                self.assertEqual(draft_release(result['tag_name'],'2026.11.19.1'),result)
                api.assert_called_once_with('repos/Moatezsager/pes26ar-updates/releases/42')
                self.assertEqual(run.call_args.args[:2],('release','view'))

    def test_does_not_redownload_complete_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'source.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('test',b'verified later')
            before=archive.read_bytes()
            with patch('import_drive.shutil.disk_usage') as disk:
                disk.return_value.free=1024**3
                with patch.dict('sys.modules',{'gdown':None}):
                    download_archive(archive,'test-id')
            self.assertEqual(archive.read_bytes(),before)

    def test_private_saves_are_not_selected(self):
        expected={'Game/img/a.img':dict(size=3)}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('PES 2013 Moderno/Game/img/a.img',b'abc')
            z.writestr('Android/data/private/ML01.bin',b'personal career')
            z.writestr('PES 2013 Moderno/Backups-Arabic/backup.zip',b'private')
        with zipfile.ZipFile(stream) as z:
            self.assertEqual(set(locate(z,expected)),set(expected))

    def test_reject_paths_duplicates_and_size(self):
        for path in ('../Game/x','/Game/x','Game\\x'):
            with self.assertRaises(ValueError):canonical(path)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('a/Game/x',b'a')
            z.writestr('b/Game/x',b'a')
        with zipfile.ZipFile(stream) as z:
            with self.assertRaises(ValueError):locate(z,{'Game/x':dict(size=1)})
        self.assertFalse(matches(dict(state='uploaded',size=3,digest='sha256:wrong'),3,'right'))


if __name__=='__main__':unittest.main()
