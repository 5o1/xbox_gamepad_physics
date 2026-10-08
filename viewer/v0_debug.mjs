import * as T from 'three';


const TEXTURE_SLOTS = [
  'map', 'lightMap', 'aoMap', 'emissiveMap', 'bumpMap', 'normalMap',
  'displacementMap', 'roughnessMap', 'metalnessMap', 'alphaMap', 'envMap',
  'anisotropyMap', 'clearcoatMap', 'clearcoatRoughnessMap',
  'clearcoatNormalMap', 'iridescenceMap', 'iridescenceThicknessMap',
  'sheenColorMap', 'sheenRoughnessMap', 'transmissionMap', 'thicknessMap',
  'specularIntensityMap', 'specularColorMap',
];


export function installViewerDebug(api) {
  const {scene, camera, renderer, orbit, parts, restMatrices} = api;
  const ray = new T.Raycaster();

  function hitRecordsAt(clientX, clientY) {
    const rect = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new T.Vector2(
      (clientX - rect.left) / rect.width * 2 - 1,
      1 - (clientY - rect.top) / rect.height * 2,
    ), camera);
    return ray.intersectObjects([...parts.values()], true).map(hit => ({
      node: hit.object.userData.profileNode ?? null,
      object: hit.object.name || null,
      distance: hit.distance,
      point_world: hit.point.toArray(),
    }));
  }

  function screenBoundsForNode(nodeName) {
    const rect = renderer.domElement.getBoundingClientRect();
    const box = new T.Box3().setFromObject(parts.get(nodeName));
    const corners = [];
    for (const x of [box.min.x, box.max.x]) {
      for (const y of [box.min.y, box.max.y]) {
        for (const z of [box.min.z, box.max.z]) {
          const point = new T.Vector3(x, y, z).project(camera);
          corners.push([
            rect.left + (point.x + 1) * rect.width / 2,
            rect.top + (1 - point.y) * rect.height / 2,
          ]);
        }
      }
    }
    return {
      left: Math.max(rect.left, Math.min(...corners.map(point => point[0]))),
      right: Math.min(rect.right, Math.max(...corners.map(point => point[0]))),
      top: Math.max(rect.top, Math.min(...corners.map(point => point[1]))),
      bottom: Math.min(rect.bottom, Math.max(...corners.map(point => point[1]))),
    };
  }

  function materialStats(model) {
    const names = new Set();
    const textures = new Set();
    const usedSlots = new Set();
    let meshCount = 0;
    let materialSlotCount = 0;
    model?.traverse(object => {
      if (!object.isMesh) return;
      meshCount += 1;
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        if (!material) continue;
        materialSlotCount += 1;
        names.add(material.name);
        for (const slot of TEXTURE_SLOTS) {
          const texture = material[slot];
          if (texture?.isTexture) {
            textures.add(texture.uuid);
            usedSlots.add(slot);
          }
        }
      }
    });
    return {
      mesh_count: meshCount,
      material_slot_count: materialSlotCount,
      unique_material_names: [...names].sort(),
      used_texture_slots: [...usedSlots].sort(),
      unique_texture_count: textures.size,
    };
  }

  function inspect() {
    const state = api.getState();
    const rect = renderer.domElement.getBoundingClientRect();
    return {
      ready: state.ready,
      activeVariantId: state.activeVariantId,
      profileId: state.profile?.profile_id ?? null,
      mode: state.session.mode,
      frame: {
        valid: state.session.frame.valid,
        reason: state.session.frame.reason ?? null,
        source: state.session.frame.source ?? null,
      },
      deviceKey: state.deviceKey,
      values: Array.from(state.session.frame.values),
      represented: Array.from(state.lastEvaluation?.represented ?? new Float32Array(21)),
      projections: state.lastEvaluation?.projections ?? [],
      pair: state.lastEvaluation?.representedEvents?.pair_bind_connect ?? 0,
      selected: state.selected,
      dragging: state.drag !== null,
      verifiedBindings: state.verifiedBindings,
      materialStats: materialStats(state.model),
      cycles: state.cycles,
      parts: [...parts].map(([name, node]) => {
        const box = new T.Box3().setFromObject(node);
        const worldCenter = box.getCenter(new T.Vector3());
        const point = worldCenter.clone().project(camera);
        return {
          name,
          screen: [
            rect.left + (point.x + 1) * rect.width / 2,
            rect.top + (1 - point.y) * rect.height / 2,
          ],
          matrix: node.matrix.toArray(),
          restMatrix: restMatrices.get(name).toArray(),
          worldCenter: worldCenter.toArray(),
        };
      }),
    };
  }

  function findVisiblePick(nodeName, gridSize = 25) {
    const state = api.getState();
    if (!state.ready || !parts.has(nodeName)) throw Error(`unknown or unavailable node: ${nodeName}`);
    const bounds = screenBoundsForNode(nodeName);
    if (!(bounds.right > bounds.left && bounds.bottom > bounds.top)) {
      throw Error(`node has no on-canvas screen bounds: ${nodeName}`);
    }
    let chosen = null;
    for (let row = 0; row < gridSize; row += 1) {
      for (let column = 0; column < gridSize; column += 1) {
        const screen = [
          bounds.left + (column + 0.5) * (bounds.right - bounds.left) / gridSize,
          bounds.top + (row + 0.5) * (bounds.bottom - bounds.top) / gridSize,
        ];
        const hit = hitRecordsAt(...screen)[0];
        if (hit?.node !== nodeName) continue;
        const edge = Math.min(
          screen[0] - bounds.left,
          bounds.right - screen[0],
          screen[1] - bounds.top,
          bounds.bottom - screen[1],
        );
        if (!chosen || edge > chosen.edge) chosen = {screen, hit, edge};
      }
    }
    if (!chosen) throw Error(`node has no visible sample: ${nodeName}`);
    const local = parts.get(nodeName).worldToLocal(new T.Vector3(...chosen.hit.point_world));
    return {node: nodeName, screen: chosen.screen, local_point: local.toArray()};
  }

  function projectInteractionPoint(nodeName, localPoint, state) {
    if (!parts.has(nodeName)) throw Error(`unknown node: ${nodeName}`);
    return api.projectPickedPoint(
      nodeName,
      new T.Vector3(...localPoint),
      Float32Array.from(state),
    );
  }

  function setCamera({azimuth_deg, elevation_deg, distance_span = 2.4}) {
    const {model} = api.getState();
    if (!model) throw Error('viewer is not ready');
    const box = new T.Box3().setFromObject(model);
    const center = box.getCenter(new T.Vector3());
    const size = box.getSize(new T.Vector3());
    const span = Math.max(size.x, size.y, size.z);
    const azimuth = T.MathUtils.degToRad(azimuth_deg);
    const elevation = T.MathUtils.degToRad(elevation_deg);
    const distance = span * distance_span;
    const horizontal = distance * Math.cos(elevation);
    orbit.target.copy(center);
    camera.position.set(
      center.x + horizontal * Math.cos(azimuth),
      center.y + horizontal * Math.sin(azimuth),
      center.z + distance * Math.sin(elevation),
    );
    camera.updateProjectionMatrix();
    orbit.update();
    camera.updateMatrixWorld(true);
    scene.updateMatrixWorld(true);
    api.requestRender();
  }

  function resetCamera() {
    api.resetCamera();
    camera.updateMatrixWorld(true);
    scene.updateMatrixWorld(true);
  }

  window.__xboxViewerDebug = {
    inspect,
    findVisiblePick,
    projectInteractionPoint,
    setCamera,
    resetCamera,
  };
}
