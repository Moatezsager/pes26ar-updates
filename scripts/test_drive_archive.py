import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import drive_archive as d
from mirror_public import archive


class DriveArchiveTests(unittest.TestCase):
    def test_upload_acknowledgements(self):
        self.assertEqual(d.acknowledged(308, {}, 8), 0)
        self.assertEqual(d.acknowledged(308, {'Range': 'bytes=0-3'}, 8), 4)
        self.assertEqual(d.acknowledged(200, {}, 8), 8)
        for code, headers in [(500, {}), (308, {'Range': 'bytes=0-8'}), (308, {'Range': 'bad'})]:
            with self.assertRaises(ValueError):
                d.acknowledged(code, headers, 8)

    def test_resume_after_uncertain_upload(self):
        data = b'abcdefgh'
        digest = hashlib.sha256(data).hexdigest()
        drive = d.Drive('mock-token')
        requests = []
        responses = iter([(200, {'Location': 'https://www.googleapis.com/upload/drive/v3/files/session'}, b''),
                          RuntimeError('interrupted'), (308, {'Range': 'bytes=0-1'}, b''),
                          (308, {'Range': 'bytes=0-5'}, b''), (200, {}, b'')])
        def request(url, method, body, headers):
            requests.append((method, body, headers))
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value
        drive.request = request
        drive.api = lambda *_: {'id': 'id', 'name': d.NAME, 'size': '8', 'sha256Checksum': digest}
        with tempfile.TemporaryDirectory() as tmp, patch.object(d, 'BLOCK', 4), patch.object(d.time, 'sleep'):
            path = Path(tmp) / 'zip.bin'
            path.write_bytes(data)
            result = drive.upload('id', path, digest)
        self.assertEqual(result['sha256Checksum'], digest)
        self.assertEqual([r[1] for r in requests if r[0] == 'PUT' and r[1]], [b'abcd', b'cdef', b'gh'])
        self.assertEqual([r[2]['Content-Range'] for r in requests if r[0] == 'PUT' and r[1]],
                         ['bytes 0-3/8', 'bytes 2-5/8', 'bytes 6-7/8'])

    def test_whole_archive_checksum_is_mandatory(self):
        for row in [{'name': d.NAME, 'size': 8, 'sha256Checksum': 'wrong'},
                    {'name': 'wrong.zip', 'size': 8, 'sha256Checksum': 'correct'},
                    {'name': d.NAME, 'size': 9, 'sha256Checksum': 'correct'}]:
            with self.assertRaises(ValueError):
                d.verify_remote(row, 8, 'correct')

    def test_single_zip_original_paths_and_crc(self):
        payload = b'game-data' * 100
        digest = hashlib.sha256(payload).hexdigest()
        rows = [{'path': 'Game/img/dt06.img', 'size': len(payload), 'sha256': digest,
                 'chunks': [{'size': len(payload), 'sha256': digest}]}]
        checked = []
        def put(path, sha):
            d.verify_zip(path, rows)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), sha)
            with zipfile.ZipFile(path) as z:
                self.assertEqual(z.read('PES 2013 Moderno/Game/img/dt06.img'), payload)
            checked.append(True)
        with tempfile.TemporaryDirectory() as tmp:
            result = archive(rows, Path(tmp), 'manual', put, get=lambda _: payload, limit=20*1024**3)
        self.assertEqual(len(result), 1)
        self.assertEqual(checked, [True])

    def test_extra_or_duplicate_members_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('extra.txt', 'unexpected')
            with self.assertRaises(ValueError):
                d.verify_zip(path, [])


if __name__ == '__main__':
    unittest.main()
