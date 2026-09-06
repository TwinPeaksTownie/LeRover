/**
 * Overlander 4 Touch Controller - API & Network Module
 */

/**
 * Safe fetch helper with AbortController timeout and no-store caching
 */
export function safeFetch(url, options = {}, timeoutMs = 1200) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const fetchOptions = Object.assign({}, options, {
        signal: controller.signal,
        cache: 'no-store'
    });
    return fetch(url, fetchOptions)
        .finally(() => clearTimeout(timeoutId));
}

// Telemetry & Hardware Status
export function fetchStatus(timestamp = Date.now()) {
    return safeFetch('/api/status?t=' + timestamp, {}, 1000);
}

// Gantry & Pedestal Motion
export function sendSliderMove(targetVal) {
    return safeFetch('/api/slider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 8, target: parseInt(targetVal, 10), value: parseInt(targetVal, 10) })
    }, 2500);
}

export function sendPedestalStep(direction) {
    return safeFetch('/api/pedestal_step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction })
    }, 2500);
}

export function sendSyncPosition(servoId, pos) {
    return safeFetch('/api/sync_position', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: parseInt(servoId, 10), pos: parseInt(pos, 10) })
    }, 2500);
}

// Remote Service Toggles
export function sendMacLeaderToggle(action) {
    return safeFetch('/api/mac_leader_toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    }, 2500);
}

export function sendPi500FollowerToggle(action) {
    return safeFetch('/api/pi500_follower_toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    }, 2500);
}

export function sendPokeballTeleopToggle(action) {
    return safeFetch('/api/pokeball_teleop_toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    }, 2500);
}

export function sendServoStudioToggle(action) {
    return safeFetch('/api/servo_studio_toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    }, 2500);
}

export function sendClackPoseToggle(action) {
    return safeFetch('/api/clack_pose_toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    }, 2500);
}

export function sendAppStart(appName, params = {}) {
    return safeFetch('/api/apps/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: appName, ...params })
    }, 3500);
}

export function sendAppStop(appName = null) {
    return safeFetch('/api/apps/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: appName })
    }, 3000);
}

// Beat Bandit App
export function sendBeatBanditStart(urlOrId, options = {}) {
    return safeFetch('/api/apps/beat_bandit/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            url: urlOrId,
            track_id: urlOrId,
            start_sec: options.start_sec !== undefined ? options.start_sec : 0.0,
            end_sec: options.end_sec !== undefined ? options.end_sec : null,
            loop: !!options.loop
        })
    }, 4000);
}

export function sendBeatBanditStop() {
    safeFetch('/api/play_sound', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'stop' })
    }, 1000).catch(() => {});

    return safeFetch('/api/apps/beat_bandit/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    }, 2000);
}

export function fetchBeatBanditTracksApi() {
    return safeFetch('/api/apps/beat_bandit/tracks', {}, 1500);
}

export function fetchBeatBanditChoreo(trackId) {
    const q = trackId ? `?track_id=${encodeURIComponent(trackId)}` : '';
    return safeFetch(`/api/apps/beat_bandit/choreo${q}`, {}, 2500);
}

export function saveBeatBanditChoreo(trackId, choreo) {
    return safeFetch('/api/apps/beat_bandit/save_choreo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track_id: trackId, choreography: choreo })
    }, 3500);
}

export function autoGenerateBeatBanditChoreo(trackId, style = 'balanced') {
    return safeFetch('/api/apps/beat_bandit/auto_generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track_id: trackId, style: style })
    }, 4000);
}

export function fetchBeatBanditProbabilities() {
    return safeFetch('/api/apps/beat_bandit/probabilities', {}, 2000);
}

export function saveBeatBanditProbabilities(probabilities, trackId = null) {
    return safeFetch('/api/apps/beat_bandit/probabilities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ probabilities, track_id: trackId })
    }, 4500);
}

export function previewBeatBanditPose(pose) {
    return safeFetch('/api/apps/beat_bandit/preview_pose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pose })
    }, 2500);
}

export function captureBeatBanditPose(name) {
    return safeFetch('/api/apps/beat_bandit/capture_pose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    }, 2500);
}

export function previewBeatBanditMovement(channel, target) {
    return safeFetch('/api/apps/beat_bandit/preview_movement', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, target })
    }, 2500);
}

