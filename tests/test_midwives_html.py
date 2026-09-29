import unittest

from owl.acquisition.midwives_html import OrdinaryHTML
from owl.acquisition.midwives_wikitext import RenderError


class MidwivesHTMLTests(unittest.TestCase):
    def render(self, source):
        renderer = OrdinaryHTML(
            [{'title': 'A Book for Midwives', 'pageid': 1},
             {'title': 'A Book for Midwives:Example', 'pageid': 2}],
            [{'title': 'File:Figure.png', 'source_id': 'figure',
              'info': {'width': 400, 'height': 200}}])
        return renderer.render('A Book for Midwives:Example', source, 'Example')

    def test_warning_table_words_and_image_position_are_retained(self):
        text = '<div class="warning">Warning: seek help.</div>\n<table><tr><td>5 mg</td><td>twice daily</td></tr></table>\n<div style="position:relative;width:200px">[[Image:Figure.png|200px|alt=Clinical diagram]]<span style="position:absolute;left:20px;top:10px">Label</span></div>'
        html, report = self.render(text)
        for literal in ['Warning: seek help.', '5 mg', 'twice daily', 'left:20px;top:10px', 'Label', 'alt="Clinical diagram"']:
            self.assertIn(literal, html)
        self.assertIn('width="200" height="100"', html)
        self.assertEqual(report['images'], ['File:Figure.png'])

    def test_hidden_publisher_content_is_open_without_javascript(self):
        html, report = self.render('<dialog id="sidetoc">Chapter contents</dialog><details><summary>Sources</summary>Source notice</details>')
        self.assertIn('<aside id="sidetoc">Chapter contents</aside>', html)
        self.assertIn('<details open="">', html)
        self.assertIn('Source notice', html)

    def test_local_headings_links_and_nested_lists(self):
        html, report = self.render('== Warning signs ==\n[[A Book for Midwives:Example#Warning signs|Read signs]]\n* first\n** nested\n* second')
        self.assertIn('id="Warning_signs"', html)
        self.assertIn('href="page-2.html#Warning_signs"', html)
        self.assertEqual(html.count('<ul>'), html.count('</ul>'))
        self.assertIn('nested', html)
        self.assertEqual(report['local_links'][0]['fragment'], 'Warning_signs')

    def test_single_source_wiki_table_preserves_speech_labels(self):
        html, _ = self.render('{| style="width:320px"\n|<div>First speech</div><div>Second speech</div>\n|}')
        self.assertIn('<table style="width:320px"><tr><td>', html)
        self.assertIn('First speech', html)
        self.assertIn('Second speech', html)

    def test_unknown_dependencies_and_executable_markup_fail_closed(self):
        for source in ['[[Image:Missing.png]]', '[[A Book for Midwives:Missing]]',
                       '<script>run()</script>', '<div style="background:url(https://example.com/x)">text</div>',
                       '<img src="https://example.com/x.png">', '<a href="javascript:run()">link</a>',
                       ':unimplemented indentation']:
            with self.subTest(source=source), self.assertRaises(RenderError):
                self.render(source)


if __name__ == '__main__':
    unittest.main()
