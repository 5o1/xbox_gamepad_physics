import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {
  assertNavigationBinding,
  buildVerifiedSourceBinding,
  CACHE_BUSTER_PARAMETER,
  CRITICAL_SOURCE_RESOURCES,
  hashCriticalResponses,
  MATERIAL_MODULE_SOURCE_RESOURCES,
  makeCacheBustedNavigationUrl,
  prepareUncachedNetwork,
  recordCriticalResponse,
  sha256CdpBody,
  verifyLocalSourceBindings,
} from './browser_source_binding.mjs';


test('navigation URL preserves caller query and replaces the cache-buster', () => {
  const first = makeCacheBustedNavigationUrl('http://127.0.0.1:9876/?fixture=1', '12345678-first');
  const second = makeCacheBustedNavigationUrl(first.url, '12345678-second');
  const parsed = new URL(second.url);
  assert.equal(parsed.searchParams.get('fixture'), '1');
  assert.equal(parsed.searchParams.get(CACHE_BUSTER_PARAMETER), '12345678-second');
  assert.equal(parsed.searchParams.getAll(CACHE_BUSTER_PARAMETER).length, 1);
  assert.notEqual(first.url, second.url);
  assert.equal(assertNavigationBinding(second, second.url), second.url);
  assert.throws(
    () => assertNavigationBinding(second, 'http://127.0.0.1:9876/?fixture=1'),
    /cache-buster/,
  );
  assert.throws(
    () => assertNavigationBinding(second, 'http://127.0.0.1:9999/?__xbox_regression_nonce=12345678-second'),
    /origin/,
  );
  assert.throws(() => makeCacheBustedNavigationUrl('http://127.0.0.1/', 'short'), /nonce/);
});


test('network cache is disabled and cleared in a fixed pre-navigation sequence', async () => {
  const calls = [];
  const state = await prepareUncachedNetwork(async(method, params = {}) => {
    calls.push({method, params});
    return {};
  });
  assert.deepEqual(calls, [
    {method: 'Network.enable', params: {}},
    {method: 'Network.setCacheDisabled', params: {cacheDisabled: true}},
    {method: 'Network.clearBrowserCache', params: {}},
  ]);
  assert.deepEqual(state, {
    network_cache_disabled: true,
    browser_cache_cleared_before_navigation: true,
  });

  await assert.rejects(
    prepareUncachedNetwork(async method => {
      if (method === 'Network.clearBrowserCache') throw new Error('synthetic clear failure');
      return {};
    }),
    /synthetic clear failure/,
  );
});


test('CDP text and base64 bodies are hashed as exact bytes', () => {
  const expected = createHash('sha256').update(Buffer.from([0, 1, 2, 255])).digest('hex');
  assert.equal(sha256CdpBody({body: 'AAEC/w==', base64Encoded: true}).sha256, expected);
  assert.equal(sha256CdpBody({body: '手柄', base64Encoded: false}).byte_length, Buffer.byteLength('手柄'));
  assert.throws(() => sha256CdpBody({}), /missing/);
});


