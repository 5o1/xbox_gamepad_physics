import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {closeCdpTarget, connectCdp, describeRuntimeException, evaluateCdp} from './cdp_client.mjs';
import {
  buildVerifiedSourceBinding,
  makeCacheBustedNavigationUrl,
  prepareUncachedNetwork,
  recordSourceResponse,
  V0_SOURCE_RESOURCES,
} from './browser_source_binding.mjs';


const requestedViewerUrl = new URL(process.argv[2] ?? 'http://127.0.0.1:9898/v0.html');
requestedViewerUrl.searchParams.set('debug', '1');
const viewerUrl = requestedViewerUrl.href;
const cdpUrl = process.argv[3] ?? 'http://127.0.0.1:9310';
const output = process.argv[4] ?? '/tmp/xbox-v0-browser';
await mkdir(output, {recursive: true});

const navigation = makeCacheBustedNavigationUrl(viewerUrl);
const viewerOrigin = new URL(viewerUrl).origin;
const runtimeFailures = [];
const resourceFailures = [];
const consoleErrors = [];
const requests = new Map();
const boundaryResponses = new Map();
let page = null;
let client = null;
let evaluate = null;
let harnessFailed = false;

try {
  const pageResponse = await fetch(new URL('/json/new?about:blank', cdpUrl), {
    method: 'PUT',
    signal: AbortSignal.timeout(20_000),
  });
  assert.ok(pageResponse.ok, `create CDP target: HTTP ${pageResponse.status}`);
  page = await pageResponse.json();
  client = await connectCdp(page.webSocketDebuggerUrl);
  const {call} = client;
  evaluate = expression => evaluateCdp(client, expression);

  client.onEvent(message => {
    if (message.method === 'Runtime.exceptionThrown') {
      runtimeFailures.push(describeRuntimeException(message.params.exceptionDetails));
    }
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      consoleErrors.push(message.params.args.map(argument => (
        argument.value ?? argument.description ?? argument.type
      )).join(' '));
    }
    if (message.method === 'Network.requestWillBeSent') {
      requests.set(message.params.requestId, message.params.request.url);
    }
    recordSourceResponse(boundaryResponses, message, viewerOrigin, V0_SOURCE_RESOURCES);
    if (message.method === 'Network.responseReceived' && message.params.response.status >= 400) {
      resourceFailures.push({url: message.params.response.url, status: message.params.response.status});
    }
    if (message.method === 'Network.loadingFailed') {
      resourceFailures.push({
        url: requests.get(message.params.requestId),
        error: message.params.errorText,
      });
    }
  });

  const cache = await prepareUncachedNetwork(call);
  await call('Runtime.enable');
  await call('Page.enable');
  const navigationResult = await call('Page.navigate', {url: navigation.url});
  assert.equal(navigationResult.errorText, undefined);
  await call('Page.bringToFront');

  const inspect = () => evaluate('window.__xboxViewerDebug?.inspect() ?? null');
  const waitFor = async (predicate, label, attempts = 180) => {
    let observed = null;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      observed = await inspect();
      if (observed && predicate(observed)) return observed;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw new Error(`${label}; last state=${JSON.stringify(observed)}`);
  };
  let state = await waitFor(candidate => candidate.ready, 'viewer did not become ready');
  const pageError = await evaluate('document.body.dataset.error || null');
  assert.equal(pageError, null, `viewer error: ${pageError}`);
  assert.equal(state.parts.length, 16);
  assert.equal(state.profileId, 'xbox_one_s_batonyrobson_appearance_matched_estimated_v0');
  assert.equal(state.activeVariantId, state.profileId);
  assert.ok(Object.values(state.verifiedBindings).every(binding => (
    binding.actual_sha256 === binding.expected_sha256
  )), 'runtime asset/profile/evidence hash mismatch');
  assert.equal(state.materialStats.mesh_count, 16);
  assert.ok(state.materialStats.unique_texture_count > 0, 'embedded textures were not instantiated');
  assert.ok(state.verifiedBindings.material, 'original material source was not verified');
  assert.ok(state.materialStats.used_texture_slots.includes('specularIntensityMap'), 'original specular intensity map was lost');
  assert.ok(!state.materialStats.used_texture_slots.includes('specularColorMap'), 'static-export specular color substitution is still active');
  assert.equal(state.renderSettings.color.view, 'Filmic');
  assert.equal(state.renderSettings.source_scene_sha256, '8f517046e08da298a35fa2d42c803b09e88ede897afe07e982769b21c9f27432');

  const actualNavigationUrl = await evaluate('location.href');
  const sourceBinding = await buildVerifiedSourceBinding({
    responses: boundaryResponses,
    specifications: V0_SOURCE_RESOURCES,
    navigation,
    actualNavigationUrl,
    cache,
    externalAssetScope: 'The viewer verifies inventory, profile, evidence and GLB hashes.',
  });

  const baseline = await call('Page.captureScreenshot', {format: 'png'});
  await writeFile(join(output, 'estimated_v0_baseline.png'), Buffer.from(baseline.data, 'base64'));
  const profile = JSON.parse(await readFile(
    new URL('../assets/appearance_matched_estimated_v0/viewer_profile.json', import.meta.url),
    'utf8',
  ));

  const inject = ({axes = [0, 0, 0, 0], buttons = {}} = {}) => evaluate(`(() => {
    window.testPad = {
      connected: true,
      mapping: 'standard',
      index: 0,
      id: 'SYNTHETIC STANDARD PAD',
      timestamp: performance.now(),
      axes: ${JSON.stringify(axes)},
      buttons: Array.from({length: 17}, (_, index) => {
        const value = (${JSON.stringify(buttons)})[index] ?? 0;
        return {value, pressed: value > .5, touched: value > 0};
      }),
    };
    Object.defineProperty(navigator, 'getGamepads', {
      configurable: true,
      value: () => [window.testPad],
    });
    const mode = document.getElementById('mode');
    mode.value = 'device';
    mode.dispatchEvent(new Event('change'));
  })()`);

  // Exercise each standard channel through the actual browser Gamepad mapping.
  const channelChecks = [];
  for (let channel = 0; channel < 21; channel += 1) {
    const signal = channel < 4 ? 0.35 : 0.65;
    const axes = [0, 0, 0, 0];
    const buttons = {};
    if (channel < 4) axes[channel] = signal;
    else buttons[channel - 4] = signal;
    await inject({axes, buttons});
    const observed = await waitFor(
      candidate => Math.abs(candidate.values[channel] - signal) < 1e-6,
      `standard channel ${channel} did not reach the requested value`,
    );
    const joint = profile.joints.find(item => (
      item.driver.kind === 'linear_channel'
        ? item.driver.channel === channel
        : [item.driver.negative_channel, item.driver.positive_channel].includes(channel)
    ));
    assert.ok(joint, `standard channel ${channel} has no visible joint`);
    const part = observed.parts.find(item => item.name === joint.node);
    const displacement = Math.hypot(...part.matrix.map((value, index) => value - part.restMatrix[index]));
    assert.ok(displacement > 1e-8, `standard channel ${channel} did not move its visible node`);
    channelChecks.push({channel, name: profile.channels[channel].name, node: joint.node});
  }

  const debugCall = (method, args = []) => evaluate(
    `window.__xboxViewerDebug.${method}(...${JSON.stringify(args)})`,
  );
  const neutral = () => new Array(21).fill(0);
  const mouseChecks = [];

  async function configureMouse(channel, drag2d) {
    await evaluate(`(() => {
      window.testPad = null;
      const mode = document.getElementById('mode');
      mode.value = 'mouse';
      mode.dispatchEvent(new Event('change'));
      document.getElementById('channel').value = ${JSON.stringify(String(channel))};
      document.getElementById('drag2d').checked = ${drag2d ? 'true' : 'false'};
    })()`);
    await waitFor(candidate => candidate.mode === 'mouse', 'mouse mode did not stabilize');
  }

  async function exerciseMouse({label, node, channel, target, activeChannels, drag2d = false, camera}) {
    await configureMouse(channel, drag2d);
    if (camera) await debugCall('setCamera', [camera]);
    const pick = await debugCall('findVisiblePick', [node]);
    const targetScreen = await debugCall('projectInteractionPoint', [node, pick.local_point, target]);
    await call('Input.dispatchMouseEvent', {
      type: 'mousePressed', x: pick.screen[0], y: pick.screen[1],
      button: 'left', buttons: 1, clickCount: 1,
    });
    await call('Input.dispatchMouseEvent', {
      type: 'mouseMoved', x: targetScreen[0], y: targetScreen[1],
      button: 'left', buttons: 1,
    });
    const moved = await waitFor(candidate => (
      candidate.dragging
      && candidate.values.every((value, index) => Math.abs(value - target[index]) < 0.12)
    ), `${label}: mouse drag did not produce the expected channels`);
    assert.equal(moved.selected, node, `${label}: pointer selected a different node`);
    await call('Input.dispatchMouseEvent', {
      type: 'mouseReleased', x: targetScreen[0], y: targetScreen[1],
      button: 'left', buttons: 0, clickCount: 1,
    });
    await waitFor(candidate => (
      !candidate.dragging && activeChannels.every(index => candidate.values[index] === 0)
    ), `${label}: release did not reset its channels`);
    mouseChecks.push({label, node, active_channels: activeChannels, release_reset: true});
  }

  const aTarget = neutral();
  aTarget[4] = 1;
  await exerciseMouse({
    label: 'a', node: '00_A_Button_VISUAL_UNCALIBRATED', channel: 4,
    target: aTarget, activeChannels: [4],
  });
  const triggerTarget = neutral();
  triggerTarget[10] = 0.8;
  await exerciseMouse({
    label: 'left_trigger', node: '11_Trigger_L_VISUAL_UNCALIBRATED', channel: 10,
    target: triggerTarget, activeChannels: [10],
    camera: {azimuth_deg: 90, elevation_deg: 35, distance_span: 2.4},
  });
  await debugCall('resetCamera');
  const stickTarget = neutral();
  stickTarget[0] = 0.45;
  stickTarget[1] = -0.35;
  await exerciseMouse({
    label: 'left_stick', node: '09_Stick_L_VISUAL_UNCALIBRATED', channel: 0,
    target: stickTarget, activeChannels: [0, 1], drag2d: true,
  });
  const dpadTarget = neutral();
  dpadTarget[19] = 1;
  await exerciseMouse({
    label: 'dpad_right', node: '06_D-Pad_VISUAL_UNCALIBRATED', channel: 19,
    target: dpadTarget, activeChannels: [19],
  });

  // A concurrent device state verifies the standard encoding is not serialized
  // into one-control-at-a-time behavior.
  const concurrentAxes = [0.25, -0.35, -0.4, 0.2];
  const concurrentButtons = {0: 1, 4: 1, 6: 0.5, 7: 0.8, 12: 1, 15: 1};
  await inject({axes: concurrentAxes, buttons: concurrentButtons});
  state = await waitFor(candidate => candidate.values.filter(value => Math.abs(value) > 1e-6).length >= 9,
    'concurrent Gamepad state did not propagate');
  const expected = [...concurrentAxes, ...Array.from({length: 17}, (_, index) => concurrentButtons[index] ?? 0)];
  assert.ok(state.values.every((value, index) => Math.abs(value - expected[index]) < 1e-6));
  const concurrentShot = await call('Page.captureScreenshot', {format: 'png'});
  await writeFile(
    join(output, 'estimated_v0_concurrent_input.png'),
    Buffer.from(concurrentShot.data, 'base64'),
  );

  assert.deepEqual(runtimeFailures, []);
  assert.deepEqual(resourceFailures, []);
  assert.deepEqual(consoleErrors, []);
  const result = {
    schema_version: 2,
    passed: true,
    profile_id: state.profileId,
    variant_id: state.activeVariantId,
    runtime: {
      browser: await call('Browser.getVersion'),
      viewer_url: viewerUrl,
      navigation_url: actualNavigationUrl,
      cdp_url: cdpUrl,
    },
    source_binding: sourceBinding,
    external_asset_bindings: state.verifiedBindings,
    material_stats: state.materialStats,
    render_settings: state.renderSettings,
    standard_gamepad_21_channels: channelChecks,
    mouse_controls: mouseChecks,
    concurrent_gamepad_encoding: true,
    real_controller_tested: false,
    physical_acceptance: false,
  };
  await writeFile(join(output, 'browser_v0_harness.json'), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({...result, output}));
} catch (error) {
  harnessFailed = true;
  throw error;
} finally {
  if (evaluate) await evaluate('delete navigator.getGamepads; delete window.testPad').catch(() => {});
  client?.close();
  if (page?.id) {
    try {
      await closeCdpTarget(cdpUrl, page.id);
    } catch (error) {
      if (!harnessFailed) throw error;
      console.error(`CDP target cleanup also failed: ${error.message}`);
    }
  }
}
