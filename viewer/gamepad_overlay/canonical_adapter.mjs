export const LAYOUT_ID = "sdl3-gamepad-core-v1";

export const CHANNEL_NAMES = Object.freeze([
    "left_x", "left_y", "right_x", "right_y", "left_trigger", "right_trigger",
    "south", "east", "west", "north", "back", "guide", "start",
    "left_stick", "right_stick", "left_shoulder", "right_shoulder",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right", "misc1",
    "right_paddle1", "left_paddle1", "right_paddle2", "left_paddle2",
    "touchpad", "misc2", "misc3", "misc4", "misc5", "misc6",
]);

const INDEX = Object.freeze(Object.fromEntries(
    CHANNEL_NAMES.map((name, index) => [name, index]),
));

function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
}

export function validateCanonicalFrame(frame) {
    if (frame?.layout_id !== LAYOUT_ID) {
        throw new Error(`Expected layout_id ${LAYOUT_ID}`);
    }
    if (!Array.isArray(frame.values) || frame.values.length !== CHANNEL_NAMES.length) {
        throw new Error(`Expected ${CHANNEL_NAMES.length} gamepad values`);
    }
    for (const name of ["available_mask", "task_mask"]) {
        const mask = frame[name];
        if (!Array.isArray(mask) || mask.length !== CHANNEL_NAMES.length) {
            throw new Error(`Expected ${CHANNEL_NAMES.length} ${name} entries`);
        }
        if (mask.some(value => typeof value !== "boolean")) {
            throw new Error(`${name} entries must be boolean`);
        }
    }
    frame.values.forEach((value, index) => {
        if (!Number.isFinite(value)) {
            throw new Error(`Channel ${CHANNEL_NAMES[index]} must be finite`);
        }
        if (!frame.available_mask[index] && value !== 0) {
            throw new Error(`Unavailable channel ${CHANNEL_NAMES[index]} must be zero`);
        }
        if (frame.task_mask[index] && !frame.available_mask[index]) {
            throw new Error(`Task channel ${CHANNEL_NAMES[index]} is unavailable`);
        }
    });
    if (!Number.isInteger(frame.device_id) || frame.device_id < 0) {
        throw new Error("device_id must be a non-negative integer");
    }
    return frame;
}

export function canonicalFrameToOverlayState(frame) {
    validateCanonicalFrame(frame);
    const value = name => frame.values[INDEX[name]];
    return {
        LX: clamp(value("left_x"), -1, 1),
        LY: clamp(value("left_y"), -1, 1),
        RX: clamp(value("right_x"), -1, 1),
        RY: clamp(value("right_y"), -1, 1),
        LT: clamp(value("left_trigger"), 0, 1),
        RT: clamp(value("right_trigger"), 0, 1),
        A: clamp(value("south"), 0, 1),
        B: clamp(value("east"), 0, 1),
        X: clamp(value("west"), 0, 1),
        Y: clamp(value("north"), 0, 1),
        SELECT: clamp(value("back"), 0, 1),
        GUIDE: clamp(value("guide"), 0, 1),
        START: clamp(value("start"), 0, 1),
        LS: clamp(value("left_stick"), 0, 1),
        RS: clamp(value("right_stick"), 0, 1),
        LB: clamp(value("left_shoulder"), 0, 1),
        RB: clamp(value("right_shoulder"), 0, 1),
        DX: clamp(value("dpad_right") - value("dpad_left"), -1, 1),
        DY: clamp(value("dpad_down") - value("dpad_up"), -1, 1),
    };
}

function afterPaint() {
    return new Promise(resolve => requestAnimationFrame(
        () => requestAnimationFrame(resolve),
    ));
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function updateHud(frame, overlayState) {
    const telemetry = frame.telemetry ?? {};
    const radius = Math.hypot(overlayState.LX, overlayState.LY);
    setText("phase", telemetry.phase ?? "sample");
    setText("frameIndex", String(telemetry.frame_index ?? "–"));
    setText("theta", Number.isFinite(telemetry.theta_deg)
        ? `${telemetry.theta_deg.toFixed(1)}°`
        : "–");
    setText("qx", Number.isFinite(telemetry.left_stick_x_rad)
        ? telemetry.left_stick_x_rad.toFixed(4)
        : "–");
    setText("qy", Number.isFinite(telemetry.left_stick_y_rad)
        ? telemetry.left_stick_y_rad.toFixed(4)
        : "–");
    setText("leftX", overlayState.LX.toFixed(4));
    setText("leftY", overlayState.LY.toFixed(4));
    setText("radius", radius.toFixed(4));

    const dot = document.getElementById("signalDot");
    if (dot) {
        dot.style.transform = `translate(${overlayState.LX * 60}px, ${overlayState.LY * 60}px)`;
    }
    const leftStickNodes = document.querySelectorAll(
        '#overlayRoot [data-side="left"][data-role="analog-stick"], '
        + '#overlayRoot [data-side="left"][data-role="analog-stick-ring"]',
    );
    const active = radius > 1e-4;
    leftStickNodes.forEach(node => node.classList.toggle("signal-active", active));
}

export function installCanonicalSource() {
    const upstream = window.OverlayInput;
    if (!upstream?.createGamepadSource) {
        throw new Error("Upstream gamepad-overlay input module is unavailable");
    }

    let sink = null;
    let ready = false;
    const originalCreateSource = upstream.createGamepadSource;
    window.OverlayInput = Object.freeze({
        ...upstream,
        createGamepadSource(config) {
            const requested = new URLSearchParams(location.search).get("source");
            if (requested != null && requested !== "canonical") {
                return originalCreateSource(config);
            }
            return {
                start() { sink = config.onState; },
                stop() { sink = null; },
            };
        },
    });

    return Object.freeze({
        get ready() { return ready && sink != null; },
        markReady() { ready = true; },
        async applyFrame(frame) {
            if (!ready || sink == null) throw new Error("Overlay adapter is not ready");
            const overlayState = canonicalFrameToOverlayState(frame);
            sink(overlayState);
            await afterPaint();
            updateHud(frame, overlayState);
            return overlayState;
        },
    });
}
