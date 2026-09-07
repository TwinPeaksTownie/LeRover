/**
 * Overlander 4 Touch Controller - UI Rendering & DOM Management Module
 */

import {
    currentVerifiedPos,
    isLeaderRunning,
    isFollowerRunning,
    isPokeballRunning,
    isPokeballConnected,
    isMasterDaemonRunning,
    isStudioRunning,
    isClackPoseRunning,
    isBeatBanditAppRunning,
    isBeatBanditDancing,
    isBeatBanditRunning,
    isListenerAppRunning,
    beatBanditTrackPage,
    selectedBeatBanditTrackId,
    cachedBeatBanditTracks,
    currentAppsMode,
    currentOrnithState,
    setCurrentOrnithState,
    currentPresetsPage,
    currentPresetMode,
    isOverwriteModeActive,
    cachedPresetsList,
    currentAppsSubView,
    currentBackendSubView,
    bbStudioTab,
    activeChoreoData,
    activeProbabilitiesData,
    selectedMoveBlock,
    selectedMoveChannel,
    timelinePlayheadTime,
    timelinePixelsPerSec,
    timelineInTime,
    timelineOutTime,
    timelineLoopEnabled,
    timelineIsPlaying,
    selectedPoseName,
    currentCustomPoseJoints,
    currentConfig,
    mergeConfigTelemetry,
    lastRenderedButtonsKey,
    lastRenderedConfigKey,
    lastRenderedSliderText,
    lastRenderedTeleopText,
    lastRenderedPowerText,
    setCurrentVerifiedPos,
    setIsLeaderRunning,
    setIsFollowerRunning,
    setIsPokeballRunning,
    setIsPokeballConnected,
    setIsMasterDaemonRunning,
    setIsStudioRunning,
    setIsClackPoseRunning,
    setIsBeatBanditAppRunning,
    setIsBeatBanditDancing,
    setIsBeatBanditRunning,
    setIsListenerAppRunning,
    setBeatBanditTrackPage,
    setSelectedBeatBanditTrackId,
    setCurrentAppsMode,
    setCurrentPresetsPage,
    setCurrentPresetMode,
    setIsOverwriteModeActive,
    setCurrentAppsSubView,
    setCurrentBackendSubView,
    setBbStudioTab,
    setActiveChoreoData,
    setSelectedMoveBlock,
    setSelectedMoveChannel,
    setTimelinePlayheadTime,
    setTimelinePixelsPerSec,
    setTimelineInTime,
    setTimelineOutTime,
    setTimelineLoopEnabled,
    setTimelineIsPlaying,
    setSelectedPoseName,
    setCurrentCustomPoseJoints,
    setCurrentConfig,
    isDrawerOpen,
    setIsDrawerOpen,
    registeredAppsList,
    setRegisteredAppsList,
    activeBreadcrumbs,
    setActiveBreadcrumbs,
    auxCalibrationData,
    setAuxCalibrationData,
    currentCarouselIndex,
    setCurrentCarouselIndex,
    setLastRenderedButtonsKey,
    setLastRenderedConfigKey,
    setLastRenderedSliderText,
    setLastRenderedTeleopText,
    setLastRenderedPowerText
} from './state.js';

export function setHeaderAlert(msg) {
    const el = document.getElementById('sliderValDisplay');
    if (el) {
        el.innerHTML = '<span style="color:#ff3344; font-weight:900;">⚡ ' + (msg || '12V POWER OFF') + '</span>';
    }
}

export function renderButtonStates() {
    const stateKey = `${isFollowerRunning}_${isLeaderRunning}_${isStudioRunning}_${isClackPoseRunning}_${isBeatBanditAppRunning}_${isBeatBanditDancing}_${isListenerAppRunning}_${isMasterDaemonRunning}_${isPokeballRunning}_${isPokeballConnected}`;
    if (lastRenderedButtonsKey === stateKey) {
        return; // Zero DOM mutations when state is unchanged!
    }
    setLastRenderedButtonsKey(stateKey);

    // Follower button
    const followerBtn = document.getElementById('followerBtn');
    const followerBtnText = document.getElementById('followerBtnText');
    if (followerBtn) {
        followerBtn.style.borderColor = isFollowerRunning ? '#00ff66' : '#444444';
        followerBtn.style.color = isFollowerRunning ? '#00ff66' : '#ffffff';
        if (followerBtnText) followerBtnText.innerText = isFollowerRunning ? 'STOP TELEOP' : 'START TELEOP';
    }

    // Leader button
    const leaderBtn = document.getElementById('leaderBtn');
    const leaderBtnText = document.getElementById('leaderBtnText');
    if (leaderBtn) {
        leaderBtn.style.borderColor = isLeaderRunning ? '#00e5ff' : '#444444';
        leaderBtn.style.color = isLeaderRunning ? '#00e5ff' : '#ffffff';
        if (leaderBtnText) leaderBtnText.innerText = isLeaderRunning ? 'STOP LEADER' : 'START LEADER';
    }

    // Studio button & badge
    const studioBtn = document.getElementById('studioBtn');
    const studioBtnText = document.getElementById('studioBtnText');
    const studioBtnSub = document.getElementById('studioBtnSub');
    const studioBadge = document.getElementById('studioBadge');
    if (studioBtn) {
        studioBtn.style.borderColor = isStudioRunning ? '#00ff66' : '#ffaa00';
        studioBtn.style.color = isStudioRunning ? '#00ff66' : '#ffffff';
        studioBtn.style.background = isStudioRunning ? 'rgba(0, 255, 102, 0.15)' : '#181818';
        if (studioBtnText) studioBtnText.innerText = isStudioRunning ? 'STOP SERVO STUDIO' : 'START SERVO STUDIO';
        if (studioBtnSub) {
            studioBtnSub.innerText = isStudioRunning ? '(STUDIO RUNNING - PORT 8086)' : '(CALIBRATION ON PORT 8086)';
            studioBtnSub.style.color = isStudioRunning ? '#aaffcc' : '#ffcc88';
        }
    }
    if (studioBadge) {
        studioBadge.innerText = isStudioRunning ? 'RUNNING' : 'STOPPED';
        studioBadge.style.color = isStudioRunning ? '#00ff66' : '#888888';
        studioBadge.style.background = isStudioRunning ? '#113311' : '#222222';
    }

    // Clack Pose (Piranha Pose) button & badge
    const clackPoseBtn = document.getElementById('clackPoseBtn');
    const clackPoseBadge = document.getElementById('clackPoseBadge');
    if (clackPoseBtn) {
        const clackPoseBtnText = document.getElementById('clackPoseBtnText');
        const clackPoseBtnSub = document.getElementById('clackPoseBtnSub');
        clackPoseBtn.style.borderColor = isClackPoseRunning ? '#00ff66' : '#444444';
        clackPoseBtn.style.color = isClackPoseRunning ? '#00ff66' : '#ffffff';
        clackPoseBtn.style.background = isClackPoseRunning ? 'rgba(0, 255, 102, 0.15)' : '#181818';
        if (clackPoseBtnText) clackPoseBtnText.innerText = isClackPoseRunning ? '🛑 STOP PIRANHA POSE' : '🪴 START PIRANHA POSE';
        if (clackPoseBtnSub) {
            clackPoseBtnSub.innerText = isClackPoseRunning ? 'Listening & Sequences Active' : 'Presets, Sequences & Clacks';
            clackPoseBtnSub.style.color = isClackPoseRunning ? '#aaffcc' : '#aaa';
        }
    }
    if (clackPoseBadge) {
        clackPoseBadge.innerText = isClackPoseRunning ? 'LISTENING' : 'STOPPED';
        clackPoseBadge.style.color = isClackPoseRunning ? '#00ff66' : '#888888';
        clackPoseBadge.style.background = isClackPoseRunning ? '#113311' : '#222222';
    }

    // Beat Bandit App Toggle button
    const bbAppToggleBtn = document.getElementById('bbAppToggleBtn');
    const bbAppToggleBtnText = document.getElementById('bbAppToggleBtnText');
    const bbAppToggleBtnSub = document.getElementById('bbAppToggleBtnSub');
    if (bbAppToggleBtn) {
        bbAppToggleBtn.style.borderColor = isBeatBanditAppRunning ? '#a855f7' : '#444444';
        bbAppToggleBtn.style.color = isBeatBanditAppRunning ? '#e9d5ff' : '#ffffff';
        bbAppToggleBtn.style.background = isBeatBanditAppRunning ? 'linear-gradient(135deg, #4c1d95, #2e1065)' : '#181818';
        if (bbAppToggleBtnText) bbAppToggleBtnText.innerText = isBeatBanditAppRunning ? '🛑 STOP BEAT BANDIT' : '🎧 START BEAT BANDIT';
        if (bbAppToggleBtnSub) {
            bbAppToggleBtnSub.innerText = isBeatBanditAppRunning ? 'Engine Active & Ready' : 'Audio Choreography & Timeline Engine';
            bbAppToggleBtnSub.style.color = isBeatBanditAppRunning ? '#d8b4fe' : '#888';
        }
    }

    // Voice Listener App Toggle button
    const listenerAppToggleBtn = document.getElementById('listenerAppToggleBtn');
    const listenerAppToggleBtnText = document.getElementById('listenerAppToggleBtnText');
    const listenerAppToggleBtnSub = document.getElementById('listenerAppToggleBtnSub');
    if (listenerAppToggleBtn) {
        listenerAppToggleBtn.style.borderColor = isListenerAppRunning ? '#00f2fe' : '#444444';
        listenerAppToggleBtn.style.color = isListenerAppRunning ? '#9dfbfa' : '#ffffff';
        listenerAppToggleBtn.style.background = isListenerAppRunning ? 'linear-gradient(135deg, #0e3538, #051d1f)' : '#181818';
        if (listenerAppToggleBtnText) listenerAppToggleBtnText.innerText = isListenerAppRunning ? '🛑 STOP LISTENER APP' : '👂 START LISTENER APP';
        if (listenerAppToggleBtnSub) {
            listenerAppToggleBtnSub.innerText = isListenerAppRunning ? 'Voice Hotword & Speech Pipeline Active' : 'Voice Hotword & Speech-to-Intent Pipeline';
            listenerAppToggleBtnSub.style.color = isListenerAppRunning ? '#9dfbfa' : '#888';
        }
    }

    // Beat Bandit dance button
    const bbMainDanceBtn = document.getElementById('bbMainDanceBtn');
    const bbMainDanceIcon = document.getElementById('bbMainDanceIcon');
    const bbMainDanceText = document.getElementById('bbMainDanceText');
    if (bbMainDanceBtn) {
        if (isBeatBanditDancing || timelineIsPlaying) {
            bbMainDanceBtn.style.background = 'linear-gradient(135deg, #dc2626, #991b1b)';
            bbMainDanceBtn.style.borderColor = '#ef4444';
            bbMainDanceBtn.style.boxShadow = '0 4px 14px rgba(239,68,68,0.5)';
            if (bbMainDanceIcon) bbMainDanceIcon.innerText = '🛑';
            if (bbMainDanceText) bbMainDanceText.innerText = 'STOP';
        } else {
            bbMainDanceBtn.style.background = 'linear-gradient(135deg, #7928ca, #ff0080)';
            bbMainDanceBtn.style.borderColor = '#ff00cc';
            bbMainDanceBtn.style.boxShadow = '0 4px 14px rgba(255,0,128,0.35)';
            if (bbMainDanceIcon) bbMainDanceIcon.innerText = '⚡';
            if (bbMainDanceText) bbMainDanceText.innerText = 'DANCE';
        }
    }

    // Apps status readout
    const appsStatus = document.getElementById('appsStatus');
    if (appsStatus) {
        if (currentOrnithState && currentOrnithState !== 'IDLE') {
            const ost = currentOrnithState;
            if (ost === 'LISTENING') {
                appsStatus.innerText = '🎙️ ORNITH LISTENING...';
                appsStatus.style.color = '#00ff66';
            } else if (ost === 'THINKING') {
                appsStatus.innerText = '💭 ORNITH THINKING...';
                appsStatus.style.color = '#ffaa00';
            } else if (ost === 'SPEAKING') {
                appsStatus.innerText = '🔊 ORNITH SPEAKING...';
                appsStatus.style.color = '#ff00cc';
            } else if (ost === 'AWAITING_INPUT') {
                appsStatus.innerText = '🎙️ TAP B TO SPEAK';
                appsStatus.style.color = '#00e5ff';
            } else {
                appsStatus.innerText = `🎙️ ORNITH ${ost}`;
                appsStatus.style.color = '#00e5ff';
            }
        } else if (isBeatBanditDancing) {
            appsStatus.innerText = 'BEAT BANDIT DANCING';
            appsStatus.style.color = '#ff00cc';
        } else if (isBeatBanditAppRunning) {
            appsStatus.innerText = 'BEAT BANDIT ACTIVE';
            appsStatus.style.color = '#a855f7';
        } else if (isListenerAppRunning) {
            appsStatus.innerText = 'VOICE LISTENER ACTIVE';
            appsStatus.style.color = '#00f2fe';
        } else if (isClackPoseRunning) {
            appsStatus.innerText = 'PIRANHA POSE ACTIVE';
            appsStatus.style.color = '#00ff66';
        } else if (isStudioRunning) {
            appsStatus.innerText = 'CALIBRATION STUDIO ACTIVE';
            appsStatus.style.color = '#ffaa00';
        } else {
            appsStatus.innerText = 'ROBOT APPS IDLE';
            appsStatus.style.color = '#888888';
        }
    }

    // Robot backend button
    const masterBtn = document.getElementById('masterDaemonBtn');
    const masterBtnText = document.getElementById('masterDaemonBtnText');
    const masterBtnSub = document.getElementById('masterDaemonBtnSub');
    if (masterBtn) {
        if (isMasterDaemonRunning) {
            masterBtn.style.borderColor = '#00ff66';
            masterBtn.style.color = '#00ff66';
            masterBtn.style.background = 'rgba(0, 255, 102, 0.12)';
            if (masterBtnText) masterBtnText.innerText = '🟢 STOP ROBOT BACKEND';
            if (masterBtnSub) {
                masterBtnSub.innerText = '(PORT 8085 RUNNING)';
                masterBtnSub.style.color = '#aaffcc';
            }
        } else {
            masterBtn.style.borderColor = '#ffaa00';
            masterBtn.style.color = '#ffffff';
            masterBtn.style.background = '#181818';
            if (masterBtnText) masterBtnText.innerText = '🤖 START ROBOT BACKEND';
            if (masterBtnSub) {
                masterBtnSub.innerText = '(BACKEND STOPPED)';
                masterBtnSub.style.color = '#ffcc88';
            }
        }
    }

    // Pokéball Teleop button
    const pokeballBtn = document.getElementById('pokeballBtn');
    const pbTitle = document.getElementById('pokeballBtnTitle');
    const pbSub = document.getElementById('pokeballBtnSub');
    if (pokeballBtn) {
        if (!isPokeballRunning) {
            pokeballBtn.style.borderColor = '#444444';
            pokeballBtn.style.color = '#ffffff';
            pokeballBtn.style.background = '#181818';
            if (pbTitle) pbTitle.innerText = 'START POKÉBALL';
            if (pbSub) pbSub.style.display = 'none';
        } else if (isPokeballConnected) {
            pokeballBtn.style.borderColor = '#00ff66';
            pokeballBtn.style.color = '#00ff66';
            pokeballBtn.style.background = 'rgba(0, 255, 102, 0.15)';
            if (pbTitle) pbTitle.innerText = 'POKÉBALL CONNECTED';
            if (pbSub) {
                pbSub.style.display = 'block';
                pbSub.innerText = '(Click to Stop)';
                pbSub.style.color = '#aaffcc';
            }
        } else {
            pokeballBtn.style.borderColor = '#ff3344';
            pokeballBtn.style.color = '#ff3344';
            pokeballBtn.style.background = 'rgba(255, 51, 68, 0.15)';
            if (pbTitle) pbTitle.innerText = 'SEARCHING BLE...';
            if (pbSub) {
                pbSub.style.display = 'block';
                pbSub.innerText = 'Press Button to Wake';
                pbSub.style.color = '#ff8899';
            }
        }
    }

    // Drawer Teleop & Input Buttons
    const drawerFollowerBtn = document.getElementById('drawerFollowerBtn');
    const drawerFollowerText = document.getElementById('drawerFollowerText');
    if (drawerFollowerBtn) {
        drawerFollowerBtn.style.borderColor = isFollowerRunning ? '#00ff66' : '#444444';
        drawerFollowerBtn.style.color = isFollowerRunning ? '#00ff66' : '#ffffff';
        if (drawerFollowerText) drawerFollowerText.innerText = isFollowerRunning ? 'STOP TELEOP' : 'START TELEOP';
    }
    const drawerLeaderBtn = document.getElementById('drawerLeaderBtn');
    const drawerLeaderText = document.getElementById('drawerLeaderText');
    if (drawerLeaderBtn) {
        drawerLeaderBtn.style.borderColor = isLeaderRunning ? '#00e5ff' : '#444444';
        drawerLeaderBtn.style.color = isLeaderRunning ? '#00e5ff' : '#ffffff';
        if (drawerLeaderText) drawerLeaderText.innerText = isLeaderRunning ? 'STOP LEADER' : 'START LEADER';
    }
    const drawerPokeballBtn = document.getElementById('drawerPokeballBtn');
    const drawerPokeballText = document.getElementById('drawerPokeballText');
    if (drawerPokeballBtn) {
        drawerPokeballBtn.style.borderColor = isPokeballRunning ? (isPokeballConnected ? '#00ff66' : '#ffaa00') : '#444444';
        drawerPokeballBtn.style.color = isPokeballRunning ? (isPokeballConnected ? '#00ff66' : '#ffaa00') : '#ffffff';
        if (drawerPokeballText) {
            drawerPokeballText.innerText = isPokeballRunning ? (isPokeballConnected ? 'POKÉBALL ACTIVE' : 'SEARCHING BLE') : 'POKÉBALL BLE';
        }
    }

    // Dynamic Launcher Card Badges
    const badgeClacker = document.getElementById('badgeClacker');
    if (badgeClacker) {
        badgeClacker.innerText = isClackPoseRunning ? 'RUNNING' : 'IDLE';
        const card = document.getElementById('launchClackerBtn');
        if (card) {
            if (isClackPoseRunning) card.classList.add('running');
            else card.classList.remove('running');
        }
    }
    const badgeStudio = document.getElementById('badgeStudio');
    if (badgeStudio) {
        badgeStudio.innerText = isStudioRunning ? 'RUNNING' : 'IDLE';
        const card = document.getElementById('launchStudioBtn');
        if (card) {
            if (isStudioRunning) card.classList.add('running');
            else card.classList.remove('running');
        }
    }
    const badgeBeatBandit = document.getElementById('badgeBeatBandit');
    if (badgeBeatBandit) {
        badgeBeatBandit.innerText = isBeatBanditAppRunning ? 'RUNNING' : 'IDLE';
        const card = document.getElementById('launchBeatBanditBtn');
        if (card) {
            if (isBeatBanditAppRunning) card.classList.add('running');
            else card.classList.remove('running');
        }
    }
    const badgeListener = document.getElementById('badgeListener');
    if (badgeListener) {
        badgeListener.innerText = isListenerAppRunning ? 'RUNNING' : 'IDLE';
        const card = document.getElementById('launchListenerBtn');
        if (card) {
            if (isListenerAppRunning) card.classList.add('running');
            else card.classList.remove('running');
        }
    }

    // Top Bar Status Pill
    const topStatusDot = document.getElementById('topStatusDot');
    const topStatusText = document.getElementById('topStatusText');
    if (topStatusDot && topStatusText) {
        if (isBeatBanditDancing) {
            topStatusDot.className = 'status-led led-green';
            topStatusText.innerText = 'BEAT BANDIT DANCING';
        } else if (isBeatBanditAppRunning) {
            topStatusDot.className = 'status-led led-green';
            topStatusText.innerText = 'BEAT BANDIT ACTIVE';
        } else if (isClackPoseRunning) {
            topStatusDot.className = 'status-led led-green';
            topStatusText.innerText = 'PIRANHA POSE ACTIVE';
        } else if (isListenerAppRunning) {
            topStatusDot.className = 'status-led led-green';
            topStatusText.innerText = 'VOICE LISTENER ACTIVE';
        } else if (isFollowerRunning) {
            topStatusDot.className = 'status-led led-green';
            topStatusText.innerText = 'TELEOP ACTIVE';
        } else if (isMasterDaemonRunning) {
            topStatusDot.className = 'status-led led-green';
            topStatusText.innerText = 'ROBOT READY';
        } else {
            topStatusDot.className = 'status-led led-red';
            topStatusText.innerText = 'BACKEND OFFLINE';
        }
    }
}

