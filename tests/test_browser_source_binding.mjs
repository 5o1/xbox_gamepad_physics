import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildVerifiedSourceBinding,
  CACHE_BUSTER_PARAMETER,
  makeCacheBustedNavigationUrl,
  recordSourceResponse,
} from './browser_source_binding.mjs';


test('cache-busted navigation preserves the requested page', () => {
  const navigation = makeCacheBustedNavigationUrl(
    'http://127.0.0.1:9898/v0.html?debug=1',
    'boundary-test',
  );
  const actual = new URL(navigation.url);
  assert.equal(actual.pathname, '/v0.html');
  assert.equal(actual.searchParams.get('debug'), '1');
  assert.equal(actual.searchParams.get(CACHE_BUSTER_PARAMETER), 'boundary-test');
});


test('browser binding accepts only observed successful boundary responses', async () => {
  const origin = 'http://127.0.0.1:9898';
  const specifications = [{request_path: '/v0.html'}, {request_path: '/registry/asset_index.json'}];
  const responses = new Map();
  for (const [index, specification] of specifications.entries()) {
    recordSourceResponse(responses, {
      method: 'Network.responseReceived',
      params: {response: {
        url: `${origin}${specification.request_path}`,
        status: index ? 204 : 200,
        fromDiskCache: false,
        fromServiceWorker: false,
      }},
    }, origin, specifications);
  }
  const navigation = makeCacheBustedNavigationUrl(`${origin}/v0.html`, 'boundary-test');
  const common = {
    responses,
    specifications,
    navigation,
    actualNavigationUrl: navigation.url,
    cache: {network_cache_disabled: true, browser_cache_cleared_before_navigation: true},
    externalAssetScope: 'verified by the viewer',
  };
  const binding = await buildVerifiedSourceBinding(common);
  assert.equal(binding.verification, 'http_boundary_only');
  assert.equal(binding.resources.length, 2);

  const missing = new Map(responses);
  missing.delete('/registry/asset_index.json');
  await assert.rejects(
    buildVerifiedSourceBinding({...common, responses: missing}),
    /not observed.*asset_index/,
  );

  const failed = new Map(responses);
  failed.set('/registry/asset_index.json', {...failed.get('/registry/asset_index.json'), status: 500});
  await assert.rejects(
    buildVerifiedSourceBinding({...common, responses: failed}),
    /HTTP 500.*asset_index/,
  );
});
