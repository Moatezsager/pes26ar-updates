import unittest
import zipfile
import io
from import_drive import canonical,locate,matches


class ImportTests(unittest.TestCase):
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
