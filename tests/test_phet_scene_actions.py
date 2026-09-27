"""PhET scene QA contract using synthetic local files and a browser test double."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check_phet.cjs"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is required for the PhET harness")
class PhetSceneTests(unittest.TestCase):
    def run_node(self, code):
        return subprocess.run([NODE, "-e", code], text=True, capture_output=True, check=False)

    def test_scene_action_validation_rejects_ambiguous_or_ignored_fields(self):
        invalid = [
            {"scene": ["view"]}, {"scene": "view.0", "role": "button"},
            {"scene": "view.0", "click": [1, 2]}, {"click": [1, 2], "drag_to_scene": "view.1"},
            {"role": "button", "fraction": [.5, .5]}, {"scene": "view.0", "key": "Enter"},
            {"scene": "view.0", "drag_to_scene": "view.1", "hold_ms": 20},
            {"click": [1, 2], "hold_ms": 20}, {"scene": "view", "viewport_width": "390"},
            {"scene": "view", "viewport_width": 0}, {"scene": "view", "viewport_width": 99999},
            {"scene": "view", "fraction": None}, {"scene": "view.0", "drag_to_scene": []},
            {"role": "button", "hold_ms": 20},
        ]
        code = f"""
          const {{validateActions}} = require({json.dumps(str(CHECKER))});
          const invalid = {json.dumps(invalid)};
          const accepted = invalid.flatMap((action,index) => {{
            try {{ validateActions([action]); return [index]; }} catch {{ return []; }}
          }});
          console.log(JSON.stringify(accepted));
        """
        result = self.run_node(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [], "Malformed actions must fail before browser execution")

    def test_valid_reviewed_scene_click_drag_and_hold_actions(self):
        valid = [{"scene": "view.1", "fraction": [0, 1], "viewport_width": 390},
                 {"scene": "view.1", "drag_to_scene": "view.2"},
                 {"scene": "view.1", "hold_ms": 20},
                 {"role": "button", "name": "Push", "key": "Space", "hold_ms": 20}]
        result = self.run_node(f"require({json.dumps(str(CHECKER))}).validateActions({json.dumps(valid)})")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inspection_allows_reviewed_entry_but_never_interacts_resets_or_certifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "simulation.html"
            source.write_text("<html>Synthetic fixture</html>")
            manifest = root / "checks.json"
            manifest.write_text(json.dumps({"assets": [{"id": "scene_fixture", "destination": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "entry": [{"role": "button", "name": "Intro Screen", "key": "Enter"}],
                "interaction": [{"scene": "view.0"}], "reset": [{"scene": "view.1"}],
                "expected_changed_keys": ["chargeProperty"]}], "viewports": [{"width": 390, "height": 844}]}))
            calls = root / "calls.json"
            fake = root / "playwright.cjs"
            fake.write_text("""
              const fs = require('node:fs');
              const calls = [];
              function freeze(value) {
                if(value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
                return value;
              }
              const node = () => ({visible:true,text:'Read-only label',_inputListeners:[{}],children:[],
                localBounds:{},localToGlobalBounds(){return {minX:10,minY:10,maxX:40,maxY:30};}});
              global.phet = freeze({joist:{sim:{frameCounter:30,selectedScreenProperty:{value:{view:node(),model:{chargeProperty:{value:0}}}}}}});
              global.innerWidth=390;global.innerHeight=844;
              global.requestAnimationFrame=callback=>callback();
              const page = {on(){}, async goto(){}, async waitForFunction(fn){if(!fn())throw Error('not ready');},
                async evaluate(fn,arg){return fn(arg);},
                getByRole(role,options){
                  if(role!=='button'||options.name!=='Intro Screen')throw Error('unexpected input control');
                  return {first(){return this;},async press(key){calls.push('entry:'+key);}};
                },mouse:{async click(){throw Error('inspection must not interact');}},
              };
              const context={async route(){},async newPage(){return page;},async close(){}};
              module.exports={chromium:{async launch(){return {version(){return 'test-double';},
                async newContext(){return context;},async close(){fs.writeFileSync(CALLS,JSON.stringify(calls));}};}}};
            """.replace("CALLS", json.dumps(str(calls))))
            report = root / "report.json"
            result = subprocess.run([NODE, str(CHECKER), "--manifest", str(manifest), "--root", str(root),
                "--output", str(report), "--playwright", str(fake), "--inspect-only"],
                text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1, result.stderr)
            evidence = json.loads(report.read_text())
            self.assertEqual(json.loads(calls.read_text()), ["entry:Enter"])
            self.assertFalse(evidence["success"])
            self.assertEqual(evidence["physical_device_certification"], "pending")
            check = evidence["checks"][0]
            self.assertTrue(check["inspection"]["root_found"])
            self.assertTrue(check["inspection"]["nodes"])
            self.assertNotIn("before", check)
            self.assertNotIn("after", check)
            self.assertNotIn("reset", check)
            self.assertFalse(check["success"])

    def test_hidden_ancestor_and_zero_area_scene_cannot_click_unrelated_control(self):
        for hidden, zero in [(True, False), (False, True)]:
            with self.subTest(hidden_ancestor=hidden, zero_area=zero), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "simulation.html"
                source.write_text("<html>Synthetic fixture</html>")
                manifest = root / "checks.json"
                manifest.write_text(json.dumps({"assets": [{"id": "scene_fixture", "destination": source.name,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "interaction": [{"scene": "view.0.0"}],
                    "expected_changed_keys": ["chargeProperty"]}], "viewports": [{"width": 390, "height": 844}]}))
                fake = root / "playwright.cjs"
                fake.write_text("""
                  const model={chargeProperty:{value:0}};
                  const control={visible:true,children:[],localBounds:{},localToGlobalBounds(){
                    return {minX:10,minY:10,maxX:ZERO?10:40,maxY:ZERO?10:30};}};
                  const view={visible:true,children:[{visible:!HIDDEN,children:[control]}]};
                  global.phet={joist:{sim:{frameCounter:30,selectedScreenProperty:{value:{view,model}}}}};
                  global.innerWidth=390;global.innerHeight=844;
                  global.requestAnimationFrame=callback=>callback();
                  global.document={documentElement:{scrollWidth:390},querySelectorAll(){return [{getBoundingClientRect(){
                    return {width:390,height:844,right:390,bottom:844,left:0,top:0};}}];}};
                  const page={on(){},async goto(){},async waitForFunction(fn){if(!fn())throw Error('not ready');},
                    async evaluate(fn,arg){return fn(arg);},getByRole(role,options){
                      if(role!=='button'||options.name!=='Reset All')throw Error('unexpected input');
                      return {first(){return this;},async press(){model.chargeProperty.value=0;}};
                    },mouse:{async click(){model.chargeProperty.value=1;}}};
                  const context={async route(){},async newPage(){return page;},async close(){}};
                  module.exports={chromium:{async launch(){return {version(){return 'test-double';},
                    async newContext(){return context;},async close(){}};}}};
                """.replace("ZERO", json.dumps(zero)).replace("HIDDEN", json.dumps(hidden)))
                report = root / "report.json"
                result = subprocess.run([NODE, str(CHECKER), "--manifest", str(manifest), "--root", str(root),
                    "--output", str(report), "--playwright", str(fake)], text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1, result.stderr)
                evidence = json.loads(report.read_text())
                self.assertFalse(evidence["success"])
                self.assertNotIn("after", evidence["checks"][0], "Invalid scene must fail before mouse input")


if __name__ == "__main__":
    unittest.main()