export function updateConfigUI() {
    const s = currentConfig.clack_threshold || 5200;
    const v = currentConfig.volume_pct !== undefined ? currentConfig.volume_pct : 100;
    const sp = currentConfig.rover_max_speed_pct || 35;
    const a = currentConfig.arm_speed_sec || 1.0;

    const stateKey = `${s}_${v}_${sp}_${a}`;
    if (lastRenderedConfigKey === stateKey) {
        return; // Zero DOM churn
    }
    setLastRenderedConfigKey(stateKey);

    // 1. Sensitivity Threshold
    const elSens = document.getElementById('cfgSensVal');
    if (elSens) elSens.innerText = s;
    const bLow = document.getElementById('cfgSensLow');
    const bNorm = document.getElementById('cfgSensNorm');
    const bHi = document.getElementById('cfgSensHi');
    if (bLow) bLow.classList.toggle('active', s >= 7000);
    if (bNorm) bNorm.classList.toggle('active', s >= 4500 && s < 7000);
    if (bHi) bHi.classList.toggle('active', s < 4500);

    const slBtn = document.getElementById('sensLowBtn');
    const snBtn = document.getElementById('sensNormBtn');
    const shBtn = document.getElementById('sensHiBtn');
    if (slBtn) { slBtn.style.borderColor = (s >= 7000) ? '#00e5ff' : '#555'; slBtn.style.color = (s >= 7000) ? '#00e5ff' : '#fff'; }
    if (snBtn) { snBtn.style.borderColor = (s >= 4500 && s < 7000) ? '#00e5ff' : '#555'; snBtn.style.color = (s >= 4500 && s < 7000) ? '#00e5ff' : '#fff'; }
    if (shBtn) { shBtn.style.borderColor = (s < 4500) ? '#00e5ff' : '#555'; shBtn.style.color = (s < 4500) ? '#00e5ff' : '#fff'; }

    // 2. Volume
    const elVol = document.getElementById('cfgVolVal');
    if (elVol) elVol.innerText = v + '%';
    const bV50 = document.getElementById('cfgVol50');
    const bV75 = document.getElementById('cfgVol75');
    const bV100 = document.getElementById('cfgVol100');
    const bV150 = document.getElementById('cfgVol150');
    if (bV50) bV50.classList.toggle('active', v === 50);
    if (bV75) bV75.classList.toggle('active', v === 75);
    if (bV100) bV100.classList.toggle('active', v === 100);
    if (bV150) bV150.classList.toggle('active', v === 150);

    // 3. Rover Speed
    const off = Math.round(500 * (sp / 100));
    const elSp = document.getElementById('cfgSpeedVal');
    if (elSp) elSp.innerText = sp + '% (' + off + 'µs)';
    const bS35 = document.getElementById('cfgSpeed35');
    const bS50 = document.getElementById('cfgSpeed50');
    const bS70 = document.getElementById('cfgSpeed70');
    const bS100 = document.getElementById('cfgSpeed100');
    if (bS35) bS35.classList.toggle('active', sp === 35);
    if (bS50) bS50.classList.toggle('active', sp === 50);
    if (bS70) bS70.classList.toggle('active', sp === 70);
    if (bS100) bS100.classList.toggle('active', sp === 100);

    // 4. Arm Move Speed
    const elArm = document.getElementById('cfgArmVal');
    if (elArm) elArm.innerText = a.toFixed(1) + 's';
    const bA03 = document.getElementById('cfgArm03');
    const bA06 = document.getElementById('cfgArm06');
    const bA10 = document.getElementById('cfgArm10');
    const bA15 = document.getElementById('cfgArm15');
    if (bA03) bA03.classList.toggle('active', Math.abs(a - 0.3) < 0.05);
    if (bA06) bA06.classList.toggle('active', Math.abs(a - 0.6) < 0.05);
    if (bA10) bA10.classList.toggle('active', Math.abs(a - 1.0) < 0.05);
    if (bA15) bA15.classList.toggle('active', Math.abs(a - 1.5) < 0.05);
}

export function handleBeatBanditPageToggle() {
    const totalTracks = (cachedBeatBanditTracks || []).length;
    const totalPages = Math.max(1, Math.ceil(totalTracks / 4));
    if (beatBanditTrackPage < totalPages - 1) {
        setBeatBanditTrackPage(beatBanditTrackPage + 1);
    } else {
        setBeatBanditTrackPage(0);
    }
    renderBeatBanditTracksList(cachedBeatBanditTracks);
}

export function renderBeatBanditTracksList(tracks) {
    const listEl = document.getElementById('bbTracksList');
    const pageBtn = document.getElementById('bbPageBtn');
    if (!listEl) return;
    if (!tracks || tracks.length === 0) {
        listEl.innerHTML = '<div style="grid-column: span 2; font-size: 11.5px; color: #888; text-align: center; padding: 20px;">No offline tracks cached yet.</div>';
        if (pageBtn) pageBtn.style.display = 'none';
        return;
    }

    const totalPages = Math.max(1, Math.ceil(tracks.length / 4));
    if (beatBanditTrackPage >= totalPages) setBeatBanditTrackPage(0);

    if (pageBtn) {
        if (totalPages <= 1) {
            pageBtn.style.display = 'none';
        } else {
            pageBtn.style.display = 'inline-block';
            pageBtn.innerText = (beatBanditTrackPage < totalPages - 1) ? 'NEXT ⏭️' : 'FIRST ⏮️';
        }
    }

    const startIndex = beatBanditTrackPage * 4;
    const pageTracks = tracks.slice(startIndex, startIndex + 4);

    let html = '';
    pageTracks.forEach(t => {
        const isSelected = (t.track_id === selectedBeatBanditTrackId);
        const mins = Math.floor((t.duration !== undefined && t.duration !== null ? t.duration : 0) / 60);
        const secs = Math.floor((t.duration !== undefined && t.duration !== null ? t.duration : 0) % 60).toString().padStart(2, '0');
        const timeStr = `${mins}:${secs}`;
        const bpmVal = t.tempo ? t.tempo : t.bpm;
        const bpmStr = bpmVal ? `${Math.round(bpmVal)} BPM` : '-- BPM';
        const cardBorder = isSelected ? '2px solid #ff00cc' : '1.5px solid #333348';
        const cardBg = isSelected ? 'linear-gradient(135deg, #2e1040, #180924)' : '#161622';
        const titleSafe = encodeURIComponent(t.title || '');
        const artistSafe = encodeURIComponent(t.artist || '');

        html += `
            <div class="bb-track-card" data-track-id="${t.track_id}" data-title="${titleSafe}" data-artist="${artistSafe}"
                 style="background: ${cardBg}; border: ${cardBorder}; border-radius: 6px; padding: 5px 8px; cursor: pointer; display: flex; flex-direction: column; justify-content: space-between; height: 62px; user-select: none; box-sizing: border-box; min-width: 0;">
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 4px; pointer-events: none;">
                    <span style="font-size: 12px; font-weight: 900; color: #ffffff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${t.title || 'Unknown Track'}</span>
                    <span style="background: ${isSelected ? '#ff00cc' : '#2a2a3a'}; color: ${isSelected ? '#000' : '#888'}; font-size: 8px; font-weight: 900; padding: 1.5px 5px; border-radius: 3px; flex-shrink: 0;">${isSelected ? 'SELECTED' : 'SELECT'}</span>
                </div>
                <div style="font-size: 10px; color: #d8b4fe; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none;">
                    ${t.artist || 'Artist'} - ${timeStr} - ${bpmStr}
                </div>
            </div>
        `;
    });
    listEl.innerHTML = html;
}

export function selectBeatBanditTrack(trackId, encTitle, encArtist) {
    setSelectedBeatBanditTrackId(trackId);
    const title = decodeURIComponent(encTitle || '');
    const artist = decodeURIComponent(encArtist || '');
    const tTitle = document.getElementById('bbTrackTitle');
    const tArtist = document.getElementById('bbTrackArtist');
    const inp = document.getElementById('bbUrlInput');
    const bpmDisplay = document.getElementById('bbBpmDisplay');
    const beatCounter = document.getElementById('bbBeatCounter');
    const stateBadge = document.getElementById('bbStateBadge');

    if (tTitle && title) tTitle.innerText = title;
    if (tArtist && artist) tArtist.innerText = artist;
    if (inp) inp.value = trackId;

    const selectedTrack = (cachedBeatBanditTracks || []).find(t => t.track_id === trackId);
    if (selectedTrack) {
        if (bpmDisplay && selectedTrack.tempo) bpmDisplay.innerText = Math.round(selectedTrack.tempo) + ' BPM';
        if (beatCounter && selectedTrack.total_beats) beatCounter.innerText = `Beat 0/${selectedTrack.total_beats}`;
    }
    if (stateBadge && !isBeatBanditDancing) {
        stateBadge.innerText = 'SELECTED';
        stateBadge.style.background = '#2e1040';
        stateBadge.style.color = '#ff00cc';
    }
    renderBeatBanditTracksList(cachedBeatBanditTracks);
}

export function updateBreadcrumbs(crumbs) {
    if (!Array.isArray(crumbs)) return;
    setActiveBreadcrumbs(crumbs);
    const nav = document.getElementById('breadcrumbNav');
    if (!nav) return;
    nav.innerHTML = '';
    crumbs.forEach((crumb, idx) => {
        if (idx > 0) {
            const sep = document.createElement('span');
            sep.className = 'separator';
            sep.innerText = '>';
            nav.appendChild(sep);
        }
        const span = document.createElement('span');
        const isLast = (idx === crumbs.length - 1);
        span.className = 'crumb' + (isLast ? ' active' : '');
        span.innerText = crumb.name;
        if (crumb.action && !isLast) {
            span.style.cursor = 'pointer';
            span.addEventListener('click', crumb.action);
        }
        nav.appendChild(span);
    });
}

export function toggleQuickControlDrawer(forceState) {
    const newState = (typeof forceState === 'boolean') ? forceState : !isDrawerOpen;
    setIsDrawerOpen(newState);

    const drawer = document.getElementById('quickControlDrawer');
    const backdrop = document.getElementById('drawerBackdrop');
    const toggleBtn = document.getElementById('drawerToggleBtn');

    if (drawer) {
        if (newState) {
            drawer.classList.add('open');
            drawer.setAttribute('aria-hidden', 'false');
        } else {
            drawer.classList.remove('open');
            drawer.setAttribute('aria-hidden', 'true');
        }
    }
    if (backdrop) {
        if (newState) {
            backdrop.classList.add('active');
            backdrop.setAttribute('aria-hidden', 'false');
        } else {
            backdrop.classList.remove('active');
            backdrop.setAttribute('aria-hidden', 'true');
        }
    }
    if (toggleBtn) {
        toggleBtn.setAttribute('aria-expanded', newState ? 'true' : 'false');
        if (newState) {
            toggleBtn.classList.add('active');
        } else {
            toggleBtn.classList.remove('active');
        }
    }
}

