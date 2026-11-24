"""Build one verified manual-download ZIP on CI and upload it to Google Drive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from mirror_public import SOURCE, SOURCE_SHA, archive, download, fetch, validate

PARENT = '1YNlmSNrQfrnbA7PKCrBtu3PlkVx2d5XD'
NAME = 'PES26AR_2026.11.24_Full.zip'
FIELDS = 'id,name,size,sha256Checksum,appProperties,webViewLink'
BLOCK = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Drive:
    def __init__(self, token):
        if not token or any(c.isspace() for c in token):
            raise ValueError('Set a masked GDRIVE_ACCESS_TOKEN; never paste it into logs')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, url, method='GET', data=None, headers=None):
        if not url.startswith(('https://www.googleapis.com/drive/v3/', 'https://www.googleapis.com/upload/drive/v3/')):
            raise ValueError('Unapproved Drive endpoint')
        h = {'Authorization': 'Bearer ' + self.token}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=120) as r:
                return r.status, r.headers, r.read(1024 * 1024)
        except urllib.error.HTTPError as e:
            if e.code == 308:
                return e.code, e.headers, b''
            if e.code == 401:
                raise RuntimeError('Google access expired; refresh the private CI variable') from None
            raise RuntimeError('Drive HTTP ' + str(e.code)) from None
        except OSError:
            raise RuntimeError('Drive connection interrupted; resumable upload will retry') from None

    def api(self, path, method='GET', body=None):
        data = None if body is None else json.dumps(body).encode()
        code, _, raw = self.request('https://www.googleapis.com/drive/v3/' + path, method, data,
                                    {'Content-Type': 'application/json'})
        if code not in (200, 201):
            raise RuntimeError('Unexpected Drive metadata response')
        return json.loads(raw)

    def destination(self):
        q = "'" + PARENT + "' in parents and trashed=false and name='" + NAME + "'"
        params = urllib.parse.urlencode({'q': q, 'fields': 'files(' + FIELDS + ')', 'pageSize': 10})
        files = self.api('files?' + params).get('files', [])
        if len(files) > 1:
            raise ValueError('Duplicate destination archives; none was overwritten')
        if files:
            row = files[0]
            if row.get('appProperties', {}).get('pes26arManifest') != SOURCE_SHA:
                raise ValueError('Existing unrelated archive was not overwritten')
            return row
        return self.api('files?fields=' + FIELDS, 'POST', {
            'name': NAME, 'mimeType': 'application/zip', 'parents': [PARENT],
            'appProperties': {'pes26arManifest': SOURCE_SHA}})

    def upload(self, file_id, path, digest):
        size = path.stat().st_size
        url = 'https://www.googleapis.com/upload/drive/v3/files/' + file_id + '?uploadType=resumable'
        code, headers, _ = self.request(url, 'PATCH', b'{}', {
            'Content-Type': 'application/json', 'X-Upload-Content-Type': 'application/zip',
            'X-Upload-Content-Length': str(size)})
        if code != 200:
            raise RuntimeError('Could not create resumable upload')
        session = headers.get('Location', '')
        if not session.startswith('https://www.googleapis.com/upload/drive/v3/files'):
            raise ValueError('Unapproved upload-session host')
        offset = 0
        with path.open('rb') as stream:
            failures = 0
            while offset < size:
                stream.seek(offset)
                data = stream.read(min(BLOCK, size - offset))
                try:
                    code, headers, _ = self.request(session, 'PUT', data, {
                        'Content-Type': 'application/zip',
                        'Content-Range': f'bytes {offset}-{offset + len(data) - 1}/{size}'})
                    offset = acknowledged(code, headers, size)
                    failures = 0
                    print(f'DRIVE_ZIP_UPLOAD {offset}/{size}', flush=True)
                except RuntimeError as e:
                    if 'access expired' in str(e) or failures >= 4:
                        raise
                    failures += 1
                    time.sleep(min(20, 2 ** failures))
                    code, headers, _ = self.request(session, 'PUT', b'', {'Content-Range': f'bytes */{size}'})
                    offset = acknowledged(code, headers, size)
        for _ in range(5):
            row = self.api('files/' + file_id + '?fields=' + FIELDS)
            if row.get('sha256Checksum'):
                verify_remote(row, size, digest)
                return row
            time.sleep(3)
        raise RuntimeError('Drive whole-ZIP SHA-256 is not available yet; archive is not marked ready')


def acknowledged(code, headers, total):
    if code in (200, 201):
        return total
    if code != 308:
        raise ValueError('Unexpected resumable-upload response')
    value = headers.get('Range', '')
    if not value:
        return 0
    match = re.fullmatch(r'bytes=0-(\d+)', value)
    if not match or int(match[1]) >= total:
        raise ValueError('Invalid Drive upload acknowledgement')
    return int(match[1]) + 1


def verify_remote(row, size, digest):
    if row.get('name') != NAME or int(row.get('size', -1)) != size or row.get('sha256Checksum') != digest:
        raise ValueError('Uploaded archive name, size or SHA-256 mismatch')


def verify_zip(path, files):
    expected = {'PES 2013 Moderno/' + f['path']: f for f in files}
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) != len(expected) or set(z.namelist()) != set(expected):
            raise ValueError('ZIP filenames or member count mismatch')
        if any(z.getinfo(name).file_size != row['size'] for name, row in expected.items()):
            raise ValueError('ZIP uncompressed size mismatch')
        bad = z.testzip()
        if bad:
            raise ValueError('ZIP CRC failed: ' + bad)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    raw = fetch(SOURCE, 4 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('Pinned source manifest changed')
    source = json.loads(raw)
    objects = validate(source)
    if len(source['files']) != 271:
        raise ValueError('Unexpected game file count')
    if args.probe:
        for host in ('https://gitlab.com/', 'https://github.com/'):
            part = next(c for c in objects.values() if c['size'] == 16777216 and c['urls'][0].startswith(host))
            began = time.monotonic()
            download(part)
            print(f'CLOUD_SOURCE_VERIFIED {host} 16_MiB {time.monotonic()-began:.3f}_seconds', flush=True)
        return
    drive = Drive(os.environ.get('GDRIVE_ACCESS_TOKEN', ''))
    destination = drive.destination()
    verified = destination.get('appProperties', {}).get('pes26arZipSha256')
    if verified and destination.get('sha256Checksum') == verified:
        proof = dict(status='verified', name=NAME, files=271, bytes=int(destination['size']),
                     sha256=verified, source_manifest_sha256=SOURCE_SHA,
                     url='https://drive.google.com/file/d/' + destination['id'] + '/view')
        Path('manual-download.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
        print('VERIFIED_EXISTING_ARCHIVE ' + proof['url'])
        return
    if shutil.disk_usage('.').free < 12 * 1024 ** 3:
        raise RuntimeError('At least 12 GiB temporary runner disk is required')
    proof = {}
    with tempfile.TemporaryDirectory(prefix='pes-drive-zip-') as tmp:
        def put(path, digest):
            verify_zip(path, source['files'])
            row = drive.upload(destination['id'], path, digest)
            drive.api('files/' + row['id'] + '?fields=id', 'PATCH', {
                'appProperties': {'pes26arManifest': SOURCE_SHA, 'pes26arZipSha256': digest},
                'description': 'VERIFIED: 271 game and patch files; original names; source and whole-ZIP SHA-256 checked.'})
            proof.update(status='verified', name=NAME, files=271, bytes=path.stat().st_size,
                         sha256=digest, source_manifest_sha256=SOURCE_SHA,
                         url='https://drive.google.com/file/d/' + row['id'] + '/view')
        # One volume with ordinary ZIP/ZIP64 structure, named .zip on Google Drive.
        result = archive(source['files'], Path(tmp), 'PES26AR-Full', put, limit=20 * 1024 ** 3)
        if len(result) != 1 or not proof:
            raise ValueError('Expected exactly one verified ZIP')
    Path('manual-download.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print('MANUAL_DOWNLOAD_READY ' + proof['url'], flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # HTTP/session URLs and credentials never enter CI logs.
        print('FAILED: ' + re.sub(r'https?://\S+', '[URL]', str(e)), flush=True)
        raise SystemExit(1)
