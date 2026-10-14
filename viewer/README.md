# Viewer and signal overlay

After installation, run `xbox-gamepad-physics viewer --resources ./gamepad_resources --offline --blender /path/to/blender` or `xbox-gamepad-physics overlay`. No CDN or npm downloads are required. Supply Blender 4.5 yourself; without it, the static UI remains available and Cycles requests report an explicit error. The overlay includes a synthetic demo trace. Use `--trace-dir` for your own data to display continuous upstream signals.

In a checkout, `npm run viewer` and `npm run gamepad-overlay` remain available. The Python server, worker and example implementations live in the package's `web/` and `examples/` directories. This directory contains UI development sources and historical standalone diagnostic pages. The distributed UI is a static copy of these sources. Three.js includes only the required module closure; synchronize and verify the copies before packaging. Do not include all of `node_modules` or historical online reference pages in the wheel.

Resources use approved inputs and the same kinematics DAG, without writing a separate `build/generated` tree. Real Blender/SAPIEN rendering and interaction are validated in B4.

The reference PNG is distributed only in the input zip (CC BY 4.0), not in the wheel. The viewer retains the `/accepted-reference/boiler_room_vertical_fov35_strength_1p0.png` route and reads from `inputs/assets/xbox_one_s/render/` under the resource root. If the image is absent, it displays "Missing input resources" and the page remains usable.