export function renderAppCarousel(appsList, activeIndex, onCardClick) {
    if (!Array.isArray(appsList) || appsList.length === 0) return;
    setRegisteredAppsList(appsList);
    const stage = document.getElementById('carouselStage');
    const dotsContainer = document.getElementById('carouselDots');
    const counterEl = document.getElementById('carouselCounter');
    if (!stage) return;

    const total = appsList.length;
    const idx = ((activeIndex % total) + total) % total;
    setCurrentCarouselIndex(idx);
    const app = appsList[idx];

    // 1. Build Hero Card for Active App
    stage.innerHTML = '';
    const heroCard = document.createElement('div');
    heroCard.className = 'carousel-hero-card' + (app.is_running ? ' running' : '');
    heroCard.id = 'carouselHeroCard_' + app.name;
    heroCard.dataset.app = app.name;

    const header = document.createElement('div');
    header.className = 'carousel-hero-header';

    const iconSpan = document.createElement('span');
    iconSpan.className = 'carousel-hero-icon';
    iconSpan.innerText = app.icon || '🤖';

    const titleGroup = document.createElement('div');
    titleGroup.className = 'carousel-hero-title-group';

    const titleDiv = document.createElement('div');
    titleDiv.className = 'carousel-hero-title';
    titleDiv.innerText = (app.title || app.name).toUpperCase();

    const descDiv = document.createElement('div');
    descDiv.className = 'carousel-hero-desc';
    descDiv.innerText = app.description || '';

    titleGroup.appendChild(titleDiv);
    titleGroup.appendChild(descDiv);
    header.appendChild(iconSpan);
    header.appendChild(titleGroup);

    const badge = document.createElement('span');
    badge.className = 'app-card-badge';
    badge.innerText = app.is_running ? 'RUNNING' : 'IDLE';
    header.appendChild(badge);

    const footer = document.createElement('div');
    footer.className = 'carousel-hero-footer';

    const tagsDiv = document.createElement('div');
    tagsDiv.className = 'carousel-hero-tags';
    const tags = Array.isArray(app.tags) ? app.tags.slice(0, 3) : [];
    tags.forEach(t => {
        const tagSpan = document.createElement('span');
        tagSpan.className = 'carousel-tag';
        tagSpan.innerText = t;
        tagsDiv.appendChild(tagSpan);
    });

    const actionDiv = document.createElement('div');
    actionDiv.className = 'carousel-hero-action';
    actionDiv.innerHTML = app.is_running 
        ? '<span>⚡</span><span>RUNNING (TAP TO OPEN)</span>'
        : '<span>🚀</span><span>TAP TO LAUNCH</span>';

    footer.appendChild(tagsDiv);
    footer.appendChild(actionDiv);

    heroCard.appendChild(header);
    heroCard.appendChild(footer);

    if (typeof onCardClick === 'function') {
        heroCard.addEventListener('click', () => onCardClick(app));
    }
    stage.appendChild(heroCard);

    // 2. Render Pagination Dots
    if (dotsContainer) {
        dotsContainer.innerHTML = '';
        appsList.forEach((a, i) => {
            const dot = document.createElement('div');
            dot.className = 'carousel-dot' + (i === idx ? ' active' : '');
            dot.title = a.title || a.name;
            dot.addEventListener('click', (e) => {
                e.stopPropagation();
                renderAppCarousel(appsList, i, onCardClick);
            });
            dotsContainer.appendChild(dot);
        });
    }

    // 3. Update Counter
    if (counterEl) {
        counterEl.innerText = `APP ${idx + 1} OF ${total}: ${(app.title || app.name).toUpperCase()}`;
    }
}

export function renderDynamicAppLauncher(appsList, onCardClick) {
    if (!Array.isArray(appsList) || appsList.length === 0) return;
    setRegisteredAppsList(appsList);

    // 1. Render Carousel (Primary 4" Touch Interface)
    renderAppCarousel(appsList, currentCarouselIndex, onCardClick);

    // 2. Render Compatibility Grid Container (if present)
    const container = document.getElementById('appsGridContainer');
    if (!container) return;

    container.innerHTML = '';
    appsList.forEach(app => {
        const card = document.createElement('button');
        card.className = 'app-card' + (app.is_running ? ' running' : '');
        card.id = 'appCard_' + app.name;
        card.dataset.app = app.name;

        const iconSpan = document.createElement('span');
        iconSpan.className = 'app-card-icon';
        iconSpan.innerText = app.icon || '🤖';

        const infoDiv = document.createElement('div');
        infoDiv.className = 'app-card-info';

        const titleDiv = document.createElement('div');
        titleDiv.className = 'app-card-title';
        titleDiv.innerText = app.title || app.name;

        const descDiv = document.createElement('div');
        descDiv.className = 'app-card-desc';
        descDiv.innerText = app.description || '';

        infoDiv.appendChild(titleDiv);
        infoDiv.appendChild(descDiv);

        const badge = document.createElement('span');
        badge.className = 'app-card-badge';
        badge.innerText = app.is_running ? 'RUNNING' : 'IDLE';

        card.appendChild(iconSpan);
        card.appendChild(infoDiv);
        card.appendChild(badge);

        if (typeof onCardClick === 'function') {
            card.addEventListener('click', () => onCardClick(app));
        }
        container.appendChild(card);
    });
}

