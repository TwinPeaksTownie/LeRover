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
    beatBanditTrackPage,
    selectedBeatBanditTrackId,
    cachedBeatBanditTracks,
    currentAppsMode,
    currentPresetsPage,
    currentPresetMode,
    isOverwriteModeActive,
    cachedPresetsList,
    currentAppsSubView,
    currentBackendSubView,
    bbStudioTab,
    activeChoreoData,
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
    const stateKey = `${isFollowerRunning}_${isLeaderRunning}_${isStudioRunning}_${isClackPoseRunning}_${isBeatBanditAppRunning}_${isBeatBanditDancing}_${isMasterDaemonRunning}_${isPokeballRunning}_${isPokeballConnected}`;
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
        if (isBeatBanditDancing) {
            appsStatus.innerText = 'BEAT BANDIT DANCING';
            appsStatus.style.color = '#ff00cc';
        } else if (isBeatBanditAppRunning) {
            appsStatus.innerText = 'BEAT BANDIT ACTIVE';
            appsStatus.style.color = '#a855f7';
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

    // Sewer daemon button
    const masterBtn = document.getElementById('masterDaemonBtn');
    const masterBtnText = document.getElementById('masterDaemonBtnText');
    const masterBtnSub = document.getElementById('masterDaemonBtnSub');
    if (masterBtn) {
        if (isMasterDaemonRunning) {
            masterBtn.style.borderColor = '#00ff66';
            masterBtn.style.color = '#00ff66';
            masterBtn.style.background = 'rgba(0, 255, 102, 0.12)';
            if (masterBtnText) masterBtnText.innerText = '🟢 STOP SEWER DAEMON';
            if (masterBtnSub) {
                masterBtnSub.innerText = '(PORT 8085 RUNNING)';
                masterBtnSub.style.color = '#aaffcc';
            }
        } else {
            masterBtn.style.borderColor = '#ffaa00';
            masterBtn.style.color = '#ffffff';
            masterBtn.style.background = '#181818';
            if (masterBtnText) masterBtnText.innerText = '🤖 START SEWER DAEMON';
            if (masterBtnSub) {
                masterBtnSub.innerText = '(DAEMON STOPPED)';
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
        const mins = Math.floor((t.duration || 0) / 60);
        const secs = Math.floor((t.duration || 0) % 60).toString().padStart(2, '0');
        const timeStr = `${mins}:${secs}`;
        const bpmVal = t.tempo || t.bpm || 0;
        const bpmStr = (bpmVal) ? `${Math.round(bpmVal)} BPM` : '-- BPM';
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

export function switchTab(tabId) {
    try { localStorage.setItem('active_tab', tabId); } catch(e) {}
    document.querySelectorAll('.rail-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    if (tabId === 'gantry') {
        const b = document.getElementById('railBtnGantry');
        const p = document.getElementById('panelGantry');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
    } else if (tabId === 'controls') {
        const b = document.getElementById('railBtnControls');
        const p = document.getElementById('panelControls');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
    } else if (tabId === 'apps') {
        const b = document.getElementById('railBtnApps');
        const p = document.getElementById('panelApps');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
    } else if (tabId === 'power') {
        const b = document.getElementById('railBtnPower');
        const p = document.getElementById('panelPower');
        if (b) b.classList.add('active');
        if (p) p.classList.add('active');
    }
}

export function openAppsSubView(subview) {
    setCurrentAppsSubView(subview);
    try { localStorage.setItem('apps_subview', subview); } catch(e) {}
    const vLauncher = document.getElementById('appsViewLauncher');
    const vClacker = document.getElementById('appsViewClacker');
    const vStudio = document.getElementById('appsViewStudio');
    const vBeatBandit = document.getElementById('appsViewBeatBandit');
    
    if (vLauncher) vLauncher.style.display = (subview === 'launcher') ? 'flex' : 'none';
    if (vClacker) vClacker.style.display = (subview === 'clacker') ? 'block' : 'none';
    if (vStudio) vStudio.style.display = (subview === 'studio') ? 'flex' : 'none';
    if (vBeatBandit) vBeatBandit.style.display = (subview === 'beat_bandit') ? 'flex' : 'none';
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
    setIsClackPoseRunning(currentApp === 'clack_pose_app');
    setIsFollowerRunning(currentApp === 'teleop_app');
    setIsLeaderRunning(!!((data.leader && data.leader.running) || (telemLeader && telemLeader.running)));
    
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
    if (currentApp === 'clack_pose_app' || currentApp === 'piranha_pose_app') {
        teleopStatusStr = 'PIRANHA POSE ACTIVE';
        teleopStatusColor = '#00e5ff';
    } else if (currentApp === 'pokeball_teleop_app') {
        teleopStatusStr = 'POKEBALL ACTIVE';
        teleopStatusColor = '#ff3344';
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

        if (dir && activeTelem) dir.innerText = (activeTelem.x_direction || 'CENTER').toUpperCase();
        if (joy && activeTelem) joy.innerText = `x_val=${activeTelem.x_val !== undefined ? activeTelem.x_val : 7}, y_val=${activeTelem.y_val !== undefined ? activeTelem.y_val : 118}`;
        if (rawHex && activeTelem) rawHex.innerText = activeTelem.raw_hex || '--';
        if (pkt && activeTelem) pkt.innerText = activeTelem.packet_count || 0;
        
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
            const deg = (s.deg !== undefined && s.deg !== null) ? s.deg : (s.pos !== undefined && s.pos !== null ? ((s.pos - 2048) * 360 / 4096).toFixed(0) : '--');
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
    setIsBeatBanditDancing(!!(bbData.is_dancing || (bbData.state === 'DANCING')));

    const bbBadge = document.getElementById('bbStateBadge');
    if (bbBadge) {
        const st = bbData.state || (isBeatBanditDancing ? 'DANCING' : (isBeatBanditAppRunning ? 'ACTIVE' : 'IDLE'));
        if (bbBadge.innerText !== st) {
            bbBadge.innerText = st;
            if (st === 'DANCING') {
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

    if (bbData.track) {
        const tTitle = document.getElementById('bbTrackTitle');
        const tArtist = document.getElementById('bbTrackArtist');
        if (tTitle && bbData.track.title && tTitle.innerText !== bbData.track.title) tTitle.innerText = bbData.track.title;
        if (tArtist && bbData.track.artist && tArtist.innerText !== bbData.track.artist) tArtist.innerText = bbData.track.artist;
    }

    const bbProg = document.getElementById('bbProgressBar');
    const bbBeatCtr = document.getElementById('bbBeatCounter');
    if (bbProg && bbData.progress !== undefined) bbProg.style.width = bbData.progress + '%';
    if (bbBeatCtr && bbData.current_beat !== undefined) bbBeatCtr.innerText = `Beat: ${bbData.current_beat} / ${bbData.total_beats || 0}`;

    if (bbData.time_sec !== undefined && isBeatBanditDancing) {
        setTimelinePlayheadTime(bbData.time_sec);
        if (bbStudioTab === 'timeline') {
            renderTimeline();
        }
    }

    const bbBpm = document.getElementById('bbBpmDisplay');
    const bbJaw = document.getElementById('bbJawDisplay');
    const bbS7 = document.getElementById('bbS7Display');
    const bbMove = document.getElementById('bbMoveDisplay');

    if (bbBpm && bbData.tempo) bbBpm.innerText = Number(bbData.tempo).toFixed(1) + ' BPM';
    if (bbJaw && bbData.vocal_power !== undefined) bbJaw.innerText = (Number(bbData.vocal_power) * 100).toFixed(0) + '%';
    if (bbS7 && bbData.s7_angle_deg !== undefined) {
        const s7val = Number(bbData.s7_angle_deg);
        bbS7.innerText = (s7val > 0 ? '+' : '') + s7val.toFixed(1) + '°';
    }
    if (bbMove && bbData.current_move) bbMove.innerText = bbData.current_move;

    renderButtonStates();

    // Power / Connection Mode Status (Tab 4)
    const pStatus = document.getElementById('powerStatus');
    const cm = data.connection_mode || {};
    let modeBadge = '🔵 OFFLINE (ETH)';
    if (cm.mode === 'IPHONE_HOTSPOT') {
        modeBadge = '🟢 IPHONE HOTSPOT';
    } else if (cm.mode === 'HOME_WIFI') {
        modeBadge = '🟢 MAESTAS MANSION';
    } else if (cm.ssid) {
        modeBadge = '🟢 ' + cm.ssid.toUpperCase();
    }

    if (pStatus) {
        let pStatusHtml = '';
        if (data.pi500_online) {
            const volt = (ht.bus_voltage !== undefined) ? ht.bus_voltage.toFixed(1) + 'V' : '--V';
            const pogoState = (ht.pogo_connected) ? 'POGO: OK' : 'POGO: DISC';
            const targetIp = data.resolved_pi500_ip || '10.0.0.1';
            if (data.daemon_running) {
                pStatusHtml = `PI 500 [${targetIp}] | ${modeBadge} | 12V: ${volt} | ${pogoState}`;
                pStatus.style.color = ht.pogo_connected ? '#00ff66' : '#00e5ff';
            } else {
                pStatusHtml = `PI 500 [${targetIp}] | ${modeBadge} | <span style="color:#ffaa00;">DAEMON OFF</span>`;
                pStatus.style.color = '#ffaa00';
            }
        } else {
            pStatusHtml = `PI 500 OFFLINE | ${modeBadge}`;
            pStatus.style.color = '#ff3344';
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
    if (!activeChoreoData) return;

    const duration = activeChoreoData.duration || 120.0;
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

    // 3. Helper to render blocks & detect gap slots
    function renderLaneBlocks(laneEl, blockList, channelKey, blockClass) {
        if (!laneEl) return;
        let html = '';
        let lastEnd = 0.0;

        (blockList || []).forEach((blk, idx) => {
            const st = Number(blk.start_sec !== undefined ? blk.start_sec : (blk.time_sec !== undefined ? blk.time_sec : 0));
            let et = Number(blk.end_sec !== undefined ? blk.end_sec : 0);
            if (et <= st) {
                const nextBlk = blockList[idx + 1];
                if (nextBlk) {
                    et = Number(nextBlk.start_sec !== undefined ? nextBlk.start_sec : (nextBlk.time_sec !== undefined ? nextBlk.time_sec : st + 4.0));
                } else {
                    et = duration || (st + 4.0);
                }
            }
            const dur = Math.max(0.1, et - st);
            
            // Check for gap before this block
            if (st > lastEnd + 1.5) {
                const gapLeft = labelOffset + (lastEnd * pps);
                const gapWidth = (st - lastEnd) * pps;
                html += `
                    <div class="block-gap-slot" data-channel="${channelKey}" data-start="${lastEnd.toFixed(1)}" data-end="${st.toFixed(1)}"
                         style="left: ${gapLeft}px; width: ${gapWidth}px;">
                        + ADD
                    </div>
                `;
            }

            const leftPx = labelOffset + (st * pps);
            const widthPx = Math.max(24, dur * pps);
            const isSel = selectedMoveBlock && selectedMoveBlock.id === blk.id;

            let label = blk.name || blk.pose_name || `${st.toFixed(0)}s-${et.toFixed(0)}s`;
            let effectiveClass = blockClass;

            if (channelKey === 's7_pedestal') {
                const tdeg = blk.target_deg !== undefined ? blk.target_deg : ((blk.height_norm !== undefined ? (blk.height_norm - 0.5) * 60 : 0));
                label = `${blk.name || 'Pedestal'} (${tdeg > 0 ? '+' : ''}${Number(tdeg).toFixed(0)}°)`;
            } else if (channelKey === 's8_gantry') {
                const tpos = blk.target_pos !== undefined ? blk.target_pos : (blk.position_norm !== undefined ? Math.round(blk.position_norm * 4800) : 2400);
                label = `${blk.name || 'Gantry'} (${tpos})`;
            } else if (channelKey === 'vocal_style') {
                const vStyle = (blk.style && (blk.style.includes('belt') || blk.style.includes('power') || blk.style.includes('shout') || blk.style.includes('soar') || blk.style.includes('climax'))) ? 'belting' : 'conversational';
                effectiveClass = (vStyle === 'belting') ? 'block-vocal-belting' : 'block-vocal-conversational';
                const snippet = blk.lyrics ? blk.lyrics.substring(0, 32) + (blk.lyrics.length > 32 ? '...' : '') : (blk.name || (vStyle === 'belting' ? 'Belting Section' : 'Singing Section'));
                label = `${vStyle === 'belting' ? '🔥 BELT' : '🗣️ SING'}: ${snippet}`;
            }

            html += `
                <div class="bb-move-block ${effectiveClass} ${isSel ? 'selected' : ''}"
                     data-channel="${channelKey}" data-id="${blk.id}"
                     style="left: ${leftPx}px; width: ${widthPx}px;"
                     title="${label} [${st.toFixed(1)}s - ${et.toFixed(1)}s]">
                    ${label}
                </div>
            `;
            lastEnd = et;
        });

        // Tail gap
        if (duration > lastEnd + 1.5) {
            const gapLeft = labelOffset + (lastEnd * pps);
            const gapWidth = (duration - lastEnd) * pps;
            html += `
                <div class="block-gap-slot" data-channel="${channelKey}" data-start="${lastEnd.toFixed(1)}" data-end="${duration.toFixed(1)}"
                     style="left: ${gapLeft}px; width: ${gapWidth}px;">
                    + ADD
                </div>
            `;
        }

        laneEl.innerHTML = html;
    }

    const tracks = activeChoreoData.tracks || {};
    renderLaneBlocks(document.getElementById('bbLaneBody'), tracks.spine_gaze || tracks.body_pose, 'spine_gaze', 'block-body');
    renderLaneBlocks(document.getElementById('bbLaneS8'), tracks.s8_gantry, 's8_gantry', 'block-s8');
    renderLaneBlocks(document.getElementById('bbLaneS7'), tracks.s7_pedestal, 's7_pedestal', 'block-s7');
    renderLaneBlocks(document.getElementById('bbLaneS1'), tracks.s1_torso, 's1_torso', 'block-s1');
    renderLaneBlocks(document.getElementById('bbLaneS5'), tracks.s5_head_tilt, 's5_head_tilt', 'block-s5');
    renderLaneBlocks(document.getElementById('bbLaneHeadJaw'), tracks.s6_jaw || tracks.head_jaw, 's6_jaw', 'block-head');

    // 3.5 Render Audio Waveform Visualizer Lane (Dark Blue Background, Cyan Ticks, Red Drop Lines)
    const waveCanvas = document.getElementById('bbWaveformCanvas');
    if (waveCanvas) {
        const laneW = Math.max(1000, duration * pps);
        const laneH = 46;
        waveCanvas.width = laneW;
        waveCanvas.height = laneH;
        waveCanvas.style.left = `${labelOffset}px`;
        waveCanvas.style.width = `${laneW}px`;
        waveCanvas.style.height = `${laneH}px`;

        const ctx = waveCanvas.getContext('2d');
        if (ctx) {
            // Dark navy blue background
            ctx.fillStyle = '#060d1f';
            ctx.fillRect(0, 0, laneW, laneH);

            // Subtle horizontal center baseline
            ctx.strokeStyle = '#1e293b';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, laneH / 2);
            ctx.lineTo(laneW, laneH / 2);
            ctx.stroke();

            const ampEnv = activeChoreoData.amplitude_envelope || activeChoreoData.mouth_envelope_50hz || [];
            const drops = activeChoreoData.drops || [];
            const midY = laneH / 2;
            const maxH = (laneH / 2) - 4;

            if (ampEnv && ampEnv.length > 0) {
                const fps = 50.0;
                const totalSamples = ampEnv.length;
                const barSpacing = 2.5;
                const totalBars = Math.floor(laneW / barSpacing);

                for (let b = 0; b < totalBars; b++) {
                    const x = b * barSpacing;
                    const timeAtX = x / pps;
                    const sampleIdx = Math.floor(timeAtX * fps);
                    if (sampleIdx < totalSamples) {
                        let rawVal = ampEnv[sampleIdx];
                        if (rawVal > 1.0) rawVal = rawVal / 45.0;
                        const amp = Math.max(0.06, Math.min(1.0, rawVal));
                        const barHeight = amp * maxH;

                        // Cyan / light blue vertical tick gradient
                        const grad = ctx.createLinearGradient(0, midY - barHeight, 0, midY + barHeight);
                        grad.addColorStop(0, '#38bdf8');   // Light blue
                        grad.addColorStop(0.5, '#00e5ff'); // Bright cyan
                        grad.addColorStop(1, '#0284c7');   // Deeper cyan

                        ctx.fillStyle = grad;
                        ctx.fillRect(x, midY - barHeight, 1.6, barHeight * 2);
                    }
                }
            } else {
                // Beat-aligned visualizer ticks fallback
                const beatTimes = activeChoreoData.beat_times || [];
                beatTimes.forEach((bt, idx) => {
                    const bx = bt * pps;
                    const isDownbeat = (idx % 4 === 0);
                    const bh = isDownbeat ? maxH * 0.85 : maxH * 0.45;
                    ctx.fillStyle = isDownbeat ? '#00e5ff' : '#38bdf8';
                    ctx.fillRect(bx, midY - bh, 1.8, bh * 2);
                });
            }

            // Draw thin vertical red lines for detected drops
            drops.forEach(d => {
                const dropSec = Number(d.drop_sec || 0);
                const dropX = dropSec * pps;

                // Red drop marker line
                ctx.strokeStyle = '#ef4444';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(dropX, 0);
                ctx.lineTo(dropX, laneH);
                ctx.stroke();

                // Drop tag banner
                ctx.fillStyle = '#ef4444';
                ctx.fillRect(dropX - 1, 0, 3, 10);
                ctx.font = 'bold 8.5px monospace';
                ctx.fillStyle = '#ff6b6b';
                ctx.fillText('⚡DROP', dropX + 4, 9);
            });
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
    const playhead = document.getElementById('bbPlayheadLine');
    if (playhead) {
        const phLeft = labelOffset + (timelinePlayheadTime * pps);
        playhead.style.left = `${phLeft}px`;
    }

    const timeDisplay = document.getElementById('bbTimelineTimeDisplay');
    if (timeDisplay) {
        const mins = Math.floor(timelinePlayheadTime / 60);
        const secs = (timelinePlayheadTime % 60).toFixed(1).padStart(4, '0');
        const beatTimes = activeChoreoData.beat_times || [];
        let currBeat = 0;
        for (let i = 0; i < beatTimes.length; i++) {
            if (beatTimes[i] <= timelinePlayheadTime) currBeat = i + 1;
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
        'spine_gaze': 'SPINE (S2-4)',
        'body_pose': 'SPINE (S2-4)',
        's8_gantry': 'GANTRY (S8)',
        's7_pedestal': 'PEDESTAL (S7)',
        's1_torso': 'GROOVE (S1)',
        's5_head_tilt': 'HEAD TILT (S5)',
        's6_jaw': 'LIP-SYNC JAW (S6)',
        'head_jaw': 'LIP-SYNC JAW (S6)',
        'vocal_style': 'VOCALS / LYRICS'
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
        const pos = Number(block.target_pos || 2400);
        const spd = Number(block.speed || 800);
        const mode = block.mode || 'hold';
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
        const deg = Number(block.target_deg || 0);
        controlsHtml += `
            <div style="display: flex; gap: 8px; align-items: center;">
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: #ccc;">
                        <span>STAGE FACING:</span><strong id="inspS7Val" style="color: #00ff66;">${deg > 0 ? '+' : ''}${deg}°</strong>
                    </div>
                    <input type="range" id="inspS7Slider" min="-90" max="90" step="5" value="${deg}">
                </div>
                <div style="display: flex; gap: 3px;">
                    <button class="btn-action insp-s7-preset" data-deg="-25" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">-25° Right</button>
                    <button class="btn-action insp-s7-preset" data-deg="0" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">0° Center</button>
                    <button class="btn-action insp-s7-preset" data-deg="25" style="padding: 2px 6px; font-size: 9px; height: 22px; min-height: 0; background: #1f1f2e; border: 1px solid #444; border-radius: 3px;">+25° Left</button>
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

    const rawPan = Number(poseDict.shoulder_pan || 0);
    const rawLift = Number(poseDict.shoulder_lift || -43.17);
    const rawElbow = Number(poseDict.elbow_flex || -25.69);
    const rawWristF = Number(poseDict.wrist_flex || 56.61);
    const rawWristR = Number(poseDict.wrist_roll || 0);

    const uiPan = Math.max(0, Math.min(100, (rawPan + 100) / 2.0));
    const uiLift = Math.max(0, Math.min(100, (rawLift + 100) / 2.0));
    const uiElbow = Math.max(0, Math.min(100, (rawElbow + 100) / 2.0));
    const uiWristF = Math.max(0, Math.min(100, (rawWristF + 100) / 2.0));
    const uiWristR = Math.max(0, Math.min(100, (rawWristR + 100) / 2.0));

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
        shoulder_pan: rawPan,
        shoulder_lift: rawLift,
        elbow_flex: rawElbow,
        wrist_flex: rawWristF,
        wrist_roll: rawWristR
    });
}

export function renderSettingsView() {
    if (!activeChoreoData) return;
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