test('critical response capture rejects cache reuse and fails closed on missing resources', async () => {
  const responses = new Map();
  const origin = 'http://127.0.0.1:9876';
  for (const [index, resource] of CRITICAL_SOURCE_RESOURCES.entries()) {
    assert.equal(recordCriticalResponse(responses, {
      method: 'Network.responseReceived',
      params: {
        requestId: String(index),
        response: {
          url: `${origin}${resource.request_path}?ignored=query`,
          status: 200,
          mimeType: 'application/octet-stream',
          fromDiskCache: false,
          fromServiceWorker: false,
        },
      },
    }, origin), true);
  }
  const calls = [];
  const resources = await hashCriticalResponses(async(method, params) => {
    calls.push({method, params});
    return {body: Buffer.from(`body-${params.requestId}`).toString('base64'), base64Encoded: true};
  }, responses);
  assert.equal(resources.length, CRITICAL_SOURCE_RESOURCES.length);
  assert.ok(resources.every(resource => /^[0-9a-f]{64}$/.test(resource.sha256)));
  assert.ok(calls.every(call => call.method === 'Network.getResponseBody'));

  const missing = new Map(responses);
  missing.delete('/app.mjs');
  const bodyFor = async(method, params) => ({
    body: Buffer.from(`body-${params.requestId}`).toString('base64'),
    base64Encoded: true,
  });
  await assert.rejects(hashCriticalResponses(bodyFor, missing), /not observed.*app\.mjs/);

  const cached = new Map(responses);
  cached.set('/app.mjs', {...cached.get('/app.mjs'), from_disk_cache: true});
  await assert.rejects(hashCriticalResponses(bodyFor, cached), /directly from the server.*app\.mjs/);

  const duplicate = new Map(
    [...responses].map(([requestPath, response]) => [
      requestPath,
      {...response, duplicate_response_urls: [...response.duplicate_response_urls]},
    ]),
  );
  const firstRequestId = duplicate.get('/app.mjs').requestId;
  assert.equal(recordCriticalResponse(duplicate, {
    method: 'Network.responseReceived',
    params: {
      requestId: 'replacement-must-not-win',
      response: {
        url: `${origin}/app.mjs`,
        status: 200,
        mimeType: 'text/javascript',
        fromDiskCache: false,
        fromServiceWorker: false,
      },
    },
  }, origin), true);
  assert.equal(duplicate.get('/app.mjs').requestId, firstRequestId);
  assert.equal(duplicate.get('/app.mjs').response_occurrence_count, 2);
  await assert.rejects(
    hashCriticalResponses(bodyFor, duplicate),
    /observed more than once.*app\.mjs/,
  );
});


test('capture binding compares served material HTML and JS with exact worktree bytes', async () => {
  const origin = 'http://127.0.0.1:9877';
  const navigation = makeCacheBustedNavigationUrl(
    `${origin}/material_check.html`,
    '12345678-material',
  );
  const specifications = [
    {request_path: '/material_check.html', binding_kind: 'workspace', binding_path: 'viewer/material_check.html'},
    {request_path: '/material_check.mjs', binding_kind: 'workspace', binding_path: 'viewer/material_check.mjs'},
  ];
  const bodies = new Map();
  const responses = new Map();
  for (const [index, specification] of specifications.entries()) {
    const bytes = await readFile(new URL(`../${specification.binding_path}`, import.meta.url));
    bodies.set(String(index), bytes);
    responses.set(specification.request_path, {
      requestId: String(index),
      response_url: `${origin}${specification.request_path}`,
      status: 200,
      mime_type: 'application/octet-stream',
      from_disk_cache: false,
      from_service_worker: false,
      response_occurrence_count: 1,
      duplicate_response_urls: [],
    });
  }
  const call = async(method, {requestId}) => {
    assert.equal(method, 'Network.getResponseBody');
    return {body: bodies.get(requestId).toString('base64'), base64Encoded: true};
  };
  const binding = await buildVerifiedSourceBinding({
    call,
    responses,
    specifications,
    navigation,
    actualNavigationUrl: navigation.url,
    cache: {network_cache_disabled: true, browser_cache_cleared_before_navigation: true},
    externalAssetScope: 'synthetic unit-test scope',
  });
  assert.equal(binding.local_verification.verified, true);
  assert.equal(binding.local_verification.workspace_resource_count, 2);
  assert.equal(binding.navigation_url, navigation.url);

  const tampered = new Map(bodies);
  tampered.set('1', Buffer.from('tampered'));
  await assert.rejects(
    buildVerifiedSourceBinding({
      call: async(method, {requestId}) => ({
        body: tampered.get(requestId).toString('base64'),
        base64Encoded: true,
      }),
      responses,
      specifications,
      navigation,
      actualNavigationUrl: navigation.url,
      cache: {network_cache_disabled: true, browser_cache_cleared_before_navigation: true},
      externalAssetScope: 'synthetic unit-test scope',
    }),
    /does not match the worktree|SHA-256 does not match/,
  );
});


