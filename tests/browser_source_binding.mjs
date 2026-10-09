import {randomUUID} from 'node:crypto';


export const CACHE_BUSTER_PARAMETER = '__xbox_regression_nonce';

// Browser acceptance checks only the external HTTP boundaries it relies on.
// scripts/serve_viewer.py and the pages validate repository JSON structurally
// and verify external binary assets where identity matters. Hashing every served
// repository file again would only duplicate Git and test the test harness.
export const CRITICAL_SOURCE_RESOURCES = Object.freeze([
  {request_path: '/'},
  {request_path: '/registry/asset_index.json'},
]);

export const MATERIAL_MODULE_SOURCE_RESOURCES = Object.freeze([
  {request_path: '/material_check.mjs'},
]);

export const V0_SOURCE_RESOURCES = Object.freeze([
  {request_path: '/v0.html'},
  {request_path: '/registry/asset_index.json'},
  {request_path: '/generated/kinematics/xbox_one_s_estimated_v0.json'},
  {request_path: '/evidence/appearance_matched_estimated_v0.json'},
]);


export function makeCacheBustedNavigationUrl(baseUrl, nonce = randomUUID()) {
  if (typeof nonce !== 'string' || nonce.length < 8) {
    throw new Error('Navigation cache-buster nonce must contain at least eight characters');
  }
  const url = new URL(baseUrl);
  url.searchParams.set(CACHE_BUSTER_PARAMETER, nonce);
  return {url: url.href, nonce, parameter: CACHE_BUSTER_PARAMETER};
}


export async function prepareUncachedNetwork(call) {
  await call('Network.enable');
  await call('Network.setCacheDisabled', {cacheDisabled: true});
  await call('Network.clearBrowserCache');
  return {network_cache_disabled: true, browser_cache_cleared_before_navigation: true};
}


export function assertNavigationBinding(navigation, actualNavigationUrl) {
  const requested = new URL(navigation.url);
  const actual = new URL(actualNavigationUrl);
  if (actual.origin !== requested.origin || actual.pathname !== requested.pathname) {
    throw new Error('Navigation changed origin or path');
  }
  if (actual.searchParams.get(navigation.parameter) !== navigation.nonce) {
    throw new Error('Navigation lost its cache-buster');
  }
  return actual.href;
}


export function recordSourceResponse(responses, message, expectedOrigin, specifications) {
  if (message.method !== 'Network.responseReceived') return false;
  const response = message.params?.response;
  if (!response?.url) return false;
  let url;
  try {
    url = new URL(response.url);
  } catch {
    return false;
  }
  if (url.origin !== expectedOrigin) return false;
  const specification = specifications.find(item => item.request_path === url.pathname);
  if (!specification) return false;
  if (!responses.has(specification.request_path)) {
    responses.set(specification.request_path, {
      request_path: specification.request_path,
      response_url: response.url,
      status: response.status,
      from_disk_cache: response.fromDiskCache === true,
      from_service_worker: response.fromServiceWorker === true,
    });
  }
  return true;
}


export function recordCriticalResponse(responses, message, expectedOrigin) {
  return recordSourceResponse(responses, message, expectedOrigin, CRITICAL_SOURCE_RESOURCES);
}


export async function buildVerifiedSourceBinding({
  responses,
  specifications,
  navigation,
  actualNavigationUrl,
  cache,
  externalAssetScope,
}) {
  if (!cache?.network_cache_disabled || !cache?.browser_cache_cleared_before_navigation) {
    throw new Error('Browser cache was not disabled and cleared before navigation');
  }
  const navigationUrl = assertNavigationBinding(navigation, actualNavigationUrl);
  const resources = specifications.map(specification => {
    const observed = responses.get(specification.request_path);
    if (!observed) throw new Error(`Browser boundary was not observed: ${specification.request_path}`);
    if (observed.status < 200 || observed.status >= 300) {
      throw new Error(`Browser boundary returned HTTP ${observed.status}: ${specification.request_path}`);
    }
    if (observed.from_disk_cache || observed.from_service_worker) {
      throw new Error(`Browser boundary was not fetched from the server: ${specification.request_path}`);
    }
    return observed;
  });
  return {
    verification: 'http_boundary_only',
    cache,
    requested_navigation_url: navigation.url,
    navigation_url: navigationUrl,
    resources,
    external_asset_scope: externalAssetScope,
  };
}
