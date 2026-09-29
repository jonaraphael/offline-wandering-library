import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from owl.acquisition.python_manual import GLOSSARY_FETCH,FEEDBACK_PARAMS,SEARCH_SUMMARY,auxiliary,repair
from owl.archive import ZipSource
from owl.safety import SafetyError


class PythonManualRuntimeTests(unittest.TestCase):
    def test_complete_glossary_data_and_runtime_surroundings_are_preserved(self):
        data=b'{"list":{"title":"list","body":"<p>Full definition and <a href=\\"#term-item\\">link</a></p>"}}'
        member={'path':'python/_static/glossary_search.js','runtime_patch':'python-glossary-file-v1'}
        source=('before\n'+GLOSSARY_FETCH+'\nafter').encode()
        out=repair(source,member,{'python/_static/glossary.json':data}).decode()
        embedded=out.split('const glossary = ',1)[1].split(';\nafter',1)[0]
        self.assertEqual(json.loads(embedded),json.loads(data));self.assertTrue(out.startswith('before\n'));self.assertTrue(out.endswith('\nafter'))
        with self.assertRaisesRegex(SafetyError,'source span changed'):repair(b'changed',member,{'python/_static/glossary.json':data})
        with self.assertRaisesRegex(SafetyError,'pinned auxiliary'):repair(source,member,{})

    def test_auxiliary_original_hash_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()/'source.zip';data=b'{"a":{"body":"complete"}}'
            with ZipFile(path,'w') as z:z.writestr('manual/_static/glossary.json',data)
            asset={'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            members=[{'path':'manual/_static/glossary_search.js','runtime_patch':'python-glossary-file-v1'},
                {'path':'manual/_static/glossary.json','size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}]
            with ZipSource(path,asset) as archive:
                self.assertEqual(auxiliary(archive,members),{'manual/_static/glossary.json':data})
                members[1]['sha256']='0'*64
                with self.assertRaisesRegex(SafetyError,'member pin'):auxiliary(archive,members)

    def test_feedback_defaults_and_file_search_are_explicit_source_bound_changes(self):
        feedback={'path':'manual/improve-page.html','runtime_patch':'python-feedback-defaults-v1'}
        result=repair(FEEDBACK_PARAMS.encode(),feedback,{}).decode()
        self.assertIn("if (!params.get('pageurl'))",result);self.assertIn("new URL('index.html'",result)
        search={'path':'manual/_static/searchtools.js','runtime_patch':'python-title-search-file-v1'}
        result=repair(SEARCH_SUMMARY.encode(),search,{}).decode()
        self.assertIn('location.protocol !== "file:"',result);self.assertIn('complete documentation',result)
        with self.assertRaisesRegex(SafetyError,'misplaced'):repair(b'x',{**feedback,'path':'manual/book.html'}, {})
