import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';


const scripts = [
  'capture_sketchfab_reference.mjs',
  'capture_sketchfab_camera_axes.mjs',
  'material_browser_harness.mjs',
];


for (const name of scripts) {
  test(`${name} binds an uncached navigation before publishing`, async () => {
    const source = await readFile(new URL(name, import.meta.url), 'utf8');
    const cache = source.indexOf('prepareUncachedNetwork(call)');
    const navigate = source.indexOf("call('Page.navigate'");
    const binding = source.indexOf('buildVerifiedSourceBinding({');
    const closeTarget = source.indexOf('closeCdpTarget(base');
    const publish = source.indexOf('output.finalize()');
    assert.ok(cache >= 0, 'missing cache preparation');
    assert.ok(navigate > cache, 'navigation occurs before cache preparation');
    assert.ok(binding > navigate, 'source binding occurs before navigation');
    assert.ok(closeTarget > binding, 'CDP target cleanup occurs before source verification');
    assert.ok(publish > closeTarget, 'artifacts can publish before CDP target cleanup');
    assert.ok(publish > binding, 'artifacts can publish before source verification');
    assert.match(source, /navigation_url/);
    assert.match(source, /source_binding/);
  });
}


test('Sketchfab captures bind only the local entry and record the model UID', async () => {
  for (const name of scripts.slice(0, 2)) {
    const source = await readFile(new URL(name, import.meta.url), 'utf8');
    assert.match(source, /binding_path:'viewer\/sketchfab_reference\.html'/);
    assert.doesNotMatch(source, /binding_path:.*iframe|binding_path:.*sketchfab\.com/);
    assert.match(source, /model_uid/);
  }
});


test('material capture starts blank and binds both local material files', async () => {
  const source = await readFile(new URL('material_browser_harness.mjs', import.meta.url), 'utf8');
  assert.match(source, /json\/new\?about:blank/);
  assert.match(source, /binding_path:'viewer\/material_check\.html'/);
  assert.match(source, /MATERIAL_MODULE_SOURCE_RESOURCES/);
  assert.match(source, /audit\.threeRevision!=='180'/);
  assert.match(source, /model_source_sha256/);
});


test('failed browser publish replaces only the last-attempt marker', async () => {
  const source = await readFile(new URL('browser_harness.mjs', import.meta.url), 'utf8');
  const failure = source.slice(source.indexOf('}catch(error){'));
  assert.match(
    failure,
    /output\.finalize\(\{files:\['browser_last_attempt\.json'\]\}\)/,
  );
  assert.doesNotMatch(failure, /output\.finalize\(\);/);
});