test('material capture binds its complete Three 0.180.0 module graph', async () => {
  assert.deepEqual(
    new Set(MATERIAL_MODULE_SOURCE_RESOURCES.map(item => item.request_path)),
    new Set([
      '/material_check.mjs',
      '/vendor/build/three.module.js',
      '/vendor/examples/jsm/loaders/GLTFLoader.js',
      '/vendor/examples/jsm/controls/OrbitControls.js',
      '/vendor/examples/jsm/environments/RoomEnvironment.js',
      '/vendor/examples/jsm/utils/BufferGeometryUtils.js',
    ]),
  );
  const threeRecord = JSON.parse(
    await readFile(new URL('../sources/viewer_design.json', import.meta.url), 'utf8'),
  ).dependencies.extracted_files;
  const resources = [];
  for (const specification of MATERIAL_MODULE_SOURCE_RESOURCES) {
    let bytes;
    let digest;
    if (specification.binding_kind === 'workspace') {
      bytes = await readFile(new URL(`../${specification.binding_path}`, import.meta.url));
      digest = createHash('sha256').update(bytes).digest('hex');
    } else {
      digest = threeRecord[specification.binding_path];
      bytes = Buffer.from('served vendor byte length is reported by CDP');
    }
    resources.push({
      ...specification,
      response_url: `http://127.0.0.1:9877${specification.request_path}`,
      status: 200,
      from_disk_cache: false,
      from_service_worker: false,
      response_occurrence_count: 1,
      duplicate_response_urls: [],
      byte_length: bytes.length,
      sha256: digest,
    });
  }
  const verification = await verifyLocalSourceBindings(
    resources,
    MATERIAL_MODULE_SOURCE_RESOURCES,
  );
  assert.equal(verification.verified, true);
  assert.equal(verification.three_source_record_resource_count, 5);

  const tampered = resources.map(resource => ({...resource}));
  tampered.find(resource => resource.request_path.endsWith('/GLTFLoader.js')).sha256 = '0'.repeat(64);
  await assert.rejects(
    verifyLocalSourceBindings(tampered, MATERIAL_MODULE_SOURCE_RESOURCES),
    /SHA-256 does not match.*GLTFLoader/,
  );
});


test('browser harness publishes the failure marker for CDP setup failures', async () => {
  const source = await readFile(new URL('browser_harness.mjs', import.meta.url), 'utf8');
  const setup = source.indexOf('let client=null');
  const tryStart = source.indexOf('try{', setup);
  const pageList = source.indexOf('fetch(`${cdpUrl}/json/list`');
  const connect = source.indexOf('connectCdp(page.webSocketDebuggerUrl)');
  const catchStart = source.indexOf('}catch(error){');
  const attemptWrite = source.indexOf("writeFile(join(output.directory,'browser_last_attempt.json')", catchStart);
  const selectedPublish = source.indexOf("output.finalize({files:['browser_last_attempt.json']})", catchStart);
  assert.ok(tryStart >= 0 && pageList > tryStart, 'CDP page-list lookup escapes the failure-marker try/catch');
  assert.ok(connect > pageList && connect < catchStart, 'CDP connect escapes the failure-marker try/catch');
  assert.ok(attemptWrite > catchStart, 'catch does not stage browser_last_attempt.json');
  assert.ok(selectedPublish > attemptWrite, 'catch does not publish only browser_last_attempt.json');
  assert.match(
    source,
    /new PointerEvent\('pointercancel',\{pointerId:POINTER,bubbles:true\}\)/,
    'synthetic pointercancel must carry the active pointer id used by OrbitControls',
  );
});
