/**
 * Overlander 4 Touch Controller - State Management Module
 */

export let currentVerifiedPos = 2503;
export let isLeaderRunning = false;
export let isFollowerRunning = false;
export let isPokeballRunning = false;
export let isPokeballConnected = false;
export let isMasterDaemonRunning = true;
export let isStudioRunning = false;
export let isClackPoseRunning = false;
export let isBeatBanditAppRunning = false;
export let isBeatBanditDancing = false;
export let isBeatBanditRunning = false;
export let isListenerAppRunning = false;
export let beatBanditTrackPage = 0;
export let selectedBeatBanditTrackId = 'F0N7aNy-9tg';
export let currentOrnithState = 'IDLE';
export function setCurrentOrnithState(s) { currentOrnithState = s; }
export let cachedBeatBanditTracks = [
    { track_id: "F0N7aNy-9tg", title: "Dracula", artist: "Tame Impala, JENNIE", duration: 209.8, tempo: 114.8, total_beats: 401 },
    { track_id: "Sv1dxHCW2-I", title: "People Pleaser", artist: "BLACK PONTIAC", duration: 260.2, tempo: 92.3, total_beats: 400 },
    { track_id: "y9Wxl9Q9lUQ", title: "Red Wine Supernova", artist: "Chappell Roan", duration: 192.7, tempo: 123.0, total_beats: 395 },
    { track_id: "OlQJ2zy5DE8", title: "Peaches", artist: "Jack Black", duration: 95.4, tempo: 184.6, total_beats: 293 },
    { track_id: "_uu_izpVSEc", title: "Soda Pop", artist: "Saja Boys", duration: 150.8, tempo: 126.0, total_beats: 316 },
    { track_id: "Y3jq_WIHP9k", title: "Dai Dai World Cup Song 2026", artist: "Shakira & Burna Boy", duration: 222.3, tempo: 117.5, total_beats: 435 }
];

export let currentAppsMode = 'controls';
export let currentPresetsPage = 1;
export let currentPresetMode = 'normal';
export let isOverwriteModeActive = false;
export let cachedPresetsList = {};
export let lastPresetsJsonStr = '';
export let currentAppsSubView = 'launcher';
export let currentBackendSubView = 'main';
export let isDrawerOpen = false;
export let registeredAppsList = [];
export let activeBreadcrumbs = ['APPS'];
export let auxCalibrationData = null;

// Beat Bandit Choreography Studio State
export let bbStudioTab = 'player'; // 'player' | 'timeline' | 'poses' | 'settings'
export let activeChoreoData = null;
export let activeProbabilitiesData = null;
export let selectedMoveBlock = null;
export let selectedMoveChannel = 'body_pose';
export let timelinePlayheadTime = 0.0;
export let timelinePixelsPerSec = 60; // 60px per second default for clear lyric legibility
export let timelineInTime = null; // Section In marker (sec)
export let timelineOutTime = null; // Section Out marker (sec)
export let timelineLoopEnabled = false; // Section Loop toggle
export let timelineIsPlaying = false; // Active playback flag
export let selectedPoseName = 'stand';
export let currentCustomPoseJoints = {
    shoulder_pan: 0.0,
    shoulder_lift: -43.17,
    elbow_flex: -25.69,
    wrist_flex: 56.61,
    wrist_roll: 0.0
};

export let currentConfig = {
    clack_threshold: 5200,
    volume_pct: 100,
    rover_max_speed_pct: 35,
    arm_speed_sec: 1.0
};

// State-diffing cache keys
export let lastRenderedButtonsKey = '';
export let lastRenderedConfigKey = '';
export let lastRenderedSliderText = '';
export let lastRenderedTeleopText = '';
export let lastRenderedPowerText = '';

// In-flight request guards
export let isPollingInProgress = false;
export let isFetchingTracks = false;
export let isFetchingPresets = false;

