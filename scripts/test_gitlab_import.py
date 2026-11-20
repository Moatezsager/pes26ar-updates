import io
import unittest
import urllib.request
from gitlab_import import SafeRedirect,metadata_matches


class GitLabTransportTests(unittest.TestCase):
    def test_redirect_strips_token_outside_gitlab(self):
        request=urllib.request.Request('https://gitlab.com/api/v4/projects/1/packages/test',headers={'JOB-TOKEN':'private-test-token'})
        result=SafeRedirect().redirect_request(request,io.BytesIO(),302,'Found',{},'https://storage.googleapis.com/test/signed')
        self.assertFalse(any(k.lower()=='job-token' for k in result.headers))
        with self.assertRaises(ValueError):SafeRedirect().redirect_request(request,io.BytesIO(),302,'Found',{},'http://storage.googleapis.com/test')

    def test_digest_and_size_both_required(self):
        self.assertTrue(metadata_matches(dict(size=3,file_sha256='ok'),3,'ok'))
        self.assertFalse(metadata_matches(dict(size=3,file_sha256='bad'),3,'ok'))
        self.assertFalse(metadata_matches(dict(size=2,file_sha256='ok'),3,'ok'))


if __name__=='__main__':unittest.main()
