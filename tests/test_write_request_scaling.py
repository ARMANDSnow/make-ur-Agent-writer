"""No runtime products or providers: request count admission and UI behavior."""
import subprocess
import unittest
from src.web import routes, static


class WriteRequestScalingTests(unittest.TestCase):
    def test_chapter_scaled_defaults_and_bounds(self):
        for chapters, expected in [(1, 20), (3, 60), (9, 160)]:
            with self.subTest(chapters=chapters):
                error, params = routes._validated_run_params('write-book', {'chapters': chapters})
                self.assertIsNone(error)
                self.assertEqual(params['max_model_requests'], expected)
                error, params = routes._validated_run_params('write-book', {'chapters': chapters, 'max_model_requests': 10})
                self.assertIsNone(error)
                self.assertEqual(params['max_model_requests'], 10)
                error, params = routes._validated_run_params('write-book', {'chapters': chapters, 'max_model_requests': 161})
                self.assertIsNotNone(error)
        self.assertIsNotNone(routes._validated_run_params('write-book', {'chapters': True})[0])

    def test_explicit_writing_allowance_independent_of_defaults(self):
        for chapters, limit in [(1, 22), (3, 100), (1, 160)]:
            error, params = routes._validated_run_params('write-book', {'chapters': chapters, 'max_model_requests': limit})
            self.assertIsNone(error)
            self.assertEqual(params['max_model_requests'], limit)
        for invalid in (161, 0, -1, True, 2.5):
            self.assertIsNotNone(routes._validated_run_params('write-book', {'max_model_requests': invalid})[0])

    def test_recovery_preserves_explicit_request_allowance(self):
        source = static.JS_DASHBOARD.split('  function writeRecoveryParams(chapter) {', 1)[1].split('  function writeRecoveryStateCopy', 1)[0]
        script = 'function writeRecoveryParams(chapter) {' + source + r'''
const assert=require('assert');
const NOVEL_STAGE_LIMITS={'write-book':{budget_cny:6,timeout_minutes:45,max_model_requests:20}};
const elements={max_model_requests:{value:'100'},budget_cny:{value:'6'},timeout_minutes:{value:'45'}};
const document={getElementById(){return {elements};}};
assert.equal(writeRecoveryParams(1).max_model_requests,100);
delete elements.max_model_requests;
assert.equal(writeRecoveryParams(1).max_model_requests,20);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_browser_default_scales_but_manual_input_survives(self):
        source = static.JS_DASHBOARD.split('  function bindWriteRequestLimit(form) {', 1)[1].split('  function bindWriteBook()', 1)[0]
        preset_source = static.JS_DASHBOARD.split('  function bindWritePresets(form) {', 1)[1].split('  function bindWriteRequestLimit(form)', 1)[0]
        script = 'function bindWriteRequestLimit(form) {' + source + 'function bindWritePresets(form) {' + preset_source + r'''
const assert = require('assert');
function field(value) { return {value, listeners:{}, addEventListener(n, fn){this.listeners[n]=fn;}, dispatchEvent(e){this.listeners[e.type]();}}; }
const chapters = field('1'); const limit = field('20');
bindWriteRequestLimit({elements:{chapters,max_model_requests:limit}});
chapters.value='3'; chapters.listeners.input();
assert.equal(limit.value,'60'); assert.equal(limit.max,'160');
chapters.value='9'; chapters.listeners.input();
assert.equal(limit.value,'160'); assert.equal(limit.max,'160');
const btn={getAttribute(){return 'trial';},classList:{toggle(){}},setAttribute(){}};
const toggle={addEventListener(n,fn){this.click=fn;},querySelectorAll(){return [btn];}};
const document={getElementById(){return toggle;}};
const WRITE_PRESETS={trial:{chapters:1}}; function scheduleReadiness(){}
bindWritePresets({elements:{chapters,max_model_requests:limit}});
toggle.click({target:{closest(){return btn;}}});
assert.equal(chapters.value,'1'); assert.equal(limit.value,'20'); assert.equal(limit.max,'160');
limit.value='12'; limit.listeners.input();
chapters.value='3'; chapters.listeners.input();
assert.equal(limit.value,'12'); assert.equal(limit.max,'160');
limit.value='100'; limit.listeners.input();
chapters.value='1'; chapters.listeners.input();
assert.equal(limit.value,'100'); assert.equal(limit.max,'160'); // preserve explicit authorization
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('bindWriteRequestLimit(document.getElementById("write-book-form"))', static.JS_DASHBOARD)
        self.assertIn('bindWriteRequestLimit(form)', static.JS_DASHBOARD.split('function bindWriteBook()',1)[1])
