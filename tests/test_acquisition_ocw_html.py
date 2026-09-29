"""Span preservation and explicit dependency gaps for native OCW lessons."""
import base64
import hashlib
import unittest
from unittest.mock import patch

from owl.acquisition.ocw_html import localize_html, localize_css
from owl.safety import SafetyError


class OCWHTMLTests(unittest.TestCase):
    def setUp(self):
        self.args = {'member_path':'resources/lesson/index.html',
                     'output_destination':'LIBRARY/Courses/course/pages/lesson.html',
                     'member_destinations':{'resources/lesson/index.html':'LIBRARY/Courses/course/pages/lesson.html',
                         'static/a.css':'LIBRARY/Courses/course/assets/a.css',
                         'static/image.png':'LIBRARY/Courses/course/assets/image.png',
                         'static/en.vtt':'LIBRARY/Courses/course/assets/en.vtt',
                         'pages/notes/index.html':'LIBRARY/Courses/course/pages/notes.html'},
                     'media_bindings':{'https://archive.org/download/course/video.mp4':{
                         'asset_id':'pinned_video','destination':'LIBRARY/Courses/course/media/video.mp4',
                         'captions':[{'member_path':'static/en.vtt','language':'en','label':'English'}]}},
                     'caption_texts':{'static/en.vtt':'WEBVTT\n\n00:00.000 --> 00:01.000\nComplete <text> & details\n'}}
        self.video = '<video id="lesson" class="video-js vjs-default-skin custom" controls data-downloadlink="http://www.archive.org/download/course/video.mp4"><track src="../../static/en.vtt" srclang="en"><b>Fallback context</b></video>'

    def localize(self, text):
        return localize_html(text, **self.args)

    def test_span_preservation_local_links_and_complete_native_captions(self):
        prefix = '<!DOCTYPE html>\n<!-- original -->\n<h1 data-x=\'unchanged\'>A &amp; B</h1>\n<table><tr><td>Exact  42</td></tr></table><math><mi>x</mi><mo>≠</mo><mn>2</mn></math>'
        suffix = '<footer>Copyright MIT; original attribution remains.</footer>'
        text = prefix+'<a class=x href="../../pages/notes/?q=1&amp;x=2#proof">Notes</a><link rel="stylesheet" href="../../static/a.css">'+self.video+suffix
        result = self.localize(text)
        self.assertEqual(result['issues'], [])
        self.assertTrue(result['html'].startswith(prefix))
        self.assertTrue(result['html'].endswith(suffix))
        self.assertIn('href="notes.html?q=1&amp;x=2#proof"', result['html'])
        self.assertIn('href="../assets/a.css"', result['html'])
        self.assertIn('class="custom"', result['html'])
        self.assertIn('src="../media/video.mp4"',result['html'])
        self.assertIn('<b>Fallback context</b>',result['html'])
        self.assertIn('Complete &lt;text&gt; &amp; details', result['html'])
        encoded = base64.b64encode(self.args['caption_texts']['static/en.vtt'].encode()).decode()
        self.assertIn('data:text/vtt;base64,'+encoded, result['html'])
        self.assertFalse(result['content_ready'])

    def test_unresolved_local_remote_iframe_and_unknown_script_are_retained(self):
        original = '<iframe src="https://essential.example/embed"></iframe><script>fetch("https://essential.example/data")</script><a href="missing.pdf">Missing</a>'
        result = self.localize(original)
        self.assertEqual(result['html'], original)
        kinds = {x['kind'] for x in result['issues']}
        self.assertTrue({'active-remote-dependency','retained-essential-dependency','unresolved-local-link'} <= kinds)

    def test_removes_only_exact_known_runtime_after_successful_native_replacement(self):
        script = 'window.initVideoJS();'
        digest = hashlib.sha256(script.encode()).hexdigest()
        with patch('owl.acquisition.ocw_html.KNOWN_REPLACED_INLINE',{digest:'reviewed isolated bootstrap'}):
            runtime = '<script>'+script+'</script>'
            result = self.localize(self.video+runtime+'<script>essentialLocalMath()</script>')
            self.assertNotIn(runtime,result['html'])
            self.assertIn('essentialLocalMath()',result['html'])
            unchanged = self.localize(runtime)
            self.assertEqual(unchanged['html'],runtime)
            self.assertIn('unreviewed-player-runtime',{x['kind'] for x in unchanged['issues']})
            modified = self.localize(self.video+'<script>'+script+'essential()</script>')
            self.assertIn(script+'essential()',modified['html'])

    def test_missing_english_caption_or_video_binding_blocks_replacement(self):
        self.args['caption_texts'] = {}
        result = self.localize(self.video)
        self.assertIn('missing-caption-member', {x['kind'] for x in result['issues']})
        self.assertNotIn('<source', result['html'])
        self.args['media_bindings'] = {}
        result = self.localize(self.video)
        self.assertIn('unpinned-video', {x['kind'] for x in result['issues']})

    def test_timing_preserved_and_invalid_timing_reported(self):
        binding = next(iter(self.args['media_bindings'].values()))
        binding.update(start_time='12.5',end_time='25')
        result = self.localize(self.video)
        self.assertIn('video.mp4#t=12.5,25', result['html'])
        binding['end_time']='4'
        result = self.localize(self.video)
        self.assertIn('invalid-media-timing',{x['kind'] for x in result['issues']})

    def test_css_rewrites_only_urls_and_records_missing_and_external(self):
        text = "/* retain comment */ .a { color: red; background:url('../static/image.png'); } @import \"../static/a.css\"; .b {src:url(https://fonts.example/f.woff)}"
        result = localize_css(text, member_path='styles/original.css',output_destination='LIBRARY/Courses/course/assets/style.css',member_destinations=self.args['member_destinations'])
        self.assertEqual(result['css'],text.replace('../static/image.png','image.png').replace('../static/a.css','a.css'))
        self.assertEqual(result['issues'][0]['kind'],'active-remote-dependency')
        html = self.localize('<p style="background: url(../../static/image.png)">text</p>')
        self.assertIn('url(../assets/image.png)',html['html'])

    def test_bounds_unsafe_path_duplicate_attributes_and_srcset_are_explicit(self):
        with patch('owl.acquisition.ocw_html.MAX_HTML_BYTES',4):
            with self.assertRaises(SafetyError):
                self.localize('<p>too much</p>')
        result = self.localize('<img src="../../../escape" srcset="one.png 1x" src="two.png">')
        self.assertTrue({'unsafe-local-link','unsupported-srcset','duplicate-html-attribute'} <= {x['kind'] for x in result['issues']})
        self.args['output_destination']='../bad'
        with self.assertRaises(SafetyError):
            self.localize('x')

    def test_media_file_never_read_and_jsonld_and_comments_preserved(self):
        text = '<!-- <video src="fake"> -->'+'<script type="application/ld+json">{"url":"https://publisher.example"}</script>'+self.video
        with patch('pathlib.Path.open', side_effect=AssertionError('No media or file access')):
            result = self.localize(text)
        self.assertIn('<!-- <video src="fake"> -->',result['html'])
        self.assertEqual(result['issues'],[])

    def test_uppercase_markup_and_fallback_links_are_localized(self):
        video = self.video.replace('<b>Fallback context</b>', '<a href="../../pages/notes/">Fallback context</a>')
        result = self.localize('<IMG SRC="../../static/image.png" ALT="Original">'+video)
        self.assertIn('<IMG src="../assets/image.png" ALT="Original">',result['html'])
        self.assertIn('<a href="notes.html">Fallback context</a>',result['html'])
        self.assertEqual(result['issues'],[])

    def test_partial_video_replacement_retains_shared_runtime(self):
        script = 'window.initVideoJS();'
        digest = hashlib.sha256(script.encode()).hexdigest()
        with patch('owl.acquisition.ocw_html.KNOWN_REPLACED_INLINE',{digest:'reviewed isolated bootstrap'}):
            result = self.localize(self.video+'<video data-downloadlink="https://unknown/video.mp4"></video><script>'+script+'</script>')
        self.assertIn('<script>'+script+'</script>',result['html'])
        self.assertIn('unpinned-video',{x['kind'] for x in result['issues']})

    def test_known_analytics_frame_is_exact_and_independent_of_lesson_video(self):
        frame = '<iframe src="https://www.googletagmanager.com/ns.html?id=GTM-NMQZ25T" height="0"></iframe>'
        self.assertNotIn(frame,self.localize(self.video+frame)['html'])
        self.assertEqual(self.localize(frame)['html'],'')
        essential = frame.replace('GTM-NMQZ25T','changed-id')
        self.assertIn(essential,self.localize(self.video+essential)['html'])

    def test_package_root_repair_requires_exact_existing_member(self):
        self.args['member_destinations']['static_resources/exam.pdf']='LIBRARY/Courses/course/assets/exam.pdf'
        result=self.localize('<a href="./static_resources/exam.pdf">Complete exam</a><a href="./static_resources/missing.pdf">Missing</a>')
        self.assertIn('href="../assets/exam.pdf"',result['html'])
        self.assertEqual(len(result['issues']),1)
        self.assertEqual(result['rewrites'][0]['kind'],'publisher-package-root-link')

    def test_explicit_link_repair_is_exact_and_requires_pinned_target(self):
        self.args['local_link_repairs'] = {'broken.html': 'static/image.png'}
        result = self.localize('<a href="broken.html">Original label</a><img src="broken.html"><a href="other.html">Other</a>')
        self.assertIn('<a href="../assets/image.png">Original label</a>', result['html'])
        self.assertEqual(len(result['issues']), 2)
        self.assertEqual(result['rewrites'][0]['kind'], 'explicit-publisher-link-repair')
        self.args['local_link_repairs'] = {'broken.html': 'missing.html'}
        with self.assertRaises(SafetyError):
            self.localize('<a href="broken.html">Original label</a>')

    def test_exact_navbar_handler_requires_local_script_and_target(self):
        handler="$('#mobile-course-nav-toggle').click();"
        text='<button onclick="'+handler+'">Navigation</button><button id="mobile-course-nav-toggle">Menu</button><script src="../../static_shared/js/course_offline.21a26.js"></script>'
        result=self.localize(text)
        self.assertIn('retained-event-handler',{x['kind'] for x in result['issues']})
        self.args['member_destinations']['static_shared/js/course_offline.21a26.js']='LIBRARY/Courses/course/assets/course_offline.js'
        result=self.localize(text)
        self.assertEqual(result['issues'],[])
        self.assertIn(handler,result['html'])
        result=self.localize(text.replace('id="mobile-course-nav-toggle"','id="missing"'))
        self.assertIn('retained-event-handler',{x['kind'] for x in result['issues']})

    def test_timestamp_whitespace_is_normalized_without_changing_clip(self):
        next(iter(self.args['media_bindings'].values())).update(start_time=' 12 ',end_time=' 2724')
        result=self.localize(self.video)
        self.assertEqual(result['issues'],[])
        self.assertIn('video.mp4#t=12,2724',result['html'])

    def test_caption_variants_use_original_track_and_reject_missing_or_ambiguous(self):
        binding=next(iter(self.args['media_bindings'].values()))
        first=binding.pop('captions')
        self.args['member_destinations']['static/other.vtt']='LIBRARY/Courses/course/assets/other.vtt'
        self.args['caption_texts']['static/other.vtt']='WEBVTT\n\n00:00.000 --> 00:01.000\nOther caption\n'
        second=[{'member_path':'static/other.vtt','language':'en','label':'Other English'}]
        binding['caption_variants']=[{'captions':first},{'captions':second}]
        result=self.localize(self.video)
        self.assertEqual(result['issues'],[])
        self.assertIn('Complete &lt;text&gt;',result['html'])
        self.assertNotIn('Other caption',result['html'])
        result=self.localize(self.video.replace('src="../../static/en.vtt"','src="missing.vtt"'))
        self.assertIn('unresolved-caption-variant',{r['kind'] for r in result['issues']})
        binding['caption_variants'].append({'captions':first})
        result=self.localize(self.video)
        self.assertIn('ambiguous-caption-variant',{r['kind'] for r in result['issues']})

    def test_caption_variant_can_match_frozen_whole_file_sha_alias(self):
        binding=next(iter(self.args['media_bindings'].values()))
        first=binding.pop('captions')
        first[0]['sha256']='a'*64
        binding['caption_variants']=[{'captions':first}]
        binding['caption_member_sha256']={'static/alias.vtt':'a'*64}
        self.args['member_destinations']['static/alias.vtt']='LIBRARY/Courses/course/assets/alias.vtt'
        result=self.localize(self.video.replace('../../static/en.vtt','../../static/alias.vtt'))
        self.assertEqual(result['issues'],[])
        binding['caption_member_sha256']['static/alias.vtt']='b'*64
        result=self.localize(self.video.replace('../../static/en.vtt','../../static/alias.vtt'))
        self.assertIn('unresolved-caption-variant',{r['kind'] for r in result['issues']})

    def test_publisher_shared_css_image_repair_needs_exact_local_member(self):
        kwargs={'member_path':'static_shared/css/course.css','output_destination':'REFERENCE/course.css',
            'member_destinations':{'static_shared/images/asset.png':'REFERENCE/images/asset.png'}}
        result=localize_css('a{background:url(images/asset.png)}b{background:url(images/missing.png)}',**kwargs)
        self.assertEqual(len(result['issues']),1)
        self.assertEqual(result['issues'][0]['value'],'images/missing.png')
        self.assertIn('url(images/asset.png)',result['css'])

    def test_homepage_missing_info_toggle_has_source_bound_native_close(self):
        self.args['member_path']='index.html'
        self.args['member_destinations']['static_shared/js/course_offline.21a26.js']='LIBRARY/Courses/course/assets/offline.js'
        text='<div id="course-info-drawer" class="navbar-offcanvas navbar-offcanvas-right medium-and-below-only"><button type="button" id="close-mobile-course-info-button" class="btn close-mobile-course-info" aria-label="Close Course Info" onclick="$(\'#mobile-course-info-toggle\').click();">Close</button></div><script src="static_shared/js/course_offline.21a26.js"></script>'
        result=self.localize(text)
        self.assertEqual(result['issues'],[])
        self.assertIn('classList.remove',result['html'])
        self.assertIn('>Close</button>',result['html'])
        repair=next(r for r in result['rewrites'] if r['kind']=='repair-missing-homepage-info-toggle')
        self.assertIn('Offline responsive',repair['required_review'])
        result=self.localize(text.replace('navbar-offcanvas-right','unknown-drawer'))
        self.assertIn('retained-event-handler',{r['kind'] for r in result['issues']})

    def test_reviewed_decorative_omission_preserves_label_and_exact_count(self):
        import hashlib
        tag='<img class="thumbnail" src="https://images.example/missing.jpg" alt="">'
        self.args['reviewed_omissions']=[{'tag_sha256':hashlib.sha256(tag.encode()).hexdigest(),
            'kind':'decorative-image','count':1,'reason':'Optional gallery poster; adjacent lecture title and lesson link retained.'}]
        result=self.localize('<h5>Lecture 7</h5>'+tag)
        self.assertEqual(result['issues'],[])
        self.assertIn('<h5>Lecture 7</h5>',result['html'])
        self.assertNotIn('missing.jpg',result['html'])
        with self.assertRaises(ValueError):self.localize('<h5>Lecture 7</h5>')
        meaningful=tag.replace('alt=""','alt="Essential diagram"')
        self.args['reviewed_omissions'][0]['tag_sha256']=hashlib.sha256(meaningful.encode()).hexdigest()
        with self.assertRaises(ValueError):self.localize(meaningful)

    def test_reviewed_obsolete_warning_preserves_optional_reference(self):
        import hashlib
        tag='<a class="external-link-warning" href="https://publisher.example/memorial" onclick="event.preventDefault()">'
        self.args['reviewed_omissions']=[{'tag_sha256':hashlib.sha256(tag.encode()).hexdigest(),
            'kind':'obsolete-external-warning-handler','count':1,'reason':'Optional memorial link; retain label and URL without retired modal interception.'}]
        result=self.localize(tag+'Memorial</a>')
        self.assertEqual(result['issues'],[])
        self.assertIn('href="https://publisher.example/memorial"',result['html'])
        self.assertIn('Memorial</a>',result['html'])
        self.assertNotIn('onclick=',result['html'])


if __name__ == '__main__':
    unittest.main()