export function switchTab(tabId) {
    try { localStorage.setItem('active_tab', tabId); } catch(e) {}
    document.querySelectorAll('.rail-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    const bPower = document.getElementById('topBtnPower');
    if (bPower) {
        if (tabId === 'power') bPower.classList.add('active');
        else bPower.classList.remove('active');
    }

    if (tabId === 'gantry') {
        const b = document.getElementById('railBtnGantry');
        const p = document.getElementById('panelGantry');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
        updateBreadcrumbs([
            { name: 'APPS', action: () => { switchTab('apps'); openAppsSubView('launcher'); } },
            { name: 'GANTRY', action: null }
        ]);
    } else if (tabId === 'controls') {
        const b = document.getElementById('railBtnControls');
        const p = document.getElementById('panelControls');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
        updateBreadcrumbs([
            { name: 'APPS', action: () => { switchTab('apps'); openAppsSubView('launcher'); } },
            { name: 'CONTROLS', action: null }
        ]);
    } else if (tabId === 'apps') {
        const b = document.getElementById('railBtnApps');
        const p = document.getElementById('panelApps');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
        updateBreadcrumbs([
            { name: 'APPS', action: () => openAppsSubView('launcher') }
        ]);
    } else if (tabId === 'power') {
        const b = document.getElementById('railBtnPower');
        const p = document.getElementById('panelPower');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
        updateBreadcrumbs([
            { name: 'APPS', action: () => { switchTab('apps'); openAppsSubView('launcher'); } },
            { name: 'BACKEND', action: null }
        ]);
    }
}

export function openAppsSubView(subview) {
    setCurrentAppsSubView(subview);
    try { localStorage.setItem('apps_subview', subview); } catch(e) {}
    const vLauncher = document.getElementById('appsViewLauncher');
    const vClacker = document.getElementById('appsViewClacker');
    const vStudio = document.getElementById('appsViewStudio');
    const vBeatBandit = document.getElementById('appsViewBeatBandit');
    const vListener = document.getElementById('appsViewListener');
    
    if (vLauncher) vLauncher.style.display = (subview === 'launcher') ? 'block' : 'none';
    if (vClacker) vClacker.style.display = (subview === 'clacker') ? 'block' : 'none';
    if (vStudio) vStudio.style.display = (subview === 'studio') ? 'flex' : 'none';
    if (vBeatBandit) vBeatBandit.style.display = (subview === 'beat_bandit') ? 'flex' : 'none';
    if (vListener) vListener.style.display = (subview === 'listener') ? 'flex' : 'none';

    if (subview === 'launcher') {
        updateBreadcrumbs([{ name: 'APPS', action: null }]);
    } else if (subview === 'clacker') {
        updateBreadcrumbs([
            { name: 'APPS', action: () => openAppsSubView('launcher') },
            { name: 'PIRANHA POSE', action: null }
        ]);
    } else if (subview === 'studio') {
        updateBreadcrumbs([
            { name: 'APPS', action: () => openAppsSubView('launcher') },
            { name: 'SERVO STUDIO', action: null }
        ]);
    } else if (subview === 'beat_bandit') {
        updateBreadcrumbs([
            { name: 'APPS', action: () => openAppsSubView('launcher') },
            { name: 'BEAT BANDIT', action: null }
        ]);
    } else if (subview === 'listener') {
        updateBreadcrumbs([
            { name: 'APPS', action: () => openAppsSubView('launcher') },
            { name: 'VOICE LISTENER', action: null }
        ]);
    }
}

export function openBackendSubView(subview) {
    setCurrentBackendSubView(subview);
    try { localStorage.setItem('backend_subview', subview); } catch(e) {}
    const vMain = document.getElementById('backendViewMain');
    const vPower = document.getElementById('backendViewPower');
    const vConfig = document.getElementById('backendViewConfig');

    if (vMain) vMain.style.display = (subview === 'main') ? 'flex' : 'none';
    if (vPower) vPower.style.display = (subview === 'power') ? 'flex' : 'none';
    if (vConfig) vConfig.style.display = (subview === 'config') ? 'flex' : 'none';
}

export function switchAppsMode(mode) {
    setCurrentAppsMode(mode);
    try { localStorage.setItem('apps_mode', mode); } catch(e) {}
    const controlsEl = document.getElementById('appsModeControls');
    const presetsEl = document.getElementById('appsModePresets');
    if (mode === 'presets') {
        if (controlsEl) controlsEl.style.display = 'none';
        if (presetsEl) presetsEl.style.display = 'flex';
        setCurrentPresetsPage(1);
    } else {
        if (controlsEl) controlsEl.style.display = 'flex';
        if (presetsEl) presetsEl.style.display = 'none';
    }
}

export function setPresetsMode(mode) {
    setCurrentPresetMode(mode);
    try { localStorage.setItem('preset_mode', mode); } catch(e) {}
    ['normal', 'demo', 'angry', 'dance'].forEach(m => {
        const tab = document.getElementById('modeTab' + m.charAt(0).toUpperCase() + m.slice(1));
        if (tab) {
            if (m === mode) {
                tab.style.background = '#004488';
                tab.style.border = '2px solid #00e5ff';
                tab.style.color = '#ffffff';
            } else {
                tab.style.background = '#181818';
                tab.style.border = '2px solid #555555';
                tab.style.color = '#888888';
            }
        }
    });

    const seqBtn = document.getElementById('seqPlayBtn');
    if (seqBtn) {
        if (mode === 'demo') {
            seqBtn.innerHTML = '☠️ 4-CLICK ATTACK DEMO';
            seqBtn.style.background = '#3b0d10';
            seqBtn.style.border = '2.5px solid #ff3344';
            seqBtn.style.color = '#ff4455';
        } else {
            seqBtn.innerHTML = `▶️ PLAY ${mode.toUpperCase()} SEQ`;
            seqBtn.style.background = '#0a3a1a';
            seqBtn.style.border = '2.5px solid #00ff66';
            seqBtn.style.color = '#00ff66';
        }
    }

    setCurrentPresetsPage(1);
}

export function toggleOverwriteMode() {
    setIsOverwriteModeActive(!isOverwriteModeActive);
    const btn = document.getElementById('overwriteModeBtn');
    const appsStatus = document.getElementById('appsStatus');
    if (btn) {
        if (isOverwriteModeActive) {
            btn.innerHTML = '⚠️ OVERWRITE: ON';
            btn.style.background = '#551100';
            btn.style.border = '2px solid #ff5500';
            btn.style.color = '#ffaa00';
            if (appsStatus) {
                appsStatus.innerText = 'OVERWRITE ACTIVE: CLICK SLOT TO REPLACE';
                appsStatus.style.color = '#ffaa00';
            }
        } else {
            btn.innerHTML = '✏️ OVERWRITE: OFF';
            btn.style.background = '#1c1c1c';
            btn.style.border = '2px solid #777777';
            btn.style.color = '#dddddd';
            if (appsStatus) {
                appsStatus.innerText = 'READY';
                appsStatus.style.color = '#00e5ff';
            }
        }
    }
    renderPresetsGrid();
}

export function getModeSlots(mode, presets) {
    const slots = [];
    if (mode === 'dance') {
        const danceDefs = [
            { key: 'stand', label: '1: STAND', num: 1 },
            { key: 'squat', label: '2: SQUAT', num: 2 },
            { key: 'tiptoe', label: '3: TIPTOE', num: 3 },
            { key: 'arch', label: '4: ARCH', num: 4 },
        ];
        danceDefs.forEach(d => {
            slots.push({
                key: d.key,
                label: d.label,
                num: d.num,
                isSaved: !!presets[d.key],
            });
        });
        for (let i = 5; i <= 11; i++) {
            const key = `pose_${i}`;
            slots.push({
                key: key,
                label: `${i}`,
                num: i,
                isSaved: !!presets[key],
            });
        }
    } else if (mode === 'demo') {
        const demoDefs = [
            { key: 'pose_1', label: '1: HOME', num: 1 },
            { key: 'lunge', label: '2: LUNGE', num: 2 },
            { key: 'ready', label: '3: READY', num: 3 },
            { key: 'roar', label: '4: ROAR', num: 4 },
        ];
        demoDefs.forEach(d => {
            slots.push({
                key: d.key,
                label: d.label,
                num: d.num,
                isSaved: !!presets[d.key],
            });
        });
        for (let i = 5; i <= 11; i++) {
            const key = `pose_${i}`;
            slots.push({
                key: key,
                label: `${i}`,
                num: i,
                isSaved: !!presets[key],
            });
        }
    } else {
        for (let i = 1; i <= 11; i++) {
            const key = `pose_${i}`;
            slots.push({
                key: key,
                label: `${i}`,
                num: i,
                isSaved: !!presets[key],
            });
        }
    }
    return slots;
}

export function renderPresetsGrid() {
    const container = document.getElementById('presetsGridContainer');
    if (!container) return;

    const presets = cachedPresetsList || {};
    const slots = getModeSlots(currentPresetMode, presets);

    let html = '';
    const btnBg = isOverwriteModeActive ? '#4a1500' : '#0066cc';
    const btnBorder = isOverwriteModeActive ? '#ff5500' : '#3399ff';
    const btnColor = isOverwriteModeActive ? '#ffaa00' : '#ffffff';

    if (currentPresetsPage === 1) {
        slots.forEach(slot => {
            const isSaved = slot.isSaved;
            const displayLabel = isOverwriteModeActive ? `✏️ ${slot.label}` : slot.label;
            const fSize = slot.label.length > 3 ? '13px' : '22px';
            if (isSaved) {
                html += `<button class="btn-action preset-slot-btn" data-preset="${slot.key}" data-label="${slot.label}" style="background:${btnBg}; border:2.5px solid ${btnBorder}; color:${btnColor}; font-size:${fSize}; font-weight:900; border-radius:8px; cursor:pointer; padding:2px;">${displayLabel}</button>`;
            } else if (isOverwriteModeActive) {
                html += `<button class="btn-action preset-slot-btn" data-preset="${slot.key}" data-label="${slot.label}" style="background:#2a1000; border:2px dashed #aa4400; color:#ff8833; font-size:${fSize}; font-weight:900; border-radius:8px; cursor:pointer; padding:2px;">+ ${slot.label}</button>`;
            } else {
                html += `<button class="btn-action preset-slot-btn" data-preset="${slot.key}" data-label="${slot.label}" disabled style="background:#181818; border:2px solid #3a3a3a; color:#777777; font-size:${fSize}; font-weight:900; border-radius:8px; cursor:not-allowed; padding:2px;">${slot.label}</button>`;
            }
        });

        let maxPoseNum = 0;
        for (const k of Object.keys(presets)) {
            if (k.startsWith('pose_')) {
                const num = parseInt(k.replace('pose_', ''), 10);
                if (!isNaN(num) && num > maxPoseNum) maxPoseNum = num;
            }
        }
        const hasNext = maxPoseNum >= 12;
        if (hasNext) {
            html += `<button class="btn-action preset-page-btn" data-page="2" style="background:#ff9900; border:2.5px solid #ffaa00; color:#000000; font-size:16px; font-weight:900; border-radius:8px; cursor:pointer;">Next ▶</button>`;
        } else {
            html += `<button class="btn-action" disabled style="background:#281808; border:2px solid #5a3810; color:#885520; font-size:16px; font-weight:900; border-radius:8px; cursor:not-allowed;">Next ▶</button>`;
        }
    } else {
        const startNum = 12 + (currentPresetsPage - 2) * 10;
        const endNum = 11 + (currentPresetsPage - 1) * 10;
        const nextStartNum = endNum + 1;

        for (let num = startNum; num <= startNum + 8; num++) {
            const key = `pose_${num}`;
            const isSaved = !!presets[key];
            const label = `${num}`;
            const displayLabel = isOverwriteModeActive ? `✏️ ${label}` : label;
            if (isSaved) {
                html += `<button class="btn-action preset-slot-btn" data-preset="${key}" data-label="${label}" style="background:${btnBg}; border:2.5px solid ${btnBorder}; color:${btnColor}; font-size:22px; font-weight:900; border-radius:8px; cursor:pointer;">${displayLabel}</button>`;
            } else if (isOverwriteModeActive) {
                html += `<button class="btn-action preset-slot-btn" data-preset="${key}" data-label="${label}" style="background:#2a1000; border:2px dashed #aa4400; color:#ff8833; font-size:18px; font-weight:900; border-radius:8px; cursor:pointer;">+${label}</button>`;
            } else {
                html += `<button class="btn-action preset-slot-btn" data-preset="${key}" data-label="${label}" disabled style="background:#181818; border:2px solid #3a3a3a; color:#777777; font-size:22px; font-weight:900; border-radius:8px; cursor:not-allowed;">${label}</button>`;
            }
        }

        html += `<button class="btn-action preset-page-btn" data-page="${currentPresetsPage - 1}" style="background:#ff9900; border:2.5px solid #ffaa00; color:#000000; font-size:16px; font-weight:900; border-radius:8px; cursor:pointer;">◀ Prev</button>`;

        const num10 = endNum;
        const key10 = `pose_${num10}`;
        const isSaved10 = !!presets[key10];
        const label10 = `${num10}`;
        const displayLabel10 = isOverwriteModeActive ? `✏️ ${label10}` : label10;
        if (isSaved10) {
            html += `<button class="btn-action preset-slot-btn" data-preset="${key10}" data-label="${label10}" style="background:${btnBg}; border:2.5px solid ${btnBorder}; color:${btnColor}; font-size:22px; font-weight:900; border-radius:8px; cursor:pointer;">${displayLabel10}</button>`;
        } else if (isOverwriteModeActive) {
            html += `<button class="btn-action preset-slot-btn" data-preset="${key10}" data-label="${label10}" style="background:#2a1000; border:2px dashed #aa4400; color:#ff8833; font-size:18px; font-weight:900; border-radius:8px; cursor:pointer;">+${label10}</button>`;
        } else {
            html += `<button class="btn-action preset-slot-btn" data-preset="${key10}" data-label="${label10}" disabled style="background:#181818; border:2px solid #3a3a3a; color:#777777; font-size:22px; font-weight:900; border-radius:8px; cursor:not-allowed;">${label10}</button>`;
        }

        let maxPoseNum = 0;
        for (const k of Object.keys(presets)) {
            if (k.startsWith('pose_')) {
                const num = parseInt(k.replace('pose_', ''), 10);
                if (!isNaN(num) && num > maxPoseNum) maxPoseNum = num;
            }
        }
        const hasNext = maxPoseNum >= nextStartNum;
        if (hasNext) {
            html += `<button class="btn-action preset-page-btn" data-page="${currentPresetsPage + 1}" style="background:#ff9900; border:2.5px solid #ffaa00; color:#000000; font-size:16px; font-weight:900; border-radius:8px; cursor:pointer;">Next ▶</button>`;
        } else {
            html += `<button class="btn-action" disabled style="background:#281808; border:2px solid #5a3810; color:#885520; font-size:16px; font-weight:900; border-radius:8px; cursor:not-allowed;">Next ▶</button>`;
        }
    }

    container.innerHTML = html;
}

export function changePresetsPage(newPage) {
    setCurrentPresetsPage(Math.max(1, newPage));
    renderPresetsGrid();
}

export function updateTelemetryUI(data) {
    if (!data) {
        const sliderEl = document.getElementById('sliderValDisplay');
        if (sliderEl && lastRenderedSliderText !== 'OFFLINE') {
            sliderEl.innerHTML = '<span style="color:#ff9900;">Pedestal: --°</span> <span style="color:#666;">|</span> <span style="color:#00e5ff;">Gantry: --</span>';
            setLastRenderedSliderText('OFFLINE');
        }
        const teleopEl = document.getElementById('teleopStatus');
        if (teleopEl && lastRenderedTeleopText !== 'DAEMON OFF') {
            teleopEl.innerText = 'DAEMON OFF';
            teleopEl.style.color = '#ff3344';
            setLastRenderedTeleopText('DAEMON OFF');
        }
        setIsFollowerRunning(false);
        setIsLeaderRunning(false);
        setIsPokeballRunning(false);
        setIsPokeballConnected(false);
        const topVoskDot = document.getElementById('topVoskDot');
        if (topVoskDot) topVoskDot.className = 'status-led led-red';
        const topVoskLabel = document.getElementById('topVoskLabel');
        if (topVoskLabel) topVoskLabel.style.color = '#888888';
        renderButtonStates();
        return;
    }

    // 1. Motor Position Readout (Tab 1)
    const ht = data.hardware_telemetry || {};
    const servos = ht.servos || data.servos || {};
    const m7 = servos['7'];
    const m8 = servos['8'];
    let m7Str = (m7 && m7.angle !== undefined && m7.angle !== null) ? m7.angle + '°' : '--°';
    let m8Str = (m8 && m8.pos !== undefined && m8.pos !== null) ? m8.pos + ' ticks' : '--';
    if (m8 && m8.pos !== undefined && m8.pos !== null) setCurrentVerifiedPos(m8.pos);

    const sliderTextKey = `${m7Str}_${m8Str}`;
    if (lastRenderedSliderText !== sliderTextKey) {
        setLastRenderedSliderText(sliderTextKey);
        const sliderEl = document.getElementById('sliderValDisplay');
        if (sliderEl) {
            sliderEl.innerHTML = `<span style="color:#ff9900;">Pedestal: ${m7Str}</span> <span style="color:#666;">|</span> <span style="color:#00e5ff;">Gantry: ${m8Str}</span>`;
        }
        const drawerSliderEl = document.getElementById('drawerSliderValDisplay');
        if (drawerSliderEl) {
            drawerSliderEl.innerHTML = `<span style="color:#ff9900;">Ped: ${m7Str}</span> | <span style="color:#00e5ff;">Gantry: ${m8Str}</span>`;
        }
    }

    // App Manager & Service State
    const ams = ht.app_manager_status || {};
    let activeAppName = ht.current_app || ams.current_app;
    if (!activeAppName && Array.isArray(ht.apps)) {
        const runningAppObj = ht.apps.find(a => a.is_running);
        if (runningAppObj) activeAppName = runningAppObj.name;
    }
    const currentApp = activeAppName;
    const telemLeader = ht.leader;
    
    setIsStudioRunning(currentApp === 'servo_studio_app');
    setIsClackPoseRunning(currentApp === 'clack_pose_app' || currentApp === 'piranha_pose_app');
    setIsFollowerRunning(currentApp === 'teleop_app');
    setIsLeaderRunning(!!((data.leader && data.leader.running) || (telemLeader && telemLeader.running)));
    setIsListenerAppRunning(currentApp === 'listener_app');
    if (data && data.ornith_state) {
        setCurrentOrnithState(data.ornith_state);
    }
    
    let teleopStatusStr = 'DAEMON OFF';
    let teleopStatusColor = '#ff3344';
    if (isStudioRunning) {
        teleopStatusStr = 'CALIBRATION ACTIVE';
        teleopStatusColor = '#ffaa00';
    } else if (isFollowerRunning) {
        teleopStatusStr = 'TELEOP ACTIVE';
        teleopStatusColor = '#00ff66';
    } else if (currentApp === 'beat_bandit_app') {
        setIsBeatBanditAppRunning(true);
        teleopStatusStr = 'BEAT BANDIT ACTIVE';
        teleopStatusColor = '#a855f7';
    } else {
        setIsBeatBanditAppRunning(false);
    }
    if (currentApp === 'listener_app') {
        teleopStatusStr = 'LISTENER ACTIVE';
        teleopStatusColor = '#00f2fe';
    } else if (currentApp === 'clack_pose_app' || currentApp === 'piranha_pose_app') {
        teleopStatusStr = 'PIRANHA POSE ACTIVE';
        teleopStatusColor = '#00e5ff';
    } else if (currentApp === 'pokeball_teleop_app') {
        teleopStatusStr = 'POKEBALL ACTIVE';
        teleopStatusColor = '#ff3344';
    } else if (currentApp === 'ornith_voice') {
        const ost = data.ornith_state;
        if (!ost) {
            teleopStatusStr = 'ORNITH --';
            teleopStatusColor = '#00e5ff';
        } else {
            teleopStatusStr = (ost === 'AWAITING_INPUT') ? 'TAP B TO SPEAK' : `ORNITH ${ost.toUpperCase()}`;
            teleopStatusColor = (ost === 'LISTENING') ? '#00ff66' : (ost === 'THINKING' ? '#ffaa00' : (ost === 'SPEAKING' ? '#ff00cc' : '#00e5ff'));
        }
    } else if (data.daemon_running) {
        teleopStatusStr = 'DAEMON READY';
        teleopStatusColor = '#00e5ff';
    }

    if (lastRenderedTeleopText !== teleopStatusStr) {
        setLastRenderedTeleopText(teleopStatusStr);
        const teleopEl = document.getElementById('teleopStatus');
        if (teleopEl) {
            teleopEl.innerText = teleopStatusStr;
            teleopEl.style.color = teleopStatusColor;
        }
        const drawerTeleopEl = document.getElementById('drawerTeleopStatus');
        if (drawerTeleopEl) {
            drawerTeleopEl.innerText = teleopStatusStr;
            drawerTeleopEl.style.color = teleopStatusColor;
        }
    }

    // Bus voltage & aux calibration telemetry
    const busVoltVal = (data.bus_voltage !== undefined && data.bus_voltage !== null) ? data.bus_voltage : (ht.bus_voltage !== undefined ? ht.bus_voltage : null);
    const voltBadge = document.getElementById('topVoltageBadge');
    if (voltBadge && busVoltVal !== null && busVoltVal > 0) {
        voltBadge.innerText = `${busVoltVal.toFixed(1)}V`;
        voltBadge.style.borderColor = busVoltVal >= 11.5 ? '#00ff66' : '#ffaa00';
        voltBadge.style.color = busVoltVal >= 11.5 ? '#00ff66' : '#ffaa00';
    }
    if (data.aux_calibration || ht.aux_calibration) {
        setAuxCalibrationData(data.aux_calibration || ht.aux_calibration);
    }

    const pkData = data.pokeball || {};
    setIsPokeballRunning(currentApp === 'pokeball_teleop_app');
    setIsPokeballConnected(!!pkData.connected);
    const pkTelem = pkData.telemetry || (ht.pokeball);

    setIsMasterDaemonRunning(!!data.daemon_running);

    // Parse Pokeball Live Telemetry
    if (pkTelem || pkData) {
        const badge = document.getElementById('pbConnectBadge');
        const joy = document.getElementById('pbJoyReadout');
        const dir = document.getElementById('pbDirReadout');
        const rawHex = document.getElementById('pbRawHex');
        const pkt = document.getElementById('pbPktReadout');
        const btnA = document.getElementById('pbBtnA');
        const btnB = document.getElementById('pbBtnB');
        const activeTelem = pkTelem || pkData;

        const drawerPbBadge = document.getElementById('drawerPbBadge');
        const drawerPbDir = document.getElementById('drawerPbDir');
        const drawerPbJoy = document.getElementById('drawerPbJoy');
        const drawerPbPkts = document.getElementById('drawerPbPkts');

        if (badge) {
            if (isPokeballConnected) {
                badge.innerText = '🟢 CONNECTED';
                badge.style.background = 'rgba(0,255,102,0.2)';
                badge.style.color = '#00ff66';
            } else if (isPokeballRunning) {
                badge.innerText = '🔴 SEARCHING (NOT CONNECTED)';
                badge.style.background = 'rgba(255,51,68,0.2)';
                badge.style.color = '#ff3344';
            } else {
                badge.innerText = '⚪ DISCONNECTED';
                badge.style.background = '#222';
                badge.style.color = '#888';
            }
        }

        if (drawerPbBadge) {
            if (isPokeballConnected) {
                drawerPbBadge.innerText = '🟢 CONNECTED';
                drawerPbBadge.style.color = '#00ff66';
            } else if (isPokeballRunning) {
                drawerPbBadge.innerText = '🔴 SEARCHING';
                drawerPbBadge.style.color = '#ff3344';
            } else {
                drawerPbBadge.innerText = '⚪ DISCONNECTED';
                drawerPbBadge.style.color = '#888';
            }
        }

        if (dir && activeTelem) dir.innerText = (activeTelem.x_direction ? activeTelem.x_direction.toUpperCase() : '--');
        if (drawerPbDir && activeTelem) drawerPbDir.innerText = (activeTelem.x_direction ? activeTelem.x_direction.toUpperCase() : '--');

        if (joy && activeTelem) {
            if (activeTelem.norm_x !== undefined && activeTelem.norm_y !== undefined) {
                joy.innerText = `X: ${activeTelem.norm_x.toFixed(2)}, Y: ${activeTelem.norm_y.toFixed(2)}`;
            } else {
                joy.innerText = '--';
            }
        }
        if (drawerPbJoy && activeTelem) {
            if (activeTelem.norm_x !== undefined && activeTelem.norm_y !== undefined) {
                drawerPbJoy.innerText = `(${activeTelem.norm_x.toFixed(2)}, ${activeTelem.norm_y.toFixed(2)})`;
            } else {
                drawerPbJoy.innerText = '--';
            }
        }

        if (rawHex && activeTelem) rawHex.innerText = activeTelem.raw_hex || '--';
        if (pkt && activeTelem) pkt.innerText = (activeTelem.packet_count !== undefined && activeTelem.packet_count !== null) ? activeTelem.packet_count : '--';
        if (drawerPbPkts && activeTelem) drawerPbPkts.innerText = (activeTelem.packet_count !== undefined && activeTelem.packet_count !== null) ? activeTelem.packet_count : '--';
        
        if (btnA && activeTelem) {
            const isTopActive = activeTelem.button_top || activeTelem.button_a;
            btnA.style.background = isTopActive ? '#ff3344' : '#222';
            btnA.style.color = isTopActive ? '#fff' : '#666';
        }
        if (btnB && activeTelem) {
            const isStickActive = activeTelem.button_stick || activeTelem.button_b;
            btnB.style.background = isStickActive ? '#00ff66' : '#222';
            btnB.style.color = isStickActive ? '#000' : '#666';
        }
    }

    // Parse Clack Pose Acoustic Telemetry
    const cpData = data.clack_pose || {};
    const peakEl = document.getElementById('clackPeakDisplay');
    const noiseEl = document.getElementById('clackNoiseDisplay');
    const threshEl = document.getElementById('clackThreshDisplay');
    if (peakEl && cpData.current_peak !== undefined) peakEl.innerText = cpData.current_peak;
    if (noiseEl && cpData.noise_floor !== undefined) noiseEl.innerText = cpData.noise_floor;
    if (threshEl && cpData.peak_threshold !== undefined) threshEl.innerText = cpData.peak_threshold;

    // Populate Servo Readouts (1-8)
    for (let i = 1; i <= 8; i++) {
        const s = servos[i] || {};
        const el = document.getElementById('telemServo' + i);
        let valText = '--';
        let valColor = '#666';

        if (i <= 6) {
            const norm = (s.normalized !== undefined && s.normalized !== null) ? s.normalized : s.norm;
            if (norm !== undefined && norm !== null) {
                let dispPct = Number(norm);
                if (i <= 5) {
                    dispPct = (dispPct + 100) / 2.0;
                }
                dispPct = Math.max(0, Math.min(100, dispPct));
                valText = dispPct.toFixed(0) + '%';
                valColor = (i === 6) ? '#ff00cc' : '#00ff66';
            }
        } else if (i === 7) {
            const deg = (s.deg !== undefined && s.deg !== null) ? s.deg : '--';
            const sign = Number(deg) > 0 ? '+' : '';
            valText = deg !== '--' ? (sign + deg + '°') : '--';
            valColor = '#ffaa00';
        } else if (i === 8) {
            valText = (s.pos !== undefined && s.pos !== null) ? s.pos : '--';
            valColor = '#00e5ff';
        }

        if (el && el.innerText !== valText) {
            el.innerText = valText;
            el.style.color = valColor;
        }
    }

    // Beat Bandit Telemetry Parsing
    const bbData = ht.beat_bandit || data.beat_bandit || {};
    const isDancingState = !!(bbData.is_dancing || bbData.is_playing || bbData.state === 'DANCING' || bbData.state === 'PLAYING');
    setIsBeatBanditDancing(isDancingState);
    if (!isDancingState && timelineIsPlaying) {
        setTimelineIsPlaying(false);
    }

    const bbBadge = document.getElementById('bbStateBadge');
    if (bbBadge) {
        const st = bbData.state || (isBeatBanditDancing ? 'DANCING' : (isBeatBanditAppRunning ? 'ACTIVE' : 'IDLE'));
        if (bbBadge.innerText !== st) {
            bbBadge.innerText = st;
            if (st === 'DANCING' || st === 'PLAYING') {
                bbBadge.style.background = '#113311';
                bbBadge.style.color = '#00ff66';
            } else if (st === 'ANALYZING' || st === 'DOWNLOADING') {
                bbBadge.style.background = '#332200';
                bbBadge.style.color = '#ffaa00';
            } else {
                bbBadge.style.background = '#222222';
                bbBadge.style.color = '#888888';
            }
        }
    }

    const trackObj = bbData.track || (bbData.active_track ? { title: bbData.active_track, artist: bbData.artist || '' } : null);
    if (trackObj) {
        const tTitle = document.getElementById('bbTrackTitle');
        const tArtist = document.getElementById('bbTrackArtist');
        if (tTitle && trackObj.title && tTitle.innerText !== trackObj.title) tTitle.innerText = trackObj.title;
        if (tArtist && trackObj.artist && tArtist.innerText !== trackObj.artist) tArtist.innerText = trackObj.artist;
    }

    const bbProg = document.getElementById('bbProgressBar');
    const bbBeatCtr = document.getElementById('bbBeatCounter');
    const progVal = (bbData.progress !== undefined) ? bbData.progress : bbData.progress_pct;
    if (bbProg && progVal !== undefined) bbProg.style.width = progVal + '%';
    if (bbBeatCtr && bbData.current_beat !== undefined) {
        let totalB = '--';
        if (bbData.total_beats !== undefined && bbData.total_beats !== null) {
            totalB = bbData.total_beats;
        } else if (activeChoreoData && activeChoreoData.beat_times) {
            totalB = activeChoreoData.beat_times.length;
        }
        bbBeatCtr.innerText = `Beat: ${bbData.current_beat} / ${totalB}`;
    }

    if (bbData.time_sec !== undefined && (isDancingState || timelineIsPlaying)) {
        setTimelinePlayheadTime(bbData.time_sec);
        if (bbStudioTab === 'timeline') {
            updateTimelinePlayhead(bbData.time_sec);
        }
    }

    const bbBpm = document.getElementById('bbBpmDisplay');
    const bbJaw = document.getElementById('bbJawDisplay');
    const bbS7 = document.getElementById('bbS7Display');
    const bbMove = document.getElementById('bbMoveDisplay');

    const tempoVal = (bbData.tempo !== undefined) ? bbData.tempo : bbData.bpm;
    if (bbBpm && tempoVal) bbBpm.innerText = Number(tempoVal).toFixed(1) + ' BPM';
    if (bbJaw && bbData.vocal_power !== undefined) bbJaw.innerText = (Number(bbData.vocal_power) * 100).toFixed(0) + '%';
    const s7Val = (bbData.s7_angle_deg !== undefined) ? bbData.s7_angle_deg : bbData.pedestal_angle_deg;
    if (bbS7 && s7Val !== undefined && s7Val !== null) {
        const s7num = Number(s7Val);
        bbS7.innerText = (s7num > 0 ? '+' : '') + s7num.toFixed(1) + '°';
    }
    if (bbMove && bbData.current_move) bbMove.innerText = bbData.current_move;

    // Voice Listener Telemetry Parsing
    const listenerData = ht.listener !== undefined ? ht.listener : data.listener;
    if (listenerData) {
        renderListenerTracks(
            listenerData.query,
            listenerData.search_results,
            listenerData.selected_index,
            listenerData.state,
            listenerData.transcript,
            listenerData.action_taken
        );
    }

    // Vosk Standby Health LED Indicator
    const topVoskDot = document.getElementById('topVoskDot');
    const topVoskLabel = document.getElementById('topVoskLabel');
    const railVoskDot = document.getElementById('railVoskDot');
    const listenerCardVoskDot = document.getElementById('listenerCardVoskDot');
    const isVoskReady = Boolean(data.vosk_ready);
    if (topVoskDot) {
        topVoskDot.className = isVoskReady ? 'status-led led-green' : 'status-led led-red';
    }
    if (topVoskLabel) {
        topVoskLabel.style.color = isVoskReady ? '#00ff66' : '#888888';
    }
    if (railVoskDot) {
        railVoskDot.className = isVoskReady ? 'status-led led-green' : 'status-led led-red';
        const label = document.getElementById('railVoskLabel');
        if (label) label.style.color = isVoskReady ? '#00ff66' : '#888888';
    }
    if (listenerCardVoskDot) {
        listenerCardVoskDot.className = isVoskReady ? 'status-led led-green' : 'status-led led-red';
    }

    renderButtonStates();

    // Power / Connection Mode Status (Tab 4)
    const pStatus = document.getElementById('powerStatus');
    const cm = data.connection_mode || {};
    const hostIp = data.pi4b_wlan_ip || '127.0.0.1';
    let ipBadge = ` [${hostIp}]`;

    let modeBadge = '🔵 OFFLINE (ETH)';
    if (cm.mode === 'IPHONE_HOTSPOT') {
        modeBadge = '🟢 IPHONE HOTSPOT' + ipBadge;
    } else if (cm.mode === 'HOME_WIFI') {
        modeBadge = '🟢 MAESTAS MANSION' + ipBadge;
    } else if (cm.ssid) {
        modeBadge = '🟢 ' + cm.ssid.toUpperCase() + ipBadge;
    }

    if (pStatus) {
        let pStatusHtml = '';
        const isBackendUp = !!(data.backend_online !== undefined ? data.backend_online : data.daemon_running);
        const volt = (ht.bus_voltage !== undefined) ? ht.bus_voltage.toFixed(1) + 'V' : '--V';
        const pogoState = (ht.pogo_connected) ? 'POGO: OK' : 'POGO: DISC';

        if (isBackendUp) {
            pStatusHtml = `HOST: PI 4B [${hostIp}] | ${modeBadge} | BACKEND: ACTIVE | 12V: ${volt} | ${pogoState}`;
            pStatus.style.color = ht.pogo_connected ? '#00ff66' : '#00e5ff';
        } else {
            pStatusHtml = `HOST: PI 4B [${hostIp}] | ${modeBadge} | <span style="color:#ff3344;">BACKEND: OFFLINE</span>`;
            pStatus.style.color = '#ffaa00';
        }
        if (lastRenderedPowerText !== pStatusHtml) {
            setLastRenderedPowerText(pStatusHtml);
            pStatus.innerHTML = pStatusHtml;
        }
    }

    if (data.config) {
        mergeConfigTelemetry(data.config);
        updateConfigUI();
    }
}

/**
 * ============================================================================
 * BEAT BANDIT CHOREOGRAPHY STUDIO UI RENDERING & TIMELINE INTERACTION
 * ============================================================================
 */

export function switchBbStudioTab(tab) {
    setBbStudioTab(tab);
    
    // Update SubNav button active states
    const navPlayer = document.getElementById('bbNavPlayer');
    const navTimeline = document.getElementById('bbNavTimeline');
    const navPoses = document.getElementById('bbNavPoses');
    const navSettings = document.getElementById('bbNavSettings');

    if (navPlayer) navPlayer.classList.toggle('active', tab === 'player');
    if (navTimeline) navTimeline.classList.toggle('active', tab === 'timeline');
    if (navPoses) navPoses.classList.toggle('active', tab === 'poses');
    if (navSettings) navSettings.classList.toggle('active', tab === 'settings');

    // Update SubView visibility
    const vPlayer = document.getElementById('bbSubViewPlayer');
    const vTimeline = document.getElementById('bbSubViewTimeline');
    const vPoses = document.getElementById('bbSubViewPoses');
    const vSettings = document.getElementById('bbSubViewSettings');

    if (vPlayer) vPlayer.style.display = (tab === 'player') ? 'flex' : 'none';
    if (vTimeline) vTimeline.style.display = (tab === 'timeline') ? 'flex' : 'none';
    if (vPoses) vPoses.style.display = (tab === 'poses') ? 'flex' : 'none';
    if (vSettings) vSettings.style.display = (tab === 'settings') ? 'flex' : 'none';

    if (tab === 'timeline') {
        renderTimeline();
    } else if (tab === 'poses') {
        renderPosesList();
    } else if (tab === 'settings') {
        renderSettingsView();
    }
}

export function renderTimeline() {
    if (!activeChoreoData || !activeChoreoData.duration || activeChoreoData.duration <= 0) return;

    const duration = activeChoreoData.duration;
    const pps = timelinePixelsPerSec;
    const labelOffset = 100; // 100px track label width
    const totalWidth = Math.max(900, duration * pps + labelOffset + 50);

    const canvas = document.getElementById('bbTimelineTrackCanvas');
    if (canvas) canvas.style.width = `${totalWidth}px`;

    // 1. Update Title & Header Pill
    const headerPill = document.getElementById('bbHeaderTrackTitle');
    if (headerPill) headerPill.innerText = activeChoreoData.title || selectedBeatBanditTrackId;

    // 2. Render Separated 2-Level Ruler: Time Ticks & Section Badges
    const rulerTicks = document.getElementById('bbTimelineRulerTicks');
    const rulerSections = document.getElementById('bbTimelineRulerSections');
    
    if (rulerTicks) {
        let ticksHtml = '';
        const stepSec = (duration > 120) ? 5 : 2;
        for (let t = 0; t <= duration; t += stepSec) {
            const leftPx = labelOffset + (t * pps);
            const isMajor = (t % 10 === 0);
            const mins = Math.floor(t / 60);
            const secs = (t % 60).toString().padStart(2, '0');
            const timeLabel = (t >= 60) ? `${mins}:${secs}` : `${t}s`;
            ticksHtml += `
                <div class="bb-ruler-tick ${isMajor ? 'major' : ''}" style="left: ${leftPx}px;" title="${timeLabel}">
                    ${timeLabel}
                </div>
            `;
        }
        rulerTicks.innerHTML = ticksHtml;
    }

    if (rulerSections) {
        let sectionsHtml = '';
        const sections = activeChoreoData.sections || [];
        const secColors = {
            'BEATLESS_INTRO': 'linear-gradient(90deg, #1e3a8a, #1d4ed8)',
            'VERSE_GROOVE': 'linear-gradient(90deg, #6b21a8, #581c87)',
            'SNARE_BUILDUP': 'linear-gradient(90deg, #c2410c, #9a3412)',
            'PRE_DROP_VACUUM': 'linear-gradient(90deg, #be123c, #881337)',
            'DROP_BURST': 'linear-gradient(90deg, #047857, #065f46)',
            'CLIMACTIC_BELT': 'linear-gradient(90deg, #be185d, #831843)',
        };

        sections.forEach(s => {
            const leftPx = labelOffset + (s.start_sec * pps);
            const widthPx = Math.max(30, (s.end_sec - s.start_sec) * pps);
            const bg = secColors[s.type] || 'linear-gradient(90deg, #374151, #1f2937)';
            sectionsHtml += `
                <div class="bb-ruler-sec" style="left: ${leftPx}px; width: ${widthPx}px; background: ${bg};" title="${s.name} (${s.start_sec}s - ${s.end_sec}s)">
                    ${s.name} (${s.start_sec}s)
                </div>
            `;
        });
        rulerSections.innerHTML = sectionsHtml;
    }

    // 3. Helper to render blocks
    function renderLaneBlocks(laneEl, blockList, channelKey, blockClass) {
        if (!laneEl) return;
        let html = '';
        let runningPedDeg = null;
        let prevGantryPos = null;

        function formatConciseBlockLabel(channelKey, blk, st, et) {
            if (channelKey === 'lyrics' || channelKey === 'lyrics_phrasing') {
                if (blk.type === 'breath') return '[breath]';
                return blk.text || blk.name || '';
            }

            const rawName = blk.name || '';

            if (channelKey === 's7_pedestal') {
                let endDeg = 0;
                if (blk.target_deg !== undefined && blk.target_deg !== null) {
                    endDeg = Math.round(Number(blk.target_deg));
                } else if (blk.target_pos_rom !== undefined && blk.target_pos_rom !== null) {
                    endDeg = Math.round((Number(blk.target_pos_rom) - 50.0) * 2.7);
                } else if (runningPedDeg !== null) {
                    endDeg = runningPedDeg;
                }

                const deltaDeg = (runningPedDeg !== null) ? endDeg - runningPedDeg : 0;
                runningPedDeg = endDeg;

                const endHeadingStr = (endDeg > 0) ? `+${endDeg}°` : `${endDeg}°`;

                if (deltaDeg === 0) {
                    if (endDeg === 0) return `Center (0°)`;
                    return `Hold (${endHeadingStr})`;
                } else if (deltaDeg > 0) {
                    return `Left +${deltaDeg}° (${endHeadingStr})`;
                } else {
                    return `Right ${deltaDeg}° (${endHeadingStr})`;
                }
            }

            if (channelKey === 's8_gantry') {
                const pos = (blk.target_pos !== undefined && blk.target_pos !== null) ? parseInt(blk.target_pos, 10) : null;
                const mode = String(blk.mode || 'hold').toLowerCase();
                const pPos = prevGantryPos;
                if (pos !== null) prevGantryPos = pos;

                if (mode === 'full_glide' || mode === 'glide') {
                    if (pos !== null && pPos !== null && pos > pPos) return `Glide Right (${pos})`;
                    if (pos !== null && pPos !== null && pos < pPos) return `Glide Left (${pos})`;
                    return pos !== null ? `Glide (${pos})` : 'Glide';
                }
                if (mode === 'hold_to_drop_glide' || mode.includes('drop')) return pos !== null ? `Drop Peak (${pos})` : 'Drop Peak';
                if (mode === 'late_move') return pos !== null ? `Late Settle (${pos})` : 'Late Settle';
                if (mode === 'early_settle') return pos !== null ? `Early Settle (${pos})` : 'Early Settle';
                if (mode === 'hold') return pos !== null ? `Hold (${pos})` : 'Hold';
                return pos !== null ? `${mode.replace(/_/g, ' ')} (${pos})` : mode.replace(/_/g, ' ');
            }

            if (channelKey === 'spine_gaze' || channelKey === 'body_pose') {
                const pose = String(blk.pose_name || blk.mid_pose || blk.end_pose || 'Stand');
                const poseName = pose.charAt(0).toUpperCase() + pose.slice(1);
                if (blk.bounce_modifier && blk.bounce_modifier.enabled) {
                    const bInt = Math.round(Number(blk.bounce_modifier.intensity || 0.12) * 100);
                    return `${poseName} (${bInt}% ↕)`;
                }
                return poseName;
            }

            if (channelKey === 's1_torso') {
                if (blk.groove_intensity !== undefined) {
                    const gPct = Math.round(Number(blk.groove_intensity) * 100);
                    if (gPct === 100) return `Counter (100%)`;
                    if (gPct === 50) return `Verse (50%)`;
                    if (gPct === 0) return `Still (0%)`;
                    return `${gPct}%`;
                }
                return 'Verse (50%)';
            }

            if (channelKey === 's5_head_tilt') {
                let tiltDeg = 0;
                if (blk.tilt_deg !== undefined) {
                    tiltDeg = Math.round(Number(blk.tilt_deg));
                } else if (blk.tilt_rom !== undefined) {
                    tiltDeg = Math.round((Number(blk.tilt_rom) - 50.0) * 0.5);
                }
                if (tiltDeg === 0 || blk.tilt_mode === 'center') return 'Level (0°)';
                if (tiltDeg > 0) return `Snap Right (+${tiltDeg}°)`;
                return `Snap Left (${tiltDeg}°)`;
            }

            if (channelKey === 's6_jaw' || channelKey === 'head_jaw') {
                const isSinging = (blk.jaw_mode === 'singing' || blk.is_vocal === true || blk.type === 'lyric');
                return isSinging ? 'Singing' : 'Closed';
            }

            return rawName || blk.text || (blk.measure !== undefined && blk.start_beat !== undefined ? `M${blk.measure + 1} B${blk.start_beat + 1}` : `${st.toFixed(1)}s`);
        }

        (blockList || []).forEach((blk) => {
            const st = Number(blk.start_sec !== undefined ? blk.start_sec : (blk.time_sec !== undefined ? blk.time_sec : 0));
            const et = Number(blk.end_sec !== undefined ? blk.end_sec : st);
            const dur = Math.max(0.05, et - st);

            const leftPx = st * pps;
            const widthPx = Math.max(4, dur * pps);
            const isSel = selectedMoveBlock && selectedMoveBlock.id === blk.id;

            let label = formatConciseBlockLabel(channelKey, blk, st, et);
            let effectiveClass = blockClass;

            if (channelKey === 'lyrics' || channelKey === 'lyrics_phrasing') {
                const isBreath = (blk.type === 'breath');
                if (isBreath) {
                    effectiveClass = 'block-lyric-breath';
                } else if (blk.style === 'belting') {
                    effectiveClass = 'block-vocal-belting';
                } else if (blk.style === 'conversational') {
                    effectiveClass = 'block-vocal-conversational';
                } else {
                    effectiveClass = 'block-lyric-vocal';
                }
            } else if (channelKey === 'spine_gaze' || channelKey === 'body_pose') {
                const pose = String(blk.pose_name || blk.mid_pose || blk.end_pose || 'stand').toLowerCase();
                if (pose === 'squat') {
                    effectiveClass = 'block-spine-squat';
                } else if (pose === 'tiptoe') {
                    effectiveClass = 'block-spine-tiptoe';
                } else if (pose === 'arch') {
                    effectiveClass = 'block-spine-arch';
                } else {
                    effectiveClass = 'block-spine-stand';
                }
            } else if (channelKey === 's8_gantry') {
                const mode = String(blk.mode || 'hold').toLowerCase();
                const isDrop = (blk.drop_sec !== null && blk.drop_sec !== undefined) || mode.includes('drop');
                if (isDrop) {
                    effectiveClass = 'block-s8-drop';
                } else if (mode === 'full_glide') {
                    effectiveClass = 'block-s8-full_glide';
                } else if (mode === 'early_step' || mode === 'early_settle') {
                    effectiveClass = 'block-s8-early_step';
                } else if (mode === 'late_step' || mode === 'late_move') {
                    effectiveClass = 'block-s8-late_step';
                } else {
                    effectiveClass = 'block-s8-hold';
                }
            } else if (channelKey === 's7_pedestal') {
                if (blk.target_deg !== undefined) {
                    const tdeg = Number(blk.target_deg);
                    effectiveClass = tdeg > 5 ? 'block-s7-left' : (tdeg < -5 ? 'block-s7-right' : 'block-s7-center');
                } else if (blk.mode) {
                    const m = String(blk.mode).toLowerCase();
                    effectiveClass = m.includes('left') ? 'block-s7-left' : (m.includes('right') ? 'block-s7-right' : 'block-s7-center');
                } else {
                    effectiveClass = 'block-s7-center';
                }
            } else if (channelKey === 's1_torso') {
                if (blk.groove_intensity !== undefined) {
                    const groove = Number(blk.groove_intensity);
                    effectiveClass = groove <= 0.05 ? 'block-s1-still' : (groove >= 0.75 ? 'block-s1-dance' : 'block-s1-verse');
                } else if (blk.facing_mode === 'audience_counter') {
                    effectiveClass = 'block-s1-dance';
                } else {
                    effectiveClass = 'block-s1-verse';
                }
            } else if (channelKey === 's5_head_tilt') {
                if (blk.tilt_mode === 'continuous_roll') {
                    effectiveClass = 'block-s5-roll';
                } else if (blk.tilt_deg !== undefined) {
                    const tilt = Number(blk.tilt_deg);
                    effectiveClass = tilt < -2 ? 'block-s5-left' : (tilt > 2 ? 'block-s5-right' : 'block-s5-level');
                } else if (blk.tilt_mode) {
                    const tm = String(blk.tilt_mode).toLowerCase();
                    effectiveClass = tm.includes('left') ? 'block-s5-left' : (tm.includes('right') ? 'block-s5-right' : 'block-s5-level');
                } else {
                    effectiveClass = 'block-s5-level';
                }
            } else if (channelKey === 's6_jaw' || channelKey === 'head_jaw') {
                const isSinging = (blk.jaw_mode === 'singing' || blk.is_vocal === true || blk.type === 'lyric');
                effectiveClass = isSinging ? 'block-jaw-singing' : 'block-jaw-closed';
            }
            const isUserEdited = !!blk.is_user_edited;

            html += `
                <div class="bb-move-block ${effectiveClass} ${isSel ? 'selected' : ''} ${isUserEdited ? 'user-edited' : ''}"
                     data-channel="${channelKey}" data-id="${blk.id}"
                     style="left: ${leftPx}px; width: ${widthPx}px;"
                     title="${label} [${st.toFixed(1)}s - ${et.toFixed(1)}s] ${isUserEdited ? '(Edited)' : ''}">
                    ${label}
                </div>
            `;
        });

        laneEl.innerHTML = html;
    }

    // Render all 6 lanes
    const tracks = activeChoreoData.tracks || {};
    renderLaneBlocks(document.getElementById('bbLaneLyrics'), tracks.lyrics || tracks.lyrics_phrasing, 'lyrics', 'block-lyric-female');
    renderLaneBlocks(document.getElementById('bbLaneBody'), tracks.spine_gaze || tracks.body_pose, 'spine_gaze', 'block-body');
    renderLaneBlocks(document.getElementById('bbLaneS8'), tracks.s8_gantry, 's8_gantry', 'block-s8');
    renderLaneBlocks(document.getElementById('bbLaneS7'), tracks.s7_pedestal, 's7_pedestal', 'block-s7');
    renderLaneBlocks(document.getElementById('bbLaneS1'), tracks.s1_torso, 's1_torso', 'block-s1');
    renderLaneBlocks(document.getElementById('bbLaneS5'), tracks.s5_head_tilt, 's5_head_tilt', 'block-s5');
    renderLaneBlocks(document.getElementById('bbLaneHeadJaw'), tracks.s6_jaw || tracks.head_jaw, 's6_jaw', 'block-head');

    // 3.5 Render Amplitude Visualizer Lane (Dark Blue Background, Cyan / Light Blue Ticks)
    const ampCanvas = document.getElementById('bbWaveformCanvas') || document.getElementById('bbAmpWaveformCanvas');
    if (ampCanvas) {
        const laneW = totalWidth - labelOffset;
        const laneH = 40;
        ampCanvas.width = laneW;
        ampCanvas.height = laneH;
        ampCanvas.style.left = '0px';
        ampCanvas.style.width = `${laneW}px`;
        ampCanvas.style.height = `${laneH}px`;

        const ctx = ampCanvas.getContext('2d');
        if (ctx) {
            ctx.clearRect(0, 0, laneW, laneH);

            const midY = laneH / 2;
            const maxH = laneH * 0.45;

            // Draw center baseline
            ctx.fillStyle = '#0f2744';
            ctx.fillRect(0, midY - 0.5, laneW, 1);

            const ampEnv = activeChoreoData.amplitude_envelope_50hz;
            const drops = activeChoreoData.drops;

            if (Array.isArray(ampEnv) && ampEnv.length > 0) {
                const totalSamples = ampEnv.length;
                const fps = 50.0;

                for (let x = 0; x < laneW; x += 3) {
                    const timeAtX = x / pps;
                    const sampleIdx = Math.floor(timeAtX * fps);
                    if (sampleIdx < totalSamples) {
                        let rawVal = ampEnv[sampleIdx];
                        if (rawVal > 1.0) rawVal = rawVal / 45.0;
                        const amp = Math.max(0.06, Math.min(1.0, rawVal));
                        const barH = amp * maxH;
                        ctx.fillStyle = '#38bdf8';
                        ctx.fillRect(x, midY - barH, 2, barH * 2);
                    }
                }
            }
            if (Array.isArray(drops)) {
                drops.forEach(d => {
                    const dropSec = Number(d.drop_sec || 0);
                    const dropX = dropSec * pps;

                    // Red drop marker line
                    ctx.fillStyle = 'rgba(239, 68, 68, 0.9)';
                    ctx.fillRect(dropX - 1, 0, 2, laneH);

                    // Small drop badge
                    ctx.fillStyle = '#ef4444';
                    ctx.beginPath();
                    ctx.moveTo(dropX - 4, 0);
                    ctx.lineTo(dropX + 4, 0);
                    ctx.lineTo(dropX, 6);
                    ctx.fill();
                });
            }
        }
    }

    // 3.6 Render Vocal Energy Visualizer Lane (Dark Magenta Background, Pink/Rose Ticks)
    const vocalCanvas = document.getElementById('bbVocalWaveformCanvas');
    if (vocalCanvas) {
        const laneW = totalWidth - labelOffset;
        const laneH = 40;
        vocalCanvas.width = laneW;
        vocalCanvas.height = laneH;
        vocalCanvas.style.left = '0px';
        vocalCanvas.style.width = `${laneW}px`;
        vocalCanvas.style.height = `${laneH}px`;

        const ctx = vocalCanvas.getContext('2d');
        if (ctx) {
            ctx.clearRect(0, 0, laneW, laneH);

            const midY = laneH / 2;
            const maxH = laneH * 0.45;

            // Draw center baseline
            ctx.fillStyle = '#380e45';
            ctx.fillRect(0, midY - 0.5, laneW, 1);

            const vocalEnv = activeChoreoData.mouth_envelope_50hz;

            if (Array.isArray(vocalEnv) && vocalEnv.length > 0) {
                const totalSamples = vocalEnv.length;
                const fps = 50.0;

                for (let x = 0; x < laneW; x += 3) {
                    const timeAtX = x / pps;
                    const sampleIdx = Math.floor(timeAtX * fps);
                    if (sampleIdx < totalSamples) {
                        let rawVal = vocalEnv[sampleIdx];
                        if (rawVal > 1.0) rawVal = rawVal / 45.0;
                        const amp = Math.max(0.03, Math.min(1.0, rawVal));
                        const barH = amp * maxH;
                        ctx.fillStyle = '#ec4899';
                        ctx.fillRect(x, midY - barH, 2, barH * 2);
                    }
                }
            }
        }
    }

    // 4. In / Out Markers & Shaded Range Highlight
    const inMarkerEl = document.getElementById('bbInMarker');
    const outMarkerEl = document.getElementById('bbOutMarker');
    const highlightEl = document.getElementById('bbSectionHighlight');

    if (inMarkerEl) {
        if (timelineInTime !== null) {
            inMarkerEl.style.display = 'block';
            inMarkerEl.style.left = `${labelOffset + (timelineInTime * pps)}px`;
        } else {
            inMarkerEl.style.display = 'none';
        }
    }

    if (outMarkerEl) {
        if (timelineOutTime !== null) {
            outMarkerEl.style.display = 'block';
            outMarkerEl.style.left = `${labelOffset + (timelineOutTime * pps)}px`;
        } else {
            outMarkerEl.style.display = 'none';
        }
    }

    if (highlightEl) {
        if (timelineInTime !== null && timelineOutTime !== null && timelineOutTime > timelineInTime) {
            highlightEl.style.display = 'block';
            const hLeft = labelOffset + (timelineInTime * pps);
            const hWidth = (timelineOutTime - timelineInTime) * pps;
            highlightEl.style.left = `${hLeft}px`;
            highlightEl.style.width = `${hWidth}px`;
        } else {
            highlightEl.style.display = 'none';
        }
    }

    // 5. Update Range Readout Badge & Transport Button Labels
    const rangeDisplay = document.getElementById('bbTimelineRangeDisplay');
    const playBtn = document.getElementById('bbPlaySectionBtn');
    const loopBtn = document.getElementById('bbLoopSectionBtn');

    if (rangeDisplay) {
        const inStr = (timelineInTime !== null) ? `${timelineInTime.toFixed(1)}s` : '--';
        const outStr = (timelineOutTime !== null) ? `${timelineOutTime.toFixed(1)}s` : '--';
        let diffStr = '';
        if (timelineInTime !== null && timelineOutTime !== null && timelineOutTime > timelineInTime) {
            diffStr = ` (${(timelineOutTime - timelineInTime).toFixed(1)}s)`;
        }
        rangeDisplay.innerText = `IN: ${inStr} | OUT: ${outStr}${diffStr}`;
    }

    if (playBtn) {
        if (timelineInTime !== null && timelineOutTime !== null && timelineOutTime > timelineInTime) {
            playBtn.innerText = `▶️ PLAY (${(timelineOutTime - timelineInTime).toFixed(1)}s)`;
        } else if (timelineInTime !== null) {
            playBtn.innerText = `▶️ PLAY FROM ${timelineInTime.toFixed(1)}s`;
        } else {
            playBtn.innerText = `▶️ PLAY`;
        }
    }

    if (loopBtn) {
        loopBtn.classList.toggle('active', !!timelineLoopEnabled);
    }

    // 6. Update Playhead Scrubber Position
    updateTimelinePlayhead(timelinePlayheadTime);
}

export function updateTimelinePlayhead(timeSec = timelinePlayheadTime) {
    const pps = timelinePixelsPerSec;
    const labelOffset = 100;
    const playhead = document.getElementById('bbPlayheadLine');
    if (playhead) {
        const phLeft = labelOffset + (timeSec * pps);
        playhead.style.left = `${phLeft}px`;
    }

    const timeDisplay = document.getElementById('bbTimelineTimeDisplay');
    if (timeDisplay) {
        const mins = Math.floor(timeSec / 60);
        const secs = (timeSec % 60).toFixed(1).padStart(4, '0');
        const beatTimes = (activeChoreoData && activeChoreoData.beat_times) || [];
        let currBeat = 0;
        for (let i = 0; i < beatTimes.length; i++) {
            if (beatTimes[i] <= timeSec) currBeat = i + 1;
            else break;
        }
        timeDisplay.innerText = `⏱️ ${mins}:${secs} (B ${currBeat}/${beatTimes.length || '--'})`;
    }
}

export function openMoveInspector(channel, block) {
    setSelectedMoveChannel(channel);
    setSelectedMoveBlock(block);

    const drawer = document.getElementById('bbInspectorDrawer');
    if (!drawer) return;
    drawer.style.display = 'flex';

    const typeBadge = document.getElementById('bbInspectorTypeBadge');
    const nameInp = document.getElementById('bbInspectorNameInput');
    const dynamicCtrls = document.getElementById('bbInspectorDynamicControls');

    const channelNames = {
        'lyrics': 'LYRICS',
        'lyrics_phrasing': 'LYRICS',
        'spine_gaze': 'SPINE (S2-4)',
        'body_pose': 'SPINE (S2-4)',
        's8_gantry': 'GANTRY (S8)',
        's7_pedestal': 'PEDESTAL (S7)',
        's1_torso': 'GROOVE (S1)',
        's5_head_tilt': 'HEAD TILT (S5)',
        's6_jaw': 'LIP-SYNC JAW (S6)',
        'head_jaw': 'LIP-SYNC JAW (S6)'
    };

    if (typeBadge) typeBadge.innerText = channelNames[channel] || channel.toUpperCase();
    if (nameInp) nameInp.value = block.name || '';

    const st = Number(block.start_sec || 0).toFixed(1);
    const et = Number(block.end_sec || 0).toFixed(1);
    const dur = Math.max(0.1, et - st).toFixed(1);

    let controlsHtml = `
        <!-- Left: Time & Nudge Bar -->
        <div style="display: flex; flex-direction: column; gap: 4px;">
            <div style="display: flex; align-items: center; gap: 6px;">
                <span style="font-size: 10px; color: #888; font-weight: 700;">START:</span>
                <input type="number" id="inspStartSec" step="0.1" value="${st}" style="width: 55px; background: #1a1a26; border: 1px solid #444; color: #fff; font-size: 11px; font-family: monospace; padding: 2px 4px; border-radius: 4px;">
                <span style="font-size: 10px; color: #888; font-weight: 700;">END:</span>
                <input type="number" id="inspEndSec" step="0.1" value="${et}" style="width: 55px; background: #1a1a26; border: 1px solid #444; color: #fff; font-size: 11px; font-family: monospace; padding: 2px 4px; border-radius: 4px;">
                <span style="font-size: 10px; color: #a855f7; font-weight: 800;">(${dur}s)</span>
            </div>
            <div style="display: flex; gap: 3px;">
                <button class="btn-action insp-nudge-btn" data-nudge="-1.0" style="padding: 1px 5px; font-size: 9px; height: 18px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">-1s</button>
                <button class="btn-action insp-nudge-btn" data-nudge="-0.1" style="padding: 1px 5px; font-size: 9px; height: 18px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">-0.1s</button>
                <button class="btn-action insp-nudge-btn" data-nudge="+0.1" style="padding: 1px 5px; font-size: 9px; height: 18px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">+0.1s</button>
                <button class="btn-action insp-nudge-btn" data-nudge="+1.0" style="padding: 1px 5px; font-size: 9px; height: 18px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">+1s</button>
                <button id="inspSnapBeatBtn" class="btn-action" style="padding: 1px 6px; font-size: 9px; font-weight: 800; height: 18px; min-height: 0; background: #2e1065; border: 1px solid #a855f7; color: #e9d5ff; border-radius: 3px;">SNAP BEAT</button>
            </div>
            <div style="display: flex; align-items: center; gap: 8px; margin-top: 2px;">
                ${(channel === 'lyrics' || channel === 'lyrics_phrasing') ? `
                <label style="display: flex; align-items: center; gap: 4px; font-size: 9px; color: #ec4899; font-weight: 700; cursor: pointer;" title="Automatically synchronize start/end times across all joint tracks (Spine, Rail, Pedestal, Torso, Tilt, Jaw)">
                    <input type="checkbox" id="inspCascadeAllTracks" checked style="cursor: pointer;">
                    🔗 CASCADE ALL TRACKS
                </label>
                ` : `
                <label style="display: flex; align-items: center; gap: 4px; font-size: 9px; color: #38bdf8; font-weight: 700; cursor: pointer;">
                    <input type="checkbox" id="inspUserOverride" ${block.user_override ? 'checked' : ''} style="cursor: pointer;">
                    OVERRIDE
                </label>
                <div style="display: flex; align-items: center; gap: 3px; background: #1a1500; border: 1px solid #78350f; padding: 1px 4px; border-radius: 4px;">
                    <label style="display: flex; align-items: center; gap: 3px; font-size: 9px; color: #f59e0b; font-weight: 700; cursor: pointer;">
                        <input type="checkbox" id="inspBounceEnabled" ${(block.bounce_modifier && block.bounce_modifier.enabled !== false) ? 'checked' : ''} style="cursor: pointer;">
                        BOUNCE
                    </label>
                    <button id="inspBounceDownBtn" class="btn-action" style="padding: 0 4px; font-size: 8px; height: 16px; min-height: 0; background: #291b00; border: 1px solid #d97706; border-radius: 2px; color: #fbbf24; cursor: pointer;" title="Decrease bounce intensity by 1%">▼</button>
                    <span id="inspBounceIntensityVal" style="font-size: 9px; font-family: monospace; font-weight: 800; color: #fbbf24; min-width: 22px; text-align: center;">${(block.bounce_modifier && block.bounce_modifier.intensity !== undefined) ? Math.round(Number(block.bounce_modifier.intensity) * 100) + '%' : '--'}</span>
                    <button id="inspBounceUpBtn" class="btn-action" style="padding: 0 4px; font-size: 8px; height: 16px; min-height: 0; background: #291b00; border: 1px solid #d97706; border-radius: 2px; color: #fbbf24; cursor: pointer;" title="Increase bounce intensity by 1%">▲</button>
                </div>
                `}
            </div>
        </div>
    `;

    // Right: Channel-Specific Parameters
    if (channel === 'spine_gaze' || channel === 'body_pose') {
        const poses = activeChoreoData.poses || {};
        const poseKeys = Object.keys(poses);
        let poseOpts = '';
        poseKeys.forEach(pk => {
            const sel = (block.pose_name === pk) ? 'selected' : '';
            poseOpts += `<option value="${pk}" ${sel}>${pk.toUpperCase()}</option>`;
        });

        const transSec = Number(block.transition_sec !== undefined ? block.transition_sec : 0.5);
        const pitch = block.head_pitch || 'level';

        controlsHtml += `
            <div style="display: flex; gap: 12px; align-items: center;">
                <div style="display: flex; flex-direction: column; gap: 2px;">
                    <span style="font-size: 9px; color: #aaa; font-weight: 700;">STANCE:</span>
                    <select id="inspBasePose" style="background: #1a1a26; border: 1px solid #60a5fa; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px;">
                        ${poseOpts}
                    </select>
                </div>
                <div style="display: flex; flex-direction: column; gap: 2px;">
                    <span style="font-size: 9px; color: #aaa; font-weight: 700;">HEAD PITCH:</span>
                    <select id="inspHeadPitch" style="background: #1a1a26; border: 1px solid #a855f7; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px;">
                        <option value="level" ${pitch === 'level' ? 'selected' : ''}>Level (Audience)</option>
                        <option value="up" ${pitch === 'up' ? 'selected' : ''}>Up (Power Belt)</option>
                        <option value="down" ${pitch === 'down' ? 'selected' : ''}>Down (Introspective)</option>
                    </select>
                </div>
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 9px; color: #aaa;">
                        <span>TRANSITION:</span><span id="inspTransVal" style="color: #00e5ff;">${transSec.toFixed(1)}s</span>
                    </div>
                    <input type="range" id="inspTransSlider" min="0.1" max="2.0" step="0.1" value="${transSec}">
                </div>
            </div>
        `;
    } else if (channel === 's8_gantry') {
        const pos = Number(block.target_pos);
        const spd = Number(block.speed);
        const mode = block.mode;
        controlsHtml += `
            <div style="display: flex; gap: 8px; align-items: center;">
                <div style="display: flex; flex-direction: column; gap: 2px;">
                    <span style="font-size: 9px; color: #aaa; font-weight: 700;">MODE:</span>
                    <select id="inspGantryMode" style="background: #1a1a26; border: 1px solid #60a5fa; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px;">
                        <option value="hold" ${mode === 'hold' ? 'selected' : ''}>Hold</option>
                        <option value="full_glide" ${mode === 'full_glide' ? 'selected' : ''}>Full Glide</option>
                        <option value="late_move" ${mode === 'late_move' ? 'selected' : ''}>Late Move</option>
                        <option value="early_settle" ${mode === 'early_settle' ? 'selected' : ''}>Early Settle</option>
                    </select>
                </div>
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: #ccc;">
                        <span>POSITION:</span><strong id="inspS8Val" style="color: #00e5ff;">${pos}</strong>
                    </div>
                    <input type="range" id="inspS8Slider" min="3" max="4800" step="50" value="${pos}">
                </div>
                <div style="display: flex; gap: 2px;">
                    <button class="btn-action insp-s8-preset" data-pos="1100" style="padding: 2px 4px; font-size: 8.5px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">Right</button>
                    <button class="btn-action insp-s8-preset" data-pos="2400" style="padding: 2px 4px; font-size: 8.5px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">Center</button>
                    <button class="btn-action insp-s8-preset" data-pos="3700" style="padding: 2px 4px; font-size: 8.5px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">Left</button>
                    <button class="btn-action insp-s8-preset" data-pos="4350" style="padding: 2px 4px; font-size: 8.5px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">Drop</button>
                </div>
            </div>
        `;
    } else if (channel === 's7_pedestal') {
        const pctVal = Number(block.target_pct);
        const pct = Math.max(0, Math.min(100, pctVal));
        const dispPct = Number.isFinite(pctVal) ? `${pct.toFixed(0)}%` : '--';
        controlsHtml += `
            <div style="display: flex; gap: 8px; align-items: center;">
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: #ccc;">
                        <span>STAGE FACING:</span><strong id="inspS7Val" style="color: #00ff66;">${dispPct}</strong>
                    </div>
                    <input type="range" id="inspS7Slider" min="0" max="100" step="1" value="${pct}">
                </div>
                <div style="display: flex; gap: 3px;">
                    <button class="btn-action insp-s7-preset" data-pct="0" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">0% Right</button>
                    <button class="btn-action insp-s7-preset" data-pct="50" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">50% Center</button>
                    <button class="btn-action insp-s7-preset" data-pct="100" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">100% Left</button>
                </div>
            </div>
        `;
    } else if (channel === 's1_torso') {
        const groovePct = Math.round(Number(block.groove_intensity !== undefined ? block.groove_intensity : 0.5) * 100);
        controlsHtml += `
            <div style="display: flex; gap: 12px; align-items: center; flex: 1;">
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: #ccc;">
                        <span>GROOVE MODIFIER INTENSITY:</span><strong id="inspGrooveVal" style="color: #fbbf24;">${groovePct}%</strong>
                    </div>
                    <input type="range" id="inspGrooveSlider" min="0" max="100" step="5" value="${groovePct}">
                </div>
                <div style="display: flex; gap: 3px;">
                    <button class="btn-action insp-groove-preset" data-val="0" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">0% Still</button>
                    <button class="btn-action insp-groove-preset" data-val="50" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">50% Verse</button>
                    <button class="btn-action insp-groove-preset" data-val="100" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">100% Dance</button>
                </div>
            </div>
        `;
    } else if (channel === 's5_head_tilt') {
        const tilt = Number(block.tilt_deg || 0);
        controlsHtml += `
            <div style="display: flex; gap: 12px; align-items: center; flex: 1;">
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: #ccc;">
                        <span>HEAD TILT ROLL:</span><strong id="inspTiltVal" style="color: #2dd4bf;">${tilt > 0 ? '+' : ''}${tilt}°</strong>
                    </div>
                    <input type="range" id="inspTiltSlider" min="-25" max="25" step="1" value="${tilt}">
                </div>
                <div style="display: flex; gap: 3px;">
                    <button class="btn-action insp-tilt-preset" data-deg="-12" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">-12° Left</button>
                    <button class="btn-action insp-tilt-preset" data-deg="0" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">0° Level</button>
                    <button class="btn-action insp-tilt-preset" data-deg="12" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">+12° Right</button>
                </div>
            </div>
        `;
    } else if (channel === 's6_jaw' || channel === 'head_jaw') {
        controlsHtml += `
            <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
                <span style="font-size: 11px; color: #f472b6; font-weight: 700;">50 Hz MMDenseLSTM Neural Lip-Sync Active</span>
                <span style="font-size: 10px; color: #aaa;">(Automatically opens jaw 0-45% matching vocal power)</span>
            </div>
        `;
    } else if (channel === 'lyrics' || channel === 'lyrics_phrasing') {
        const lyricText = block.text || '';
        const isBreath = (block.type === 'breath');
        const origText = block.original_asr_text || lyricText;
        controlsHtml += `
            <div style="display: flex; gap: 8px; align-items: center; flex: 1;">
                <div style="display: flex; flex-direction: column; gap: 2px;">
                    <span style="font-size: 9px; color: #aaa; font-weight: 700;">TYPE:</span>
                    <select id="inspLyricType" style="background: #1a1a26; border: 1px solid #ec4899; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px;">
                        <option value="lyric" ${!isBreath ? 'selected' : ''}>🎤 Lyric</option>
                        <option value="breath" ${isBreath ? 'selected' : ''}>💨 Breath (Grey)</option>
                    </select>
                </div>
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 9px; color: #aaa; font-weight: 700;">LYRIC TEXT:</span>
                        <span class="insp-original-ref-badge" title="Original ASR: ${origText.replace(/"/g, '&quot;')}">ORIG: "${origText.replace(/"/g, '&quot;')}"</span>
                    </div>
                    <input type="text" id="inspLyricTextInput" value="${lyricText.replace(/"/g, '&quot;')}" placeholder="Enter lyric text..." style="background: #1a1a26; border: 1px solid #60a5fa; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px; width: 100%; box-sizing: border-box;">
                </div>
            </div>
        `;
    }

    if (dynamicCtrls) dynamicCtrls.innerHTML = controlsHtml;
    renderTimeline();
}

export function closeMoveInspector() {
    setSelectedMoveBlock(null);
    const drawer = document.getElementById('bbInspectorDrawer');
    if (drawer) drawer.style.display = 'none';
    renderTimeline();
}

export function renderPosesList() {
    if (!activeChoreoData) return;
    const poses = activeChoreoData.poses || {};
    const container = document.getElementById('bbPosesListContainer');
    if (!container) return;

    let html = '';
    Object.keys(poses).forEach(k => {
        const isSel = (k === selectedPoseName);
        const bg = isSel ? 'linear-gradient(135deg, #4c1d95, #6d28d9)' : '#161622';
        const border = isSel ? '2px solid #a855f7' : '1.5px solid #2a2a3a';
        html += `
            <div class="bb-pose-item" data-pose="${k}" style="background: ${bg}; border: ${border}; border-radius: 6px; padding: 6px 10px; cursor: pointer; display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 13px; font-weight: 800; color: #fff;">${k.toUpperCase()}</span>
                <span style="font-size: 9px; color: ${isSel ? '#a7f3d0' : '#888'}; font-weight: 700;">${isSel ? 'ACTIVE' : 'SELECT'}</span>
            </div>
        `;
    });
    container.innerHTML = html;

    const currPose = poses[selectedPoseName] || poses['stand'] || {};
    updatePoseSliders(currPose);
}

export function updatePoseSliders(poseDict) {
    if (!poseDict) return;
    const nameDisplay = document.getElementById('bbCurrentPoseNameDisplay');
    if (nameDisplay) nameDisplay.innerText = selectedPoseName.toUpperCase();

    const rawPan = Number(poseDict.shoulder_pan);
    const rawLift = Number(poseDict.shoulder_lift);
    const rawElbow = Number(poseDict.elbow_flex);
    const rawWristF = Number(poseDict.wrist_flex);
    const rawWristR = Number(poseDict.wrist_roll);

    const uiPan = Math.max(0, Math.min(100, rawPan));
    const uiLift = Math.max(0, Math.min(100, rawLift));
    const uiElbow = Math.max(0, Math.min(100, rawElbow));
    const uiWristF = Math.max(0, Math.min(100, rawWristF));
    const uiWristR = Math.max(0, Math.min(100, rawWristR));

    const sPan = document.getElementById('bbSliderPan');
    const sLift = document.getElementById('bbSliderLift');
    const sElbow = document.getElementById('bbSliderElbow');
    const sWristF = document.getElementById('bbSliderWristFlex');
    const sWristR = document.getElementById('bbSliderWristRoll');

    if (sPan) sPan.value = uiPan;
    if (sLift) sLift.value = uiLift;
    if (sElbow) sElbow.value = uiElbow;
    if (sWristF) sWristF.value = uiWristF;
    if (sWristR) sWristR.value = uiWristR;

    const vPan = document.getElementById('bbValPan');
    const vLift = document.getElementById('bbValLift');
    const vElbow = document.getElementById('bbValElbow');
    const vWristF = document.getElementById('bbValWristFlex');
    const vWristR = document.getElementById('bbValWristRoll');

    if (vPan) vPan.innerText = `${uiPan.toFixed(1)}%`;
    if (vLift) vLift.innerText = `${uiLift.toFixed(1)}%`;
    if (vElbow) vElbow.innerText = `${uiElbow.toFixed(1)}%`;
    if (vWristF) vWristF.innerText = `${uiWristF.toFixed(1)}%`;
    if (vWristR) vWristR.innerText = `${uiWristR.toFixed(1)}%`;

    setCurrentCustomPoseJoints({
        shoulder_pan: uiPan,
        shoulder_lift: uiLift,
        elbow_flex: uiElbow,
        wrist_flex: uiWristF,
        wrist_roll: uiWristR
    });
}

export function renderSettingsView() {
    // 1. Audio Kinematics & Reactivity
    if (activeChoreoData) {
        const s = activeChoreoData.settings || {};
        const jawGate = s.jaw_gate_threshold !== undefined ? s.jaw_gate_threshold : 0.18;
        const jawMax = s.jaw_max_open !== undefined ? s.jaw_max_open : 45.0;
        const nodDepth = s.head_nod_depth !== undefined ? s.head_nod_depth : 6.0;
        const vibrato = s.vibrato_amplitude !== undefined ? s.vibrato_amplitude : 20.0;
        const gantrySpd = s.gantry_default_speed !== undefined ? s.gantry_default_speed : 800;
        const agility = (s.joint_alphas && s.joint_alphas.wrist_flex) ? s.joint_alphas.wrist_flex : 0.35;

        const elGate = document.getElementById('bbSliderJawGate');
        const elMax = document.getElementById('bbSliderJawMax');
        const elNod = document.getElementById('bbSliderNodDepth');
        const elVib = document.getElementById('bbSliderVibrato');
        const elGSpd = document.getElementById('bbSliderGantrySpeed');
        const elAgil = document.getElementById('bbSliderAgility');

        if (elGate) elGate.value = jawGate;
        if (elMax) elMax.value = jawMax;
        if (elNod) elNod.value = nodDepth;
        if (elVib) elVib.value = vibrato;
        if (elGSpd) elGSpd.value = gantrySpd;
        if (elAgil) elAgil.value = agility;

        const vGate = document.getElementById('bbValJawGate');
        const vMax = document.getElementById('bbValJawMax');
        const vNod = document.getElementById('bbValNodDepth');
        const vVib = document.getElementById('bbValVibrato');
        const vGSpd = document.getElementById('bbValGantrySpeed');
        const vAgil = document.getElementById('bbValAgility');

        if (vGate) vGate.innerText = Number(jawGate).toFixed(2);
        if (vMax) vMax.innerText = `${Math.round(jawMax)}%`;
        if (vNod) vNod.innerText = `${Number(nodDepth).toFixed(1)}°`;
        if (vVib) vVib.innerText = `${Number(vibrato).toFixed(1)}°`;
        if (vGSpd) vGSpd.innerText = `${gantrySpd}`;
        if (vAgil) vAgil.innerText = `${Number(agility).toFixed(2)}`;
    }

    // 2. Compiler Probabilities & Kinematic Bounds
    const p = activeProbabilitiesData;
    if (p) {
        // Section 1: Pedestal & Torso
        const pedShiftP = Math.round(Number(p.pedestal_s7.vocal_start_shift_probability) * 100);
        const torsoCounterP = Math.round(Number(p.torso_s1.audience_counter_probability) * 100);
        const pedLeftRom = Number(p.pedestal_s7.target_rom.shift_left);
        const pedRightRom = Number(p.pedestal_s7.target_rom.shift_right);

        const elPedShift = document.getElementById('bbSliderPedShiftProb');
        const elTorso = document.getElementById('bbSliderTorsoCounterProb');
        const elPedLeft = document.getElementById('bbSliderPedLeftRom');
        const elPedRight = document.getElementById('bbSliderPedRightRom');

        if (elPedShift) elPedShift.value = pedShiftP;
        if (elTorso) elTorso.value = torsoCounterP;
        if (elPedLeft) elPedLeft.value = pedLeftRom;
        if (elPedRight) elPedRight.value = pedRightRom;

        const vPedShift = document.getElementById('bbValPedShiftProb');
        const vTorso = document.getElementById('bbValTorsoCounterProb');
        const vPedLeft = document.getElementById('bbValPedLeftRom');
        const vPedRight = document.getElementById('bbValPedRightRom');

        if (vPedShift) vPedShift.innerText = `${pedShiftP}%`;
        if (vTorso) vTorso.innerText = `${torsoCounterP}%`;
        if (vPedLeft) vPedLeft.innerText = `${Number(pedLeftRom).toFixed(1)}%`;
        if (vPedRight) vPedRight.innerText = `${Number(pedRightRom).toFixed(1)}%`;

        // Section 2: Gantry & Head Tilt
        const ganP = (p.gantry_s8 && p.gantry_s8.non_drop_move_probability !== undefined) ? Math.round(p.gantry_s8.non_drop_move_probability * 100) : 65;
        const ganDropSpd = (p.gantry_s8 && p.gantry_s8.speeds && p.gantry_s8.speeds.drop_glide !== undefined) ? p.gantry_s8.speeds.drop_glide : 700;
        const tiltCenterP = (p.head_tilt_s5 && p.head_tilt_s5.center_probability !== undefined) ? Math.round(p.head_tilt_s5.center_probability * 100) : 70;
        const tiltSnapP = (p.head_tilt_s5 && p.head_tilt_s5.snap_pulse_probability !== undefined) ? Math.round(p.head_tilt_s5.snap_pulse_probability * 100) : 20;
        const tiltLeftRom = (p.head_tilt_s5 && p.head_tilt_s5.snap_pulse_left_rom !== undefined) ? p.head_tilt_s5.snap_pulse_left_rom : (p.head_tilt_s5 && p.head_tilt_s5.tilt_left_rom !== undefined ? p.head_tilt_s5.tilt_left_rom : 42.0);
        const tiltDelta = Math.round(50 - tiltLeftRom);
        const rollSweep = (p.head_tilt_s5 && p.head_tilt_s5.continuous_roll_amplitude_rom !== undefined) ? p.head_tilt_s5.continuous_roll_amplitude_rom : 8.0;

        const elGanP = document.getElementById('bbSliderGantryProb');
        const elGanDropSpd = document.getElementById('bbSliderGantryDropSpd');
        const elTiltCenter = document.getElementById('bbSliderHeadTiltCenterProb');
        const elTiltSnap = document.getElementById('bbSliderHeadTiltSnapProb');
        const elTiltRom = document.getElementById('bbSliderHeadTiltRom');
        const elRollSweep = document.getElementById('bbSliderHeadRollSweep');

        if (elGanP) elGanP.value = ganP;
        if (elGanDropSpd) elGanDropSpd.value = ganDropSpd;
        if (elTiltCenter) elTiltCenter.value = tiltCenterP;
        if (elTiltSnap) elTiltSnap.value = tiltSnapP;
        if (elTiltRom) elTiltRom.value = tiltDelta;
        if (elRollSweep) elRollSweep.value = rollSweep;

        const vGanP = document.getElementById('bbValGantryProb');
        const vGanDropSpd = document.getElementById('bbValGantryDropSpd');
        const vTiltCenter = document.getElementById('bbValHeadTiltCenterProb');
        const vTiltSnap = document.getElementById('bbValHeadTiltSnapProb');
        const vTiltRom = document.getElementById('bbValHeadTiltRom');
        const vRollSweep = document.getElementById('bbValHeadRollSweep');

        if (vGanP) vGanP.innerText = `${ganP}%`;
        if (vGanDropSpd) vGanDropSpd.innerText = `${ganDropSpd}`;
        if (vTiltCenter) vTiltCenter.innerText = `${tiltCenterP}%`;
        if (vTiltSnap) vTiltSnap.innerText = `${tiltSnapP}%`;
        if (vTiltRom) vTiltRom.innerText = `${50 - tiltDelta}% / ${50 + tiltDelta}%`;
        if (vRollSweep) vRollSweep.innerText = `${Number(rollSweep).toFixed(1)}%`;

        // Section 3: Climax Posture & Phrasing
        const maxArches = (p.spine_gaze && p.spine_gaze.max_climax_arches !== undefined) ? p.spine_gaze.max_climax_arches : 2;
        const minSep = (p.spine_gaze && p.spine_gaze.min_separation_bars !== undefined) ? p.spine_gaze.min_separation_bars : 4;

        const elMaxArches = document.getElementById('bbSliderMaxArches');
        const elMinSep = document.getElementById('bbSliderMinSeparation');

        if (elMaxArches) elMaxArches.value = maxArches;
        if (elMinSep) elMinSep.value = minSep;

        const vMaxArches = document.getElementById('bbValMaxArches');
        const vMinSep = document.getElementById('bbValMinSeparation');

        if (vMaxArches) vMaxArches.innerText = `${maxArches}`;
        if (vMinSep) vMinSep.innerText = `${minSep} Bars`;
    }
}

export function openDirectorModal() {
    const modal = document.getElementById('bbDirectorModal');
    if (modal) modal.style.display = 'flex';
}

export function closeDirectorModal() {
    const modal = document.getElementById('bbDirectorModal');
    if (modal) modal.style.display = 'none';
}

export function renderDirectorLoading(text = 'Querying Ornith 35B on LM Studio...') {
    const loadingView = document.getElementById('bbDirectorLoadingView');
    const briefView = document.getElementById('bbDirectorBriefView');
    const loadingText = document.getElementById('bbDirectorLoadingText');
    const genBtn = document.getElementById('bbDirectorGenerateBtn');
    const acceptBtn = document.getElementById('bbDirectorAcceptBtn');

    if (loadingView) loadingView.style.display = 'flex';
    if (briefView) briefView.style.display = 'none';
    if (loadingText) loadingText.innerText = text;
    if (genBtn) genBtn.disabled = true;
    if (acceptBtn) acceptBtn.disabled = true;
}

export function renderDirectorBrief(briefData, trackTitle = 'Current Track', trackMeta = '') {
    const loadingView = document.getElementById('bbDirectorLoadingView');
    const briefView = document.getElementById('bbDirectorBriefView');
    const titleEl = document.getElementById('bbDirectorSongTitle');
    const metaEl = document.getElementById('bbDirectorSongMeta');
    const climaxList = document.getElementById('bbDirectorClimaxList');
    const genBtn = document.getElementById('bbDirectorGenerateBtn');
    const acceptBtn = document.getElementById('bbDirectorAcceptBtn');

    if (loadingView) loadingView.style.display = 'none';
    if (briefView) briefView.style.display = 'flex';
    if (titleEl) titleEl.innerText = trackTitle;
    if (metaEl) metaEl.innerText = trackMeta;
    if (genBtn) genBtn.disabled = false;
    if (acceptBtn) acceptBtn.disabled = false;

    if (climaxList && briefData) {
        const climaxes = briefData.climax_candidates || [];
        let html = '';
        if (climaxes.length === 0) {
            html = '<span style="font-size: 11px; color: #888;">No distinct climax candidates identified.</span>';
        } else {
            climaxes.forEach((c, idx) => {
                const mins = Math.floor((c.start_sec || 0) / 60);
                const secs = ((c.start_sec || 0) % 60).toFixed(0).padStart(2, '0');
                const timeStr = `${mins}:${secs} (${c.start_sec}s - ${c.end_sec}s)`;
                const isMax = (c.energy >= 9.5);
                html += `
                    <div style="background: ${isMax ? '#451a03' : '#1e1b4b'}; border: 1px solid ${isMax ? '#f97316' : '#6366f1'}; border-radius: 4px; padding: 4px 8px; display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <span style="font-size: 12px;">${isMax ? '🔥' : '✨'}</span>
                            <div>
                                <strong style="font-size: 11px; color: #fff;">${c.name || 'Climax Candidate'}</strong>
                                <span style="font-size: 9.5px; color: ${isMax ? '#fdba74' : '#a5b4fc'}; margin-left: 4px;">⏱️ ${timeStr} • ${c.description || c.type || ''}</span>
                            </div>
                        </div>
                        <span style="font-size: 10px; font-weight: 800; color: ${isMax ? '#ffaa00' : '#38bdf8'}; font-family: monospace;">E: ${c.energy || '--'}/10</span>
                    </div>
                `;
            });
        }
        climaxList.innerHTML = html;
    }
}

export function renderListenerTracks(query, tracks, selectedIndex, stateStr, transcriptStr, actionStr) {
    const transcriptEl = document.getElementById('listenerTranscriptDisplay');
    if (transcriptEl) {
        if (typeof transcriptStr === 'string' && transcriptStr.trim().length > 0 && transcriptStr !== '(none)') {
            transcriptEl.innerText = `"${transcriptStr}"`;
            transcriptEl.style.color = '#ffffff';
        } else {
            transcriptEl.innerText = '(none)';
            transcriptEl.style.color = '#888888';
        }
    }

    const actionEl = document.getElementById('listenerActionDisplay');
    if (actionEl) {
        const act = (typeof actionStr === 'string' && actionStr.trim().length > 0) ? actionStr : 'Awaiting voice command';
        actionEl.innerText = act;
        if (act === 'No action taken') {
            actionEl.className = 'action-badge badge-unmatched';
        } else if (act === 'Awaiting voice command') {
            actionEl.className = 'action-badge badge-idle';
        } else {
            actionEl.className = 'action-badge badge-success';
        }
    }

    const queryEl = document.getElementById('listenerQueryDisplay');
    if (queryEl) {
        if (typeof query === 'string' && query.length > 0) {
            queryEl.innerText = `"${query}"`;
        } else {
            queryEl.innerText = '(speak "download [song] by [artist]")';
        }
    }

    const stateEl = document.getElementById('listenerStateText');
    const pillEl = document.getElementById('listenerStatusPill');
    if (stateEl && typeof stateStr === 'string') {
        stateEl.innerText = stateStr;
    }
    if (pillEl && typeof stateStr === 'string') {
        if (stateStr === 'SELECTING') {
            pillEl.style.borderColor = '#00ff66';
            pillEl.style.color = '#00ff66';
            pillEl.style.background = 'rgba(0, 255, 102, 0.15)';
        } else if (stateStr === 'ANALYZING') {
            pillEl.style.borderColor = '#d533ff';
            pillEl.style.color = '#f2a8ff';
            pillEl.style.background = 'rgba(213, 51, 255, 0.25)';
        } else if (stateStr === 'ERROR') {
            pillEl.style.borderColor = '#ff3344';
            pillEl.style.color = '#ff3344';
            pillEl.style.background = 'rgba(255, 51, 68, 0.15)';
        } else {
            pillEl.style.borderColor = '#00f2fe';
            pillEl.style.color = '#9dfbfa';
            pillEl.style.background = '#091a1c';
        }
    }

    const macBtn = document.getElementById('listenerAnalyzeMacBtn');
    if (macBtn) {
        if (stateStr === 'SELECTING' && Array.isArray(tracks) && tracks.length > 0) {
            macBtn.style.display = 'flex';
            macBtn.disabled = false;
            macBtn.innerText = '⚡ ANALYZE ON MAC';
        } else if (stateStr === 'ANALYZING') {
            macBtn.style.display = 'flex';
            macBtn.disabled = true;
            macBtn.innerText = '⌛ ANALYZING ON MAC...';
        } else {
            macBtn.style.display = 'none';
        }
    }

    const emptyEl = document.getElementById('listenerEmptyState');
    if (!Array.isArray(tracks) || tracks.length === 0) {
        if (emptyEl) emptyEl.style.display = 'flex';
        if (macBtn) macBtn.style.display = 'none';
        for (let i = 0; i < 4; i++) {
            const rowBtn = document.getElementById(`listenerTrackRow${i}`);
            if (rowBtn) rowBtn.style.display = 'none';
        }
        return;
    }

    if (emptyEl) emptyEl.style.display = 'none';

    for (let i = 0; i < 4; i++) {
        const rowBtn = document.getElementById(`listenerTrackRow${i}`);
        if (!rowBtn) continue;
        if (i >= tracks.length) {
            rowBtn.style.display = 'none';
            continue;
        }
        const item = tracks[i];
        if (!item || typeof item !== 'object') {
            rowBtn.style.display = 'none';
            continue;
        }

        rowBtn.style.display = 'flex';
        const isSelected = (i === selectedIndex);
        if (isSelected) {
            rowBtn.style.borderColor = '#00f2fe';
            rowBtn.style.background = 'linear-gradient(90deg, rgba(0, 242, 254, 0.25), #0c1b1e)';
            rowBtn.style.boxShadow = '0 0 14px rgba(0, 242, 254, 0.45)';
        } else {
            rowBtn.style.borderColor = '#19464d';
            rowBtn.style.background = '#0c1b1e';
            rowBtn.style.boxShadow = 'none';
        }

        const titleEl = rowBtn.querySelector('.track-row-title');
        const metaEl = rowBtn.querySelector('.track-row-meta');
        const badgeEl = rowBtn.querySelector('.track-row-badge');

        if (titleEl && item.title) {
            titleEl.innerText = item.title;
        }
        if (metaEl && item.uploader) {
            metaEl.innerText = `${i + 1}. ${item.uploader}`;
        }
        if (badgeEl && item.duration) {
            badgeEl.innerText = item.duration;
        }
    }
}


