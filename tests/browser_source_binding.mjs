import {createHash, randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';


export const CACHE_BUSTER_PARAMETER = '__xbox_regression_nonce';

// These are code/data bytes served by scripts/serve_viewer.py and required by
// the exercised page.  External OBJ files deliberately remain outside this
// list: their separately reviewed inventory is the asset-identity boundary.
export const CRITICAL_SOURCE_RESOURCES = Object.freeze([
  {request_path: '/', binding_kind: 'workspace', binding_path: 'viewer/index.html'},
  {request_path: '/app.mjs', binding_kind: 'workspace', binding_path: 'viewer/app.mjs'},
  {request_path: '/gamepad_state.mjs', binding_kind: 'workspace', binding_path: 'viewer/gamepad_state.mjs'},
  {request_path: '/rig.mjs', binding_kind: 'workspace', binding_path: 'viewer/rig.mjs'},
  {request_path: '/drag2d.mjs', binding_kind: 'workspace', binding_path: 'viewer/drag2d.mjs'},
  {request_path: '/diagnostics.mjs', binding_kind: 'workspace', binding_path: 'viewer/diagnostics.mjs'},
  {request_path: '/assembly_constraints.mjs', binding_kind: 'workspace', binding_path: 'viewer/assembly_constraints.mjs'},
  {
    request_path: '/vendor/build/three.module.js',
    binding_kind: 'three_source_record',
    binding_path: 'build/three.module.js',
  },
  {
    request_path: '/vendor/build/three.core.js',
    binding_kind: 'three_source_record',
    binding_path: 'build/three.core.js',
  },
  {
    request_path: '/vendor/examples/jsm/loaders/OBJLoader.js',
    binding_kind: 'three_source_record',
    binding_path: 'examples/jsm/loaders/OBJLoader.js',
  },
  {
    request_path: '/vendor/examples/jsm/controls/OrbitControls.js',
    binding_kind: 'three_source_record',
    binding_path: 'examples/jsm/controls/OrbitControls.js',
  },
  {
    request_path: '/registry/asset_index.json',
    binding_kind: 'workspace',
    binding_path: 'assets/asset_index.json',
  },
  {
    request_path: '/reference/identity_front.png',
    binding_kind: 'workspace',
    binding_path: 'results/legacy_casper_1914_visual_parts/identity_front.png',
  },
]);


// Complete JavaScript module graph executed by viewer/material_check.mjs.
// GLTFLoader's only local addon dependency is BufferGeometryUtils; the other
// addon imports resolve directly to the Three core module through the page's
// import map. Every vendor digest is sourced from sources/viewer_design.json.
export const MATERIAL_MODULE_SOURCE_RESOURCES = Object.freeze([
  {
    request_path: '/material_check.mjs',
    binding_kind: 'workspace',
    binding_path: 'viewer/material_check.mjs',
  },
  {
    request_path: '/vendor/build/three.module.js',
    binding_kind: 'three_source_record',
    binding_path: 'build/three.module.js',
  },
  {
    request_path: '/vendor/build/three.core.js',
    binding_kind: 'three_source_record',
    binding_path: 'build/three.core.js',
  },
  {
    request_path: '/vendor/examples/jsm/loaders/GLTFLoader.js',
    binding_kind: 'three_source_record',
    binding_path: 'examples/jsm/loaders/GLTFLoader.js',
  },
  {
    request_path: '/vendor/examples/jsm/controls/OrbitControls.js',
    binding_kind: 'three_source_record',
    binding_path: 'examples/jsm/controls/OrbitControls.js',
  },
  {
    request_path: '/vendor/examples/jsm/environments/RoomEnvironment.js',
    binding_kind: 'three_source_record',
    binding_path: 'examples/jsm/environments/RoomEnvironment.js',
  },
  {
    request_path: '/vendor/examples/jsm/utils/BufferGeometryUtils.js',
    binding_kind: 'three_source_record',
    binding_path: 'examples/jsm/utils/BufferGeometryUtils.js',
  },
]);


// Complete workspace/vendor graph executed by the schema-2 estimated-v0 page.
// The external inventory and GLB are verified in-page against the canonical
// registry/profile hashes because their large bytes deliberately live on the
// GPU node rather than in this Git worktree.
export const V0_SOURCE_RESOURCES = Object.freeze([
  {request_path: '/v0.html', binding_kind: 'workspace', binding_path: 'viewer/v0.html'},
  {request_path: '/v0_app.mjs', binding_kind: 'workspace', binding_path: 'viewer/v0_app.mjs'},
  {request_path: '/gamepad_state.mjs', binding_kind: 'workspace', binding_path: 'viewer/gamepad_state.mjs'},
  {request_path: '/drag2d.mjs', binding_kind: 'workspace', binding_path: 'viewer/drag2d.mjs'},
  {request_path: '/schema2_runtime.mjs', binding_kind: 'workspace', binding_path: 'viewer/schema2_runtime.mjs'},
  {request_path: '/registry/asset_index.json', binding_kind: 'workspace', binding_path: 'assets/asset_index.json'},
  {request_path: '/registry/appearance_matched_estimated_v0/viewer_profile.json', binding_kind: 'workspace', binding_path: 'assets/appearance_matched_estimated_v0/viewer_profile.json'},
  {request_path: '/evidence/appearance_matched_estimated_v0.json', binding_kind: 'workspace', binding_path: 'sources/appearance_matched_estimated_v0.json'},
  {request_path: '/candidate-reference/pos_z.png', binding_kind: 'workspace', binding_path: 'results/xbox_one_s_batonyrobson_UNVERIFIED/pos_z.png'},
  {request_path: '/vendor/build/three.module.js', binding_kind: 'three_source_record', binding_path: 'build/three.module.js'},
  {request_path: '/vendor/build/three.core.js', binding_kind: 'three_source_record', binding_path: 'build/three.core.js'},
  {request_path: '/vendor/examples/jsm/loaders/GLTFLoader.js', binding_kind: 'three_source_record', binding_path: 'examples/jsm/loaders/GLTFLoader.js'},
  {request_path: '/vendor/examples/jsm/controls/OrbitControls.js', binding_kind: 'three_source_record', binding_path: 'examples/jsm/controls/OrbitControls.js'},
  {request_path: '/vendor/examples/jsm/environments/RoomEnvironment.js', binding_kind: 'three_source_record', binding_path: 'examples/jsm/environments/RoomEnvironment.js'},
  {request_path: '/vendor/examples/jsm/utils/BufferGeometryUtils.js', binding_kind: 'three_source_record', binding_path: 'examples/jsm/utils/BufferGeometryUtils.js'},
]);


export function makeCacheBustedNavigationUrl(baseUrl, nonce = randomUUID()) {
  if (typeof nonce !== 'string' || nonce.length < 8) {
    throw new Error('Navigation cache-buster nonce must be a non-empty unpredictable string');
  }
  const url = new URL(baseUrl);
  url.searchParams.set(CACHE_BUSTER_PARAMETER, nonce);
  return {url: url.href, nonce, parameter: CACHE_BUSTER_PARAMETER};
}


export async function prepareUncachedNetwork(call) {
  await call('Network.enable');
  await call('Network.setCacheDisabled', {cacheDisabled: true});
  await call('Network.clearBrowserCache');
  return {
    network_cache_disabled: true,
    browser_cache_cleared_before_navigation: true,
  };
}


export function assertNavigationBinding(navigation, actualNavigationUrl) {
  const requested = new URL(navigation.url);
  const actual = new URL(actualNavigationUrl);
  if (actual.origin !== requested.origin) throw new Error('Navigation changed origin');
  if (actual.pathname !== requested.pathname) throw new Error('Navigation changed path');
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
  const existing = responses.get(specification.request_path);
  if (existing) {
    // Preserve the first response, which is the one the module graph could
    // have executed. A later response must never replace its evidence.
    existing.response_occurrence_count += 1;
    existing.duplicate_response_urls.push(response.url);
    return true;
  }
  responses.set(specification.request_path, {
    requestId: message.params.requestId,
    response_url: response.url,
    status: response.status,
    mime_type: response.mimeType,
    from_disk_cache: response.fromDiskCache === true,
    from_service_worker: response.fromServiceWorker === true,
    response_occurrence_count: 1,
    duplicate_response_urls: [],
  });
  return true;
}


export function recordCriticalResponse(responses, message, expectedOrigin) {
  return recordSourceResponse(
    responses,
    message,
    expectedOrigin,
    CRITICAL_SOURCE_RESOURCES,
  );
}


export function sha256CdpBody(body) {
  if (!body || typeof body.body !== 'string') {
    throw new Error('CDP response body is missing');
  }
  const bytes = body.base64Encoded
    ? Buffer.from(body.body, 'base64')
    : Buffer.from(body.body, 'utf8');
  return {
    byte_length: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
  };
}


export async function hashSourceResponses(call, responses, specifications) {
  const resources = [];
  for (const specification of specifications) {
    const observed = responses.get(specification.request_path);
    if (!observed) {
      throw new Error(`Critical browser response was not observed: ${specification.request_path}`);
    }
    if (observed.response_occurrence_count !== 1
        || observed.duplicate_response_urls?.length !== 0) {
      throw new Error(`Critical browser response was observed more than once: ${specification.request_path}`);
    }
    if (observed.status !== 200) {
      throw new Error(`Critical browser response was HTTP ${observed.status}: ${specification.request_path}`);
    }
    if (observed.from_disk_cache || observed.from_service_worker) {
      throw new Error(`Critical browser response did not come directly from the server: ${specification.request_path}`);
    }
    const body = await call('Network.getResponseBody', {requestId: observed.requestId});
    resources.push({...specification, ...observed, ...sha256CdpBody(body)});
  }
  return resources;
}


export async function hashCriticalResponses(call, responses) {
  return hashSourceResponses(call, responses, CRITICAL_SOURCE_RESOURCES);
}


function validDigest(value) {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
}


export async function verifyLocalSourceBindings(resources, specifications) {
  const byRequest = new Map();
  for (const resource of resources) {
    if (byRequest.has(resource.request_path)) {
      throw new Error(`Duplicate served source binding: ${resource.request_path}`);
    }
    byRequest.set(resource.request_path, resource);
  }
  const expectedPaths = new Set(specifications.map(item => item.request_path));
  if (byRequest.size !== expectedPaths.size || [...byRequest.keys()].some(path => !expectedPaths.has(path))) {
    throw new Error('Served source binding set does not match the expected local sources');
  }

  let threeRecord = null;
  const loadThreeRecord = async() => {
    if (threeRecord) return threeRecord;
    threeRecord = JSON.parse(
      await readFile(new URL('../sources/viewer_design.json', import.meta.url), 'utf8'),
    ).dependencies?.extracted_files;
    if (!threeRecord || typeof threeRecord !== 'object') {
      throw new Error('Local Three.js source hash record is missing');
    }
    return threeRecord;
  };

  for (const specification of specifications) {
    const resource = byRequest.get(specification.request_path);
    if (!resource) throw new Error(`Served source binding is missing: ${specification.request_path}`);
    if (resource.binding_kind !== specification.binding_kind
        || resource.binding_path !== specification.binding_path) {
      throw new Error(`Served source binding identity changed: ${specification.request_path}`);
    }
    if (!validDigest(resource.sha256) || !Number.isSafeInteger(resource.byte_length)
        || resource.byte_length <= 0) {
      throw new Error(`Served source binding digest is malformed: ${specification.request_path}`);
    }
    if (resource.status !== 200 || resource.from_disk_cache || resource.from_service_worker) {
      throw new Error(`Served source binding was not a direct HTTP 200 response: ${specification.request_path}`);
    }
    if (resource.response_occurrence_count !== 1
        || resource.duplicate_response_urls?.length !== 0) {
      throw new Error(`Served source binding was observed more than once: ${specification.request_path}`);
    }
    let expectedDigest;
    if (specification.binding_kind === 'workspace') {
      const bytes = await readFile(new URL(`../${specification.binding_path}`, import.meta.url));
      expectedDigest = createHash('sha256').update(bytes).digest('hex');
      if (resource.byte_length !== bytes.length) {
        throw new Error(`Served source byte length does not match the worktree: ${specification.request_path}`);
      }
    } else if (specification.binding_kind === 'three_source_record') {
      expectedDigest = (await loadThreeRecord())[specification.binding_path];
    } else {
      throw new Error(`Unsupported source binding kind: ${specification.binding_kind}`);
    }
    if (!validDigest(expectedDigest) || resource.sha256 !== expectedDigest) {
      throw new Error(`Served source SHA-256 does not match the local record: ${specification.request_path}`);
    }
  }
  return {
    verified: true,
    resource_count: specifications.length,
    workspace_resource_count: specifications.filter(item => item.binding_kind === 'workspace').length,
    three_source_record_resource_count: specifications.filter(item => item.binding_kind === 'three_source_record').length,
  };
}


export async function buildVerifiedSourceBinding({
  call,
  responses,
  specifications,
  navigation,
  actualNavigationUrl,
  cache,
  externalAssetScope,
}) {
  if (cache?.network_cache_disabled !== true
      || cache?.browser_cache_cleared_before_navigation !== true) {
    throw new Error('Browser cache was not disabled and cleared before navigation');
  }
  const actual = assertNavigationBinding(navigation, actualNavigationUrl);
  const resources = await hashSourceResponses(call, responses, specifications);
  const localVerification = await verifyLocalSourceBindings(resources, specifications);
  return {
    hash_algorithm: 'SHA-256',
    hash_input: 'Exact served entity bytes returned by CDP Network.getResponseBody; base64 decoded when CDP marks the body encoded',
    cache: {...cache, nonce_parameter: navigation.parameter, nonce: navigation.nonce},
    requested_navigation_url: navigation.url,
    navigation_url: actual,
    resources,
    local_verification: localVerification,
    external_asset_scope: externalAssetScope,
  };
}
