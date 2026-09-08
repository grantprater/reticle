import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import tools.task_check as tc

class R:
    returncode=0; stdout='ok'; stderr=''

class TaskCheckTests(unittest.TestCase):
    def contract(self, root, task):
        p=root/'docs'; p.mkdir(); (p/'tasks.json').write_text(json.dumps({'schema_version':1,'tasks':[task]}),encoding='utf8'); (root/'x.txt').write_text('x'); return 'docs/tasks.json'
    def task(self, **kw):
        d={'id':'t','objective':'do','files':['x.txt'],'reads':['x.txt#top'],'acceptance':[['echo','a']], 'evidence':['seen']}; d.update(kw); return d
    def test_packet_does_not_shell_expand_and_null_telemetry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=self.contract(root,self.task()); log=root/'log';
            with patch.object(tc,'_repo',return_value=root), patch.object(tc.subprocess,'run',return_value=R()) as run:
                self.assertEqual(tc.main(['--task','t','--contracts',c,'--run','--log',str(log)]),0)
                self.assertEqual(run.call_args.kwargs['shell'],False); row=json.loads(log.read_text().splitlines()[0]); self.assertIsNone(row['model']); self.assertIsNone(row['tokens'])
    def test_traversal_reads_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=self.contract(root,self.task(reads=['../secret']))
            with patch.object(tc,'_repo',return_value=root):
                with self.assertRaises(ValueError): tc.main(['--task','t','--contracts',c])
    def test_failed_check_nonzero_and_preserves_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=self.contract(root,self.task()); log=root/'log'; log.write_text('{"old":1}\n')
            bad=type('Bad',(),{'returncode':3,'stdout':'','stderr':'fail'})()
            with patch.object(tc,'_repo',return_value=root), patch.object(tc.subprocess,'run',return_value=bad):
                self.assertEqual(tc.main(['--task','t','--contracts',c,'--run','--log',str(log)]),1)
            self.assertEqual(len(log.read_text().splitlines()),2)
    def test_invalid_acceptance_argv_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=self.contract(root,self.task(acceptance=[['ok','']]))
            with patch.object(tc,'_repo',return_value=root):
                with self.assertRaises(ValueError): tc.main(['--task','t','--contracts',c])

if __name__=='__main__': unittest.main()
