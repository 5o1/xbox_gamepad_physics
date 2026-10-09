# Viewer

`index.html` is the single interactive Xbox One S inspection entry point.
`app.mjs` loads the registered 16-part visual asset, the generated kinematic
profile and its evidence. `kinematics.mjs` validates and evaluates that profile;
`drag2d.mjs` handles paired stick dragging; `cycles_view.mjs` bridges the page to
the persistent Blender/Cycles worker. `debug.mjs` is loaded only with
`?debug=1` for browser acceptance tests.

Supporting tools remain separate:

- `gamepad_overlay/` renders canonical controller signals for recorded demos.
- `material_check.html` and `material_check.mjs` inspect source materials.
- `sketchfab_reference.html` supports upstream-reference captures.

Run the main viewer from the repository root with `npm run viewer`, then open
`http://127.0.0.1:8766/`. Generated profiles belong under
`build/generated/kinematics/`; do not add generated JSON or experiment output to
this directory.