// State mutators for ES Module binding updates
export function setCurrentVerifiedPos(val) { currentVerifiedPos = val; }
export function setIsLeaderRunning(val) { isLeaderRunning = !!val; }
export function setIsFollowerRunning(val) { isFollowerRunning = !!val; }
export function setIsPokeballRunning(val) { isPokeballRunning = !!val; }
export function setIsPokeballConnected(val) { isPokeballConnected = !!val; }
export function setIsMasterDaemonRunning(val) { isMasterDaemonRunning = !!val; }
export function setIsStudioRunning(val) { isStudioRunning = !!val; }
export function setIsClackPoseRunning(val) { isClackPoseRunning = !!val; }
export function setIsBeatBanditAppRunning(val) { isBeatBanditAppRunning = !!val; }
export function setIsBeatBanditDancing(val) { isBeatBanditDancing = !!val; }
export function setIsBeatBanditRunning(val) { isBeatBanditRunning = !!val; }
export function setIsListenerAppRunning(val) { isListenerAppRunning = !!val; }
export function setBeatBanditTrackPage(val) { beatBanditTrackPage = val; }
export function setSelectedBeatBanditTrackId(val) { selectedBeatBanditTrackId = val; }
export function setCachedBeatBanditTracks(val) { cachedBeatBanditTracks = val; }
export function setCurrentAppsMode(val) { currentAppsMode = val; }
export function setCurrentPresetsPage(val) { currentPresetsPage = val; }
export function setCurrentPresetMode(val) { currentPresetMode = val; }
export function setIsOverwriteModeActive(val) { isOverwriteModeActive = !!val; }
export function setCachedPresetsList(val) { cachedPresetsList = val; }
export function setLastPresetsJsonStr(val) { lastPresetsJsonStr = val; }
export function setCurrentAppsSubView(val) { currentAppsSubView = val; }
export function setCurrentBackendSubView(val) { currentBackendSubView = val; }
export function setIsDrawerOpen(val) { isDrawerOpen = !!val; }
export function setRegisteredAppsList(val) { registeredAppsList = val; }
export function setActiveBreadcrumbs(val) { activeBreadcrumbs = val; }
export function setAuxCalibrationData(val) { auxCalibrationData = val; }
export function setBbStudioTab(val) { bbStudioTab = val; }
export function setActiveChoreoData(val) { activeChoreoData = val; }
export function setActiveProbabilitiesData(val) { activeProbabilitiesData = val; }
export function setSelectedMoveBlock(val) { selectedMoveBlock = val; }
export function setSelectedMoveChannel(val) { selectedMoveChannel = val; }
export function setTimelinePlayheadTime(val) { timelinePlayheadTime = val; }
export function setTimelinePixelsPerSec(val) { timelinePixelsPerSec = val; }
export function setTimelineInTime(val) { timelineInTime = val !== null ? Number(val) : null; }
export function setTimelineOutTime(val) { timelineOutTime = val !== null ? Number(val) : null; }
export function setTimelineLoopEnabled(val) { timelineLoopEnabled = !!val; }
export function setTimelineIsPlaying(val) { timelineIsPlaying = !!val; }
export function setSelectedPoseName(val) { selectedPoseName = val; }
export function setCurrentCustomPoseJoints(val) { currentCustomPoseJoints = val; }

export const configSettlingLocks = {};
export function setConfigSettlingLock(key, ms = 800) {
    configSettlingLocks[key] = Date.now() + ms;
}
export function isConfigLocked(key) {
    return (configSettlingLocks[key] || 0) > Date.now();
}

export function setCurrentConfig(val) { currentConfig = val; }
export function updateConfigKey(key, val) { currentConfig[key] = val; }
export function mergeConfigTelemetry(newConfig) {
    if (!newConfig || typeof newConfig !== 'object') return;
    for (const [k, v] of Object.entries(newConfig)) {
        if (!isConfigLocked(k)) {
            currentConfig[k] = v;
        }
    }
}

export function setLastRenderedButtonsKey(val) { lastRenderedButtonsKey = val; }
export function setLastRenderedConfigKey(val) { lastRenderedConfigKey = val; }
export function setLastRenderedSliderText(val) { lastRenderedSliderText = val; }
export function setLastRenderedTeleopText(val) { lastRenderedTeleopText = val; }
export function setLastRenderedPowerText(val) { lastRenderedPowerText = val; }

export function setIsPollingInProgress(val) { isPollingInProgress = !!val; }
export function setIsFetchingTracks(val) { isFetchingTracks = !!val; }
export function setIsFetchingPresets(val) { isFetchingPresets = !!val; }

