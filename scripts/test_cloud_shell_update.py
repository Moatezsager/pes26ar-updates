"""Exercise the launcher update against the same disconnected shallow history."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil
import os


class LauncherUpdateTests(unittest.TestCase):
    def test_shallow_retry_keeps_download_and_updates_code(self):
        script=Path(__file__).with_name('cloud-shell.sh').read_text(encoding='utf-8')
        start=script.index('  # A depth-one fetch')
        update=script[start:script.index('\nfi\n\npython3',start)]
        bash='C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else shutil.which('bash')
        def run(*args,cwd):
            return subprocess.run(args,cwd=cwd,check=True,capture_output=True,text=True).stdout.strip()
        with tempfile.TemporaryDirectory(prefix='pes-git-update-') as folder:
            root=Path(folder).resolve()
            run('git','init','--bare','--initial-branch=main','origin.git',cwd=root)
            run('git','clone',str(root/'origin.git'),'writer',cwd=root)
            writer=root/'writer'
            for value in ('first','second'):
                (writer/'version.txt').write_text(value)
                run('git','add','version.txt',cwd=writer)
                run('git','-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m',value,cwd=writer)
                run('git','push','origin','main',cwd=writer)
                if value=='first':
                    run('git','clone','--depth','1','--branch','main',(root/'origin.git').as_uri(),'repository',cwd=root)
            run('git','fetch','origin','main','--depth','1',cwd=root/'repository')
            (root/'source.zip').write_bytes(b'keep-completed-download')
            run(bash,'-c',update,cwd=root)
            self.assertEqual((root/'repository/version.txt').read_text(),'second')
            self.assertEqual((root/'source.zip').read_bytes(),b'keep-completed-download')
            self.assertEqual(run('git','rev-parse','--is-shallow-repository',cwd=root/'repository'),'false')


if __name__=='__main__':unittest.main()