export function previewBeatBanditBlock(trackId, channel, block) {
    return safeFetch('/api/apps/beat_bandit/preview_block', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track_id: trackId, channel, block })
    }, 3000);
}

export function sendArmMoveNorm(target, duration = 1.5, steps = 40) {
    return safeFetch('/api/arm/move_norm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, duration, steps })
    }, 3000);
}

// Arm & Presets Control
export function sendArmTorque(enable) {
    return safeFetch('/api/arm/torque', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable })
    }, 2000);
}

export function sendArmCapturePose() {
    return safeFetch('/api/arm/capture_pose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    }, 2000);
}

export function sendArmCommitPreset(mode) {
    return safeFetch('/api/arm/commit_preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
    }, 2500);
}

export function sendArmResumePose(duration, mode) {
    return safeFetch('/api/arm/resume_last_pose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration, mode })
    }, 2500);
}

export function sendArmOverwritePreset(presetName, mode) {
    return safeFetch('/api/arm/overwrite_preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: presetName, mode })
    }, 2500);
}

export function sendArmAttackSequence() {
    return safeFetch('/api/arm/attack_sequence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    }, 2500);
}

export function sendArmExecuteSequence(sequenceName, mode) {
    return safeFetch('/api/arm/execute_sequence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sequence: sequenceName, mode })
    }, 2500);
}

export function sendArmMoveToPreset(presetName, duration, mode) {
    return safeFetch('/api/arm/move_to_preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: presetName, duration, mode })
    }, 3000);
}

export function fetchArmPresets(mode, timestamp = Date.now()) {
    return safeFetch('/api/arm/presets?mode=' + mode + '&t=' + timestamp, {}, 1500);
}

// Power & Backend Tools
export function sendConnectHotspot() {
    return safeFetch('/api/connect_hotspot', { method: 'POST' }, 4000);
}

export function sendPi500PowerOn() {
    return sendConnectHotspot();
}

export function sendMasterDaemonRestart(action) {
    return safeFetch('/api/pi500_master_daemon_restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    }, 10000);
}

export function sendEmergencyKillAll() {
    return safeFetch('/api/kill_all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'kill_all' })
    }, 2500);
}

export function sendWifiRestore() {
    return safeFetch('/api/wifi_restore', { method: 'POST' }, 3000);
}

export function sendWifiDisable() {
    return safeFetch('/api/wifi_disable', { method: 'POST' }, 3000);
}

export function sendSetConfig(configObj) {
    return safeFetch('/api/set_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configObj)
    }, 2000);
}

export function sendPlaySound(payload) {
    if (!payload || typeof payload !== 'object') {
        throw new TypeError("sendPlaySound: payload must be a non-null object");
    }
    if (payload.event === undefined || typeof payload.event !== 'string' || payload.event.length === 0) {
        throw new TypeError("sendPlaySound: 'event' must be a non-empty string");
    }
    if (payload.stop_previous === undefined || typeof payload.stop_previous !== 'boolean') {
        throw new TypeError("sendPlaySound: 'stop_previous' must be a boolean");
    }
    if (payload.delay_sec === undefined || typeof payload.delay_sec !== 'number') {
        throw new TypeError("sendPlaySound: 'delay_sec' must be a number");
    }
    if (payload.wav_path === undefined || typeof payload.wav_path !== 'string') {
        throw new TypeError("sendPlaySound: 'wav_path' must be a string");
    }
    return safeFetch('/api/play_sound', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            event: payload.event,
            stop_previous: payload.stop_previous,
            delay_sec: payload.delay_sec,
            wav_path: payload.wav_path
        })
    }, 1000);
}

// Voice Listener Track Selection, Analysis & Navigation
export function sendListenerSelect(index) {
    if (index === undefined || index === null) {
        throw new Error("sendListenerSelect requires valid integer index");
    }
    return safeFetch('/api/apps/listener/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: parseInt(index, 10) })
    }, 4000);
}

export function sendListenerAnalyze(index) {
    if (index === undefined || index === null) {
        throw new Error("sendListenerAnalyze requires valid integer index");
    }
    return safeFetch('/api/apps/listener/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: parseInt(index, 10) })
    }, 4000);
}

export function sendListenerNavigate(delta) {
    return safeFetch('/api/apps/listener/navigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delta: parseInt(delta, 10) })
    }, 2500);
}
