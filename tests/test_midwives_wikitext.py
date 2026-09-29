import unittest
import hashlib

from owl.acquisition.midwives_wikitext import Expander, RenderError, split_top


REVISION = {'timestamp': '2026-08-13T20:03:38Z'}


class MidwivesWikitextTests(unittest.TestCase):
    def expand(self, source, templates=None, **limits):
        engine = Expander(templates or {}, **limits)
        return engine.page('A Book for Midwives:Example', REVISION, source)

    def test_nested_parameters_do_not_split_clinical_text_or_image_options(self):
        templates = {'Template:Box': '<strong>{{{title|Warning}}}</strong>{{{1}}}', 'Template:=': '='}
        value = self.expand('{{Box|[[Image:figure.png|200px|Dose table]] and 5{{=}}5|title=Keep this dose}}', templates)
        self.assertEqual(value, '<strong>Keep this dose</strong>[[Image:figure.png|200px|Dose table]] and 5=5')

    def test_lazy_condition_does_not_expand_missing_inactive_content(self):
        self.assertEqual(self.expand('{{#if:yes|Keep warning|{{not captured}}}}'), 'Keep warning')
        self.assertEqual(self.expand('{{#switch:dose|unused={{absent}}|dose=Preserve 5 mg|#default={{absent}}}}'), 'Preserve 5 mg')

    def test_inclusion_and_revision_date_are_deterministic(self):
        templates = {'Template:Label': '<noinclude>Sample dose is not real content</noinclude><includeonly>Actual warning</includeonly>'}
        self.assertEqual(self.expand('{{Label}} {{#time: d M Y|{{REVISIONTIMESTAMP}}}}', templates), 'Actual warning 13 Aug 2026')

    def test_heading_equals_preserve_anonymous_clinical_box_content(self):
        templates = {'Template:Box': '<aside>{{{3}}}</aside>'}
        source = '{{Box|||\n====Signs requiring care====\nKeep all warning signs.}}'
        self.assertEqual(self.expand(source, templates), '<aside>\n====Signs requiring care====\nKeep all warning signs.</aside>')

    def test_unknown_or_incomplete_constructs_fail_closed(self):
        for text in ['{{absent}}', '{{#invoke:x}}', '{{{missing}}}', '{{unclosed', '{{#time: Y|20200101}}']:
            with self.assertRaises(RenderError):
                self.expand(text)

    def test_cycles_and_expansion_size_are_bounded(self):
        with self.assertRaisesRegex(RenderError, 'recursion'):
            self.expand('{{Loop}}', {'Template:Loop': '{{Loop}}'})
        with self.assertRaises(RenderError):
            self.expand('{{Large}}', {'Template:Large': 'x' * 100}, max_output=20)

    def test_separator_and_literal_nowiki_are_preserved(self):
        self.assertEqual(split_top('a|[[page|label]]|{{x|y}}'), ['a', '[[page|label]]', '{{x|y}}'])
        self.assertEqual(self.expand('<nowiki>{{not a template}}</nowiki>'), '&#123;&#123;not a template&#125;&#125;')

    def test_literal_publisher_braces_require_exact_source_binding(self):
        source = 'Publisher-visible }} punctuation'
        body = source.encode()
        case = {'title': 'A Book for Midwives:Example',
                'payload_sha1': hashlib.sha1(body).hexdigest(),
                'whole_response_sha256': hashlib.sha256(b'\n\n\n\n' + body).hexdigest(),
                'literal_hex': '7d7d', 'payload_byte_offset': body.index(b'}}'),
                'comparison_report_sha256': 'a' * 64}
        self.assertEqual(self.expand(source, literal_cases=[case]), source)
        for altered in [source + ' changed', source.replace('}}', '}} }}')]:
            with self.assertRaises(RenderError):
                self.expand(altered, literal_cases=[case])
        with self.assertRaises(RenderError):
            self.expand(source, literal_cases=[dict(case, payload_byte_offset=0)])
        with self.assertRaises(RenderError):
            self.expand(source)


if __name__ == '__main__':
    unittest.main()
