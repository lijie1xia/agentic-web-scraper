"""Pure scoring/material helpers must not require the paid-model stack."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OfflineImportTests(unittest.TestCase):
    def test_pure_imports_without_site_packages(self):
        code = ('from scraper_framework.job_agent import score, load_skill_profile, select_relevant_highlights; '
                'import sys; assert "camel" not in sys.modules; '
                'assert "scraper_framework.job_agent.extract" not in sys.modules; '
                'assert callable(score); assert load_skill_profile()["graduate_year"] == 2027')
        result = subprocess.run([sys.executable, '-S', '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_attribute_is_attribute_error(self):
        sys.path.insert(0, str(ROOT))
        import scraper_framework.job_agent as agent
        with self.assertRaises(AttributeError):
            getattr(agent, 'not_an_export')


if __name__ == '__main__':
    unittest.main()
