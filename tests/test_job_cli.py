import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name)/'jobs.db'

    def tearDown(self): self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable,'-S',str(ROOT/'scripts/run_job_workflow.py'),'--db',str(self.db),*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=20)

    def test_import_report_and_idempotent_cycle_without_dependencies(self):
        result = self.run_cli('import-json',str(ROOT/'data/job_workflow_examples.json'))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['unique_jobs'],3)
        report = Path(self.tmp.name)/'daily.txt'
        first = self.run_cli('cycle','--input',str(ROOT/'data/job_workflow_examples.json'),'--report',str(report))
        self.assertEqual(first.returncode,0,first.stderr)
        second = self.run_cli('cycle','--input',str(ROOT/'data/job_workflow_examples.json'),'--report',str(report))
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertFalse(json.loads(second.stdout)['report_changed'])
        self.assertTrue(report.exists())
        self.assertIn('岗位总数: 3',self.run_cli('report').stdout)

    def test_network_source_requires_explicit_flag(self):
        result = self.run_cli('discover-greenhouse','example')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('联网',result.stderr)

    def test_cycle_continues_after_missing_source_and_reports_failure(self):
        report = Path(self.tmp.name)/'daily.txt'
        result = self.run_cli('cycle','--input',str(Path(self.tmp.name)/'missing.json'),'--input',str(ROOT/'data/job_workflow_examples.json'),'--report',str(report))
        self.assertEqual(result.returncode,1)
        data = json.loads(result.stdout)
        self.assertEqual(data['processed'],3)
        self.assertEqual(len(data['errors']),1)
        self.assertTrue(report.exists())


if __name__ == '__main__': unittest.main()
