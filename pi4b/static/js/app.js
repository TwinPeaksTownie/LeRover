/**
 * Overlander 4 Touch Controller - Main Application Entry Point
 */

import {
    currentVerifiedPos,
    isLeaderRunning,
    isFollowerRunning,
    isPokeballRunning,
    isMasterDaemonRunning,
    isStudioRunning,
    isClackPoseRunning,
    isBeatBanditAppRunning,
    isBeatBanditDancing,
    isBeatBanditRunning,
    selectedBeatBanditTrackId,
    cachedBeatBanditTracks,
    currentAppsMode,
    currentPresetsPage,
    currentPresetMode,
    isOverwriteModeActive,
    cachedPresetsList,
    lastPresetsJsonStr,
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
    isPollingInProgress,
    isFetchingTracks,
    isFetchingPresets,
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
    setCachedBeatBanditTracks,
    setCurrentAppsMode,
    setCurrentPresetMode,
    setCachedPresetsList,
    setLastPresetsJsonStr,
    setBbStudioTab,
    setActiveChoreoData,
    setActiveProbabilitiesData,
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
    setConfigSettlingLock,
    updateConfigKey,
    setIsPollingInProgress,
    setIsFetchingTracks,
    setIsFetchingPresets
} from './state.js';

import * as api from './api.js';
import * as ui from './ui.js';

// ==========================================
// Action Handlers
// ==========================================

export function rotatePedestal(direction) {
    const dirStr = direction === 'left' ? 'LEFT (-45°)' : 'RIGHT (+45°)';
    const displayEl = document.getElementById('sliderValDisplay');
    if (displayEl) {
        displayEl.innerText = 'STEPPING ' + dirStr + '...';
        displayEl.style.color = '#ff9900';
    }
    api.sendPedestalStep(direction)
        .then(async r => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok || data.status === 'error') {
                ui.setHeaderAlert(data.message || data.error || 'SERVO UNRESPONSIVE');
            } else {
                if (data.at_limit && data.message && data.message.includes('limit reached')) {
                    ui.setHeaderAlert(data.message.toUpperCase());
                }
            }
        })
        .catch(() => ui.setHeaderAlert('NETWORK ERROR'));
}

export function sendSliderMove(targetVal) {
    const displayEl = document.getElementById('sliderValDisplay');
    if (displayEl) {
        displayEl.innerText = targetVal + ' ticks (SENDING...)';
        displayEl.style.color = '#f8d800';
    }
    api.sendSliderMove(targetVal)
        .then(async r => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok || data.status === 'error') {
                ui.setHeaderAlert(data.message || data.error || 'GANTRY UNRESPONSIVE');
            }
        })
        .catch(() => ui.setHeaderAlert('NETWORK ERROR'));
}

export function nudgeSlider(delta) {
    let targetVal = currentVerifiedPos + delta;
    targetVal = Math.max(3, Math.min(4800, targetVal));
    sendSliderMove(targetVal);
}

export function syncGantryPosition(pos) {
    const displayEl = document.getElementById('sliderValDisplay');
    if (displayEl) {
        displayEl.innerText = pos + ' ticks (SYNCING...)';
        displayEl.style.color = '#f8d800';
    }
    api.sendSyncPosition(8, pos)
        .then(async r => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok || data.status === 'error') {
                ui.setHeaderAlert(data.message || data.error || 'SYNC FAILED');
            } else {
                setCurrentVerifiedPos(pos);
            }
        })
        .catch(() => ui.setHeaderAlert('NETWORK ERROR'));
}

export function moveGantryMaxLeft() {
    sendSliderMove(3);
}

export function moveGantryCenter() {
    sendSliderMove(2400);
}

export function moveGantryMaxRight() {
    sendSliderMove(4800);
}

export function toggleMacLeader() {
    const action = isLeaderRunning ? 'stop' : 'start';
    const btn = document.getElementById('leaderBtn');
    const txt = document.getElementById('leaderBtnText');
    if (btn) {
        btn.style.borderColor = '#ffaa00';
        btn.style.color = '#ffaa00';
        if (txt) txt.innerText = action === 'stop' ? 'STOPPING...' : 'STARTING...';
    }
    api.sendMacLeaderToggle(action).catch(() => {});
}

export function togglePi500Follower() {
    const action = isFollowerRunning ? 'stop' : 'start';
    const btn = document.getElementById('followerBtn');
    const txt = document.getElementById('followerBtnText');
    if (btn) {
        btn.style.borderColor = '#ffaa00';
        btn.style.color = '#ffaa00';
        if (txt) txt.innerText = action === 'stop' ? 'STOPPING...' : 'STARTING...';
    }
    api.sendPi500FollowerToggle(action).catch(() => {});
}

export function togglePokeballTeleop() {
    const action = isPokeballRunning ? 'stop' : 'start';
    api.sendPokeballTeleopToggle(action).catch(() => {});
}

export function toggleServoStudio() {
    const action = isStudioRunning ? 'stop' : 'start';
    const btn = document.getElementById('studioBtn');
    const txt = document.getElementById('studioBtnText');
    if (btn) {
        btn.style.borderColor = '#ffaa00';
        btn.style.color = '#ffaa00';
        if (txt) txt.innerText = action === 'stop' ? 'STOPPING...' : 'STARTING...';
    }
    setIsStudioRunning(action === 'start');
    api.sendServoStudioToggle(action).catch(() => {});
}

export function toggleClackPose() {
    const action = isClackPoseRunning ? 'stop' : 'start';
    const btn = document.getElementById('clackPoseBtn');
    const txt = document.getElementById('clackPoseBtnText');
    if (btn) {
        btn.style.opacity = '0.5';
        if (txt) txt.innerText = action === 'start' ? '⌛ STARTING...' : '⌛ STOPPING...';
    }
    api.sendClackPoseToggle(action)
        .then(r => r.json())
        .then(d => {
            if (d.running !== undefined) setIsClackPoseRunning(d.running);
            if (btn) btn.style.opacity = '1.0';
            ui.renderButtonStates();
        })
        .catch(() => {
            if (btn) btn.style.opacity = '1.0';
            api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
        });
}

export function toggleBeatBanditApp() {
    const action = isBeatBanditAppRunning ? 'stop' : 'start';
    const btn = document.getElementById('bbAppToggleBtn');
    const txt = document.getElementById('bbAppToggleBtnText');
    if (btn) {
        btn.style.opacity = '0.5';
        if (txt) txt.innerText = action === 'start' ? '⌛ STARTING...' : '⌛ STOPPING...';
    }
    if (action === 'start') {
        api.sendAppStart('beat_bandit_app')
            .then(r => r.json())
            .then(d => {
                if (d.running !== undefined) setIsBeatBanditAppRunning(d.running);
                if (btn) btn.style.opacity = '1.0';
                ui.renderButtonStates();
            })
            .catch(err => {
                if (btn) btn.style.opacity = '1.0';
                ui.setHeaderAlert('START FAILED');
                api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
            });
    } else {
        if (isBeatBanditDancing) {
            stopBeatBanditDance();
        }
        api.sendAppStop('beat_bandit_app')
            .then(r => r.json())
            .then(() => {
                setIsBeatBanditAppRunning(false);
                setIsBeatBanditDancing(false);
                if (btn) btn.style.opacity = '1.0';
                ui.renderButtonStates();
            })
            .catch(err => {
                if (btn) btn.style.opacity = '1.0';
                ui.setHeaderAlert('STOP FAILED');
                api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
            });
    }
}

export function handleMainDanceBtnClick() {
    if (isBeatBanditDancing || timelineIsPlaying) {
        stopBeatBanditDance();
    } else {
        startBeatBanditFromInput();
    }
}

export function startBeatBanditFromInput() {
    const inp = document.getElementById('bbUrlInput');
    let val = (inp && inp.value) ? inp.value.trim() : '';
    if (!val) {
        val = selectedBeatBanditTrackId;
    }
    if (!val) {
        ui.setHeaderAlert('NO TRACK SELECTED');
        return;
    }
    startBeatBanditTrack(val);
}

export function startBeatBanditTrack(urlOrId) {
    const btn = document.getElementById('bbMainDanceBtn');
    const txt = document.getElementById('bbMainDanceText');
    if (btn) btn.style.opacity = '0.7';
    if (txt) txt.innerText = 'STARTING...';

    api.sendBeatBanditStart(urlOrId)
        .then(r => r.json())
        .then(d => {
            if (btn) btn.style.opacity = '1.0';
            if (d && d.status === 'error') {
                ui.setHeaderAlert(d.message || 'PLAYBACK ERROR');
                api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
                return;
            }
            setIsBeatBanditAppRunning(true);
            setIsBeatBanditDancing(true);
            ui.renderButtonStates();
            fetchBeatBanditTracks();
        })
        .catch(() => {
            if (btn) btn.style.opacity = '1.0';
            ui.setHeaderAlert('PLAYBACK ERROR');
            api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
        });
}

export function stopBeatBanditDance() {
    const btn = document.getElementById('bbMainDanceBtn');
    const txt = document.getElementById('bbMainDanceText');
    if (btn) btn.style.opacity = '0.5';
    if (txt) txt.innerText = 'STOPPING...';

    setTimelineIsPlaying(false);
    setIsBeatBanditDancing(false);
    api.sendBeatBanditStop()
        .then(r => r.json())
        .then(() => {
            setIsBeatBanditDancing(false);
            if (btn) btn.style.opacity = '1.0';
            ui.renderButtonStates();
            ui.renderTimeline();
        })
        .catch(() => {
            if (btn) btn.style.opacity = '1.0';
            api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
        });
}

export function startBeatBanditSectionPlay() {
    const tid = selectedBeatBanditTrackId || (activeChoreoData && activeChoreoData.track_id);
    if (!tid) {
        ui.setHeaderAlert('NO TRACK SELECTED');
        return;
    }

    let start_sec = 0.0;
    if (timelineInTime !== null) {
        start_sec = timelineInTime;
    } else {
        start_sec = timelinePlayheadTime;
    }
    let end_sec = timelineOutTime !== null ? timelineOutTime : null;

    api.sendBeatBanditStart(tid, { start_sec: start_sec, end_sec: end_sec, loop: timelineLoopEnabled })
        .then(r => r.json())
        .then(d => {
            if (d && d.status === 'error') {
                ui.setHeaderAlert(d.message || 'SECTION PLAY ERROR');
                api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
                return;
            }
            setIsBeatBanditAppRunning(true);
            setTimelineIsPlaying(true);
            setIsBeatBanditDancing(true);
            ui.renderTimeline();
            ui.renderButtonStates();
        })
        .catch(() => {
            ui.setHeaderAlert('PLAY ERROR');
            api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
        });
}

export function fetchBeatBanditTracks() {
    if (isFetchingTracks) return;
    setIsFetchingTracks(true);
    api.fetchBeatBanditTracksApi()
        .then(r => r.json())
        .then(d => {
            const tracks = d.tracks || [];
            setCachedBeatBanditTracks(tracks);
            ui.renderBeatBanditTracksList(tracks);
            loadBeatBanditProbabilities();
            if ((!selectedBeatBanditTrackId || !activeChoreoData) && tracks.length > 0) {
                const selId = selectedBeatBanditTrackId || tracks[0].track_id;
                const trk = tracks.find(t => t.track_id === selId) || tracks[0];
                ui.selectBeatBanditTrack(trk.track_id, trk.title, trk.artist);
                loadChoreographyForTrack(trk.track_id);
            }
        })
        .catch(() => {})
        .finally(() => { setIsFetchingTracks(false); });
}

export function loadChoreographyForTrack(trackId) {
    const tid = trackId || selectedBeatBanditTrackId;
    if (!tid) return;

    api.fetchBeatBanditChoreo(tid)
        .then(r => r.json())
        .then(d => {
            if (d.choreography) {
                setActiveChoreoData(d.choreography);
                if (bbStudioTab === 'timeline') ui.renderTimeline();
                else if (bbStudioTab === 'poses') ui.renderPosesList();
                else if (bbStudioTab === 'settings') ui.renderSettingsView();
            }
        })
        .catch(err => {
            console.error('Failed to load track choreography:', err);
            ui.setHeaderAlert('CHOREO LOAD ERROR');
        });
}

export function loadBeatBanditProbabilities() {
    api.fetchBeatBanditProbabilities()
        .then(r => r.json())
        .then(d => {
            if (d && d.status === 'ok' && d.probabilities) {
                setActiveProbabilitiesData(d.probabilities);
                if (bbStudioTab === 'settings') ui.renderSettingsView();
            }
        })
        .catch(err => {
            console.error('Failed to load probabilities:', err);
            ui.setHeaderAlert('PROBABILITIES LOAD ERROR');
        });
}

export async function saveAndRecompileSettings() {
    const tid = selectedBeatBanditTrackId || (activeChoreoData && activeChoreoData.track_id);
    const saveSettingsBtn = document.getElementById('bbSaveSettingsBtn');
    if (saveSettingsBtn) saveSettingsBtn.innerText = '⌛ RECOMPILING...';

    if (!activeProbabilitiesData) {
        console.error('FAIL-FAST: activeProbabilitiesData is missing during save');
        ui.setHeaderAlert('NO PROBABILITIES');
        return;
    }

    try {
        // 1. Save track choreo settings if active
        if (activeChoreoData && tid) {
            await api.saveBeatBanditChoreo(tid, activeChoreoData);
        }

        // 2. Save master probabilities and recompile track atomically
        const res = await api.saveBeatBanditProbabilities(activeProbabilitiesData, tid);
        const d = await res.json();

        if (!d || d.status !== 'ok') {
            throw new Error(d?.message || 'Server returned error status during save');
        }

        // 3. Bi-Directional Read-Back Verification State
        const verifyRes = await api.fetchBeatBanditProbabilities();
        const verifyData = await verifyRes.json();
        if (!verifyData || verifyData.status !== 'ok' || !verifyData.probabilities) {
            throw new Error('Bi-directional verification failed: unable to read back saved probabilities');
        }

        setActiveProbabilitiesData(verifyData.probabilities);
        if (d.choreography) {
            setActiveChoreoData(d.choreography);
            ui.renderTimeline();
        }

        await api.sendPlaySound({ kind: 'smw_save_menu' })
            .catch(err => console.warn('Sound FX error:', err));

        if (saveSettingsBtn) {
            saveSettingsBtn.innerText = '✅ RECOMPILED!';
            setTimeout(() => { saveSettingsBtn.innerText = '💾 SAVE & RECOMPILE'; }, 1500);
        }
    } catch (err) {
        console.error('Save & recompile verification failed:', err);
        ui.setHeaderAlert('RECOMPILE ERROR');
        if (saveSettingsBtn) {
            saveSettingsBtn.innerText = '❌ ERROR';
            setTimeout(() => { saveSettingsBtn.innerText = '💾 SAVE & RECOMPILE'; }, 2000);
        }
    }
}

export function saveCurrentChoreography() {
    if (!activeChoreoData) return;
    const tid = selectedBeatBanditTrackId;
    api.saveBeatBanditChoreo(tid, activeChoreoData)
        .then(r => r.json())
        .then(d => {
            api.sendPlaySound({ kind: 'smw_save_menu' })
                .catch(err => console.warn('Sound FX error:', err));
            const saveBtn = document.getElementById('bbSaveChoreoBtn');
            if (saveBtn) {
                saveBtn.innerText = '✅ SAVED!';
                setTimeout(() => { saveBtn.innerText = '💾 SAVE'; }, 1500);
            }
        })
        .catch(err => {
            console.error('Failed to save choreography:', err);
            ui.setHeaderAlert('CHOREO SAVE ERROR');
        });
}

export function openAIDirectorModalFlow() {
    const tid = selectedBeatBanditTrackId || (activeChoreoData && activeChoreoData.track_id);
    if (!tid) {
        ui.setHeaderAlert('NO TRACK SELECTED');
        return;
    }
    const tracks = cachedBeatBanditTracks || [];
    const track = tracks.find(t => t.track_id === tid || t.id === tid);
    if (!track && !activeChoreoData) {
        ui.setHeaderAlert('TRACK METADATA UNAVAILABLE');
        return;
    }
    const title = (track && track.title) || (activeChoreoData && activeChoreoData.title);
    const dur = (track && track.duration) || (activeChoreoData && activeChoreoData.duration);
    const tempo = (track && (track.tempo || track.bpm)) || (activeChoreoData && activeChoreoData.settings && activeChoreoData.settings.bpm);
    if (!title || !dur || !tempo) {
        ui.setHeaderAlert('INCOMPLETE TRACK METADATA');
        return;
    }
    const durMins = Math.floor(dur / 60);
    const durSecs = Math.floor(dur % 60).toString().padStart(2, '0');
    const meta = `${tempo} BPM • ${durMins}:${durSecs}`;

    ui.openDirectorModal();
    ui.renderDirectorLoading('Querying Ornith 35B for Preliminary Stage Proposal...');

    api.startStageDirectorSession(tid)
        .then(r => r.json())
        .then(d => {
            if (d && d.status === 'ok') {
                setActiveDirectorSessionId(d.session_id);
                setActiveDirectorBrief(d.stage_brief);
                ui.renderDirectorBrief(d.stage_brief, title, meta);
            } else {
                console.error('Failed to start AI director session:', d);
                ui.renderDirectorLoading('Error: ' + (d.message || 'Failed to start AI director session.'));
                setTimeout(() => ui.closeDirectorModal(), 4000);
            }
        })
        .catch(err => {
            console.error('AI Stage Director Error:', err);
            ui.renderDirectorLoading('Error: ' + err.message);
            setTimeout(() => ui.closeDirectorModal(), 4000);
        });
}

export function submitDirectorFeedbackFlow(acceptAsIs = false) {
    const sid = activeDirectorSessionId;
    if (!sid) return;

    const feedbackInput = document.getElementById('bbDirectorFeedbackInput');
    const feedbackText = (feedbackInput && feedbackInput.value) ? feedbackInput.value.trim() : '';

    ui.renderDirectorLoading(acceptAsIs ? 'Synthesizing 5-Track Timeline with Ornith 35B...' : 'Synthesizing Directed 5-Track Timeline with Ornith 35B...');

    api.sendStageDirectorFeedback(sid, feedbackText, acceptAsIs)
        .then(r => r.json())
        .then(d => {
            if (d && d.status === 'ok' && d.choreography) {
                setActiveChoreoData(d.choreography);
                ui.closeDirectorModal();
                ui.renderTimeline();
                api.sendPlaySound({ kind: 'smw_save_menu' }).catch(() => {});
            } else {
                console.error('Failed to synthesize choreography:', d);
                ui.renderDirectorLoading('Error: ' + (d.message || 'Failed to synthesize choreography.'));
                setTimeout(() => ui.closeDirectorModal(), 4000);
            }
        })
        .catch(err => {
            console.error('Choreography Synthesis Error:', err);
            ui.renderDirectorLoading('Error: ' + err.message);
            setTimeout(() => ui.closeDirectorModal(), 4000);
        });
}

export function autoGenerateChoreography(style = 'balanced') {
    openAIDirectorModalFlow();
}

export function setClackThreshold(val) {
    applyConfig('clack_threshold', val);
}

export function armLimpMode() {
    api.sendArmTorque(false).catch(() => {});
}

export function armSavePose() {
    api.sendArmCapturePose().catch(() => {});
}

export function commitOfficialPreset() {
    api.sendArmCommitPreset(currentPresetMode)
        .then(r => r.json())
        .then(() => {
            fetchPresetsList(true);
        })
        .catch(() => {});
}

export function armResumePose() {
    const dur = currentConfig.arm_speed_sec || 1.0;
    api.sendArmResumePose(dur, currentPresetMode).catch(() => {});
}

export function triggerOverwritePreset(presetName, label) {
    const appsStatus = document.getElementById('appsStatus');
    if (appsStatus) {
        appsStatus.innerText = `OVERWRITING ${label}...`;
        appsStatus.style.color = '#ffaa00';
    }
    api.sendArmOverwritePreset(presetName, currentPresetMode)
        .then(r => r.json())
        .then(() => {
            api.sendPlaySound({ kind: 'smw_save_menu' }).catch(() => {});

            if (appsStatus) {
                appsStatus.innerText = `✅ OVERWROTE ${label} (${currentPresetMode.toUpperCase()})`;
                appsStatus.style.color = '#00ff66';
            }
            ui.toggleOverwriteMode();
            fetchPresetsList(true);
        })
        .catch(err => {
            if (appsStatus) {
                appsStatus.innerText = `OVERWRITE ERROR: ${err}`;
                appsStatus.style.color = '#ff3344';
            }
        });
}

export function triggerSequenceAction() {
    const appsStatus = document.getElementById('appsStatus');
    if (currentPresetMode === 'demo') {
        if (appsStatus) {
            appsStatus.innerText = '☠️ EXECUTING 4-CLICK ATTACK DEMO...';
            appsStatus.style.color = '#ff3344';
        }
        api.sendArmAttackSequence().catch(() => {});
    } else {
        if (appsStatus) {
            appsStatus.innerText = `▶️ EXECUTING ${currentPresetMode.toUpperCase()} SEQUENCE...`;
            appsStatus.style.color = '#00ff66';
        }
        api.sendArmExecuteSequence('sequence_' + currentPresetMode, currentPresetMode).catch(() => {});
    }
}

export function triggerMoveToPreset(presetName, label) {
    if (isOverwriteModeActive) {
        triggerOverwritePreset(presetName, label);
        return;
    }
    const appsStatus = document.getElementById('appsStatus');
    if (appsStatus) {
        appsStatus.innerText = `MOVING TO ${label}...`;
        appsStatus.style.color = '#00ff66';
    }
    const dur = currentConfig.arm_speed_sec || 1.0;
    api.sendArmMoveToPreset(presetName, dur, currentPresetMode)
        .then(r => r.json())
        .then(() => {
            setTimeout(() => {
                if (appsStatus) {
                    appsStatus.innerText = `ARRIVED AT ${label}`;
                    appsStatus.style.color = '#00e5ff';
                }
            }, Math.round(dur * 1000));
        })
        .catch(() => {
            if (appsStatus) {
                appsStatus.innerText = `MOVE ERROR: ${label}`;
                appsStatus.style.color = '#ff3344';
            }
        });
}

export function fetchPresetsList(forceRender = false) {
    if (isFetchingPresets && !forceRender) return;
    setIsFetchingPresets(true);

    api.fetchArmPresets(currentPresetMode)
        .then(r => r.json())
        .then(data => {
            const newJsonStr = JSON.stringify(data.presets || {});
            if (newJsonStr !== lastPresetsJsonStr || forceRender) {
                setLastPresetsJsonStr(newJsonStr);
                setCachedPresetsList(data.presets || {});
                if (currentAppsMode === 'presets') {
                    ui.renderPresetsGrid();
                }
            }
        })
        .catch(() => {})
        .finally(() => { setIsFetchingPresets(false); });
}

export function triggerPi500PowerOn() {
    api.sendPi500PowerOn().catch(() => {});
}

export function triggerPi500MasterDaemonRestart() {
    const action = isMasterDaemonRunning ? 'stop' : 'start';
    const btn = document.getElementById('masterDaemonBtn');
    const txt = document.getElementById('masterDaemonBtnText');
    if (btn) {
        btn.style.opacity = '0.5';
        if (txt) txt.innerText = action === 'stop' ? '⌛ STOPPING SEWER DAEMON...' : '⌛ STARTING SEWER DAEMON...';
    }
    api.sendMasterDaemonRestart(action)
        .then(r => r.json())
        .then(() => {
            if (btn) btn.style.opacity = '1.0';
            setIsMasterDaemonRunning(action !== 'stop');
            ui.renderButtonStates();
        })
        .catch(() => {
            if (btn) {
                btn.style.opacity = '1.0';
                if (txt) txt.innerText = '❌ SEWER DAEMON ERROR';
            }
        });
}

export function triggerEmergencyKillAll() {
    api.sendEmergencyKillAll().catch(() => {});
}

export function triggerWifiRestore() {
    ui.setHeaderAlert('RESTORING WI-FI...');
    api.sendWifiRestore().catch(() => {});
}

export function triggerWifiDisable() {
    if (window.confirm('Disable Wi-Fi on both Pis to test Direct Ethernet isolation? (10-min safety auto-restore active)')) {
        ui.setHeaderAlert('DISABLING WI-FI...');
        api.sendWifiDisable().catch(() => {});
    }
}

export function applyConfig(key, val) {
    setConfigSettlingLock(key, 800);
    const prevVal = currentConfig[key];
    updateConfigKey(key, val);
    ui.updateConfigUI();
    api.sendSetConfig({ [key]: val })
        .catch(() => {
            updateConfigKey(key, prevVal);
            ui.updateConfigUI();
            api.sendPlaySound({ kind: 'incorrect' }).catch(() => {});
        });
}

// ==========================================
// Sequential Telemetry Polling Loop
// ==========================================

export function pollTelemetry() {
    if (isPollingInProgress) return;
    setIsPollingInProgress(true);

    api.fetchStatus()
        .then(r => {
            if (!r.ok) {
                setIsFollowerRunning(false);
                setIsLeaderRunning(false);
                setIsPokeballRunning(false);
                setIsPokeballConnected(false);
                ui.renderButtonStates();
                return null;
            }
            return r.json();
        })
        .then(data => {
            ui.updateTelemetryUI(data);

            if (currentAppsMode === 'presets' || isClackPoseRunning) {
                fetchPresetsList(false);
            }
        })
        .catch(() => {
            setIsFollowerRunning(false);
            setIsLeaderRunning(false);
            setIsPokeballRunning(false);
            setIsPokeballConnected(false);
            ui.renderButtonStates();
        })
        .finally(() => {
            setIsPollingInProgress(false);
            setTimeout(pollTelemetry, 350);
        });
}

// ==========================================
// DOM Event Listener Binding & Initialization
// ==========================================

function bindEventListeners() {
    // 1. Navigation Rail
    const railGantry = document.getElementById('railBtnGantry');
    const railControls = document.getElementById('railBtnControls');
    const railApps = document.getElementById('railBtnApps');
    const railPower = document.getElementById('railBtnPower');

    if (railGantry) railGantry.addEventListener('click', () => ui.switchTab('gantry'));
    if (railControls) railControls.addEventListener('click', () => ui.switchTab('controls'));
    if (railApps) railApps.addEventListener('click', () => {
        ui.switchTab('apps');
        ui.openAppsSubView('launcher');
    });
    if (railPower) railPower.addEventListener('click', () => ui.switchTab('power'));

    // 2. Tab 1: Gantry & Pedestal
    const pedLeft = document.getElementById('pedestalLeftBtn');
    const pedRight = document.getElementById('pedestalRightBtn');
    const gStepLeft = document.getElementById('gantryStepLeftBtn');
    const gStepRight = document.getElementById('gantryStepRightBtn');
    const gMaxLeft = document.getElementById('gantryMaxLeftBtn');
    const gCenter = document.getElementById('gantryCenterBtn');
    const gMaxRight = document.getElementById('gantryMaxRightBtn');

    if (pedLeft) pedLeft.addEventListener('click', () => rotatePedestal('left'));
    if (pedRight) pedRight.addEventListener('click', () => rotatePedestal('right'));
    if (gStepLeft) gStepLeft.addEventListener('click', () => nudgeSlider(-500));
    if (gStepRight) gStepRight.addEventListener('click', () => nudgeSlider(500));
    if (gMaxLeft) gMaxLeft.addEventListener('click', () => moveGantryMaxLeft());
    if (gCenter) gCenter.addEventListener('click', () => moveGantryCenter());
    if (gMaxRight) gMaxRight.addEventListener('click', () => moveGantryMaxRight());

    // 3. Tab 2: Teleop Controllers
    const leaderBtn = document.getElementById('leaderBtn');
    const followerBtn = document.getElementById('followerBtn');
    const pokeballBtn = document.getElementById('pokeballBtn');

    if (leaderBtn) leaderBtn.addEventListener('click', () => toggleMacLeader());
    if (followerBtn) followerBtn.addEventListener('click', () => togglePi500Follower());
    if (pokeballBtn) pokeballBtn.addEventListener('click', () => togglePokeballTeleop());

    // 4. Tab 3: Robot Applications
    // View A: Top-level Launcher
    const launchClacker = document.getElementById('launchClackerBtn');
    const launchStudio = document.getElementById('launchStudioBtn');
    const launchBeatBandit = document.getElementById('launchBeatBanditBtn');

    if (launchClacker) launchClacker.addEventListener('click', () => {
        ui.openAppsSubView('clacker');
        if (currentAppsMode === 'presets') fetchPresetsList(true);
    });
    if (launchStudio) launchStudio.addEventListener('click', () => {
        ui.openAppsSubView('studio');
    });
    if (launchBeatBandit) launchBeatBandit.addEventListener('click', () => {
        ui.openAppsSubView('beat_bandit');
        fetchBeatBanditTracks();
    });

    // View B: Piranha Pose Controls & Presets
    const clackPoseBtn = document.getElementById('clackPoseBtn');
    const clackerBackBtn = document.getElementById('clackerBackBtn');
    const armLimpBtn = document.getElementById('armLimpBtn');
    const armSaveBtn = document.getElementById('armSaveBtn');
    const commitPresetBtn = document.getElementById('commitPresetBtn');
    const armResumeBtn = document.getElementById('armResumeBtn');
    const sensLowBtn = document.getElementById('sensLowBtn');
    const sensNormBtn = document.getElementById('sensNormBtn');
    const sensHiBtn = document.getElementById('sensHiBtn');
    const openPresetsModeBtn = document.getElementById('openPresetsModeBtn');

    if (clackPoseBtn) clackPoseBtn.addEventListener('click', () => toggleClackPose());
    if (clackerBackBtn) clackerBackBtn.addEventListener('click', () => {
        ui.openAppsSubView('launcher');
    });
    if (armLimpBtn) armLimpBtn.addEventListener('click', () => armLimpMode());
    if (armSaveBtn) armSaveBtn.addEventListener('click', () => armSavePose());
    if (commitPresetBtn) commitPresetBtn.addEventListener('click', () => commitOfficialPreset());
    if (armResumeBtn) armResumeBtn.addEventListener('click', () => armResumePose());
    if (sensLowBtn) sensLowBtn.addEventListener('click', () => setClackThreshold(7500));
    if (sensNormBtn) sensNormBtn.addEventListener('click', () => setClackThreshold(5200));
    if (sensHiBtn) sensHiBtn.addEventListener('click', () => setClackThreshold(3500));
    if (openPresetsModeBtn) openPresetsModeBtn.addEventListener('click', () => {
        ui.switchAppsMode('presets');
        fetchPresetsList(true);
    });

    const modeTabNormal = document.getElementById('modeTabNormal');
    const modeTabDemo = document.getElementById('modeTabDemo');
    const modeTabAngry = document.getElementById('modeTabAngry');
    const modeTabDance = document.getElementById('modeTabDance');
    const overwriteModeBtn = document.getElementById('overwriteModeBtn');
    const seqPlayBtn = document.getElementById('seqPlayBtn');
    const presetsReturnBtn = document.getElementById('presetsReturnBtn');
    const presetsGridContainer = document.getElementById('presetsGridContainer');

    if (modeTabNormal) modeTabNormal.addEventListener('click', () => {
        ui.setPresetsMode('normal');
        fetchPresetsList(true);
    });
    if (modeTabDemo) modeTabDemo.addEventListener('click', () => {
        ui.setPresetsMode('demo');
        fetchPresetsList(true);
    });
    if (modeTabAngry) modeTabAngry.addEventListener('click', () => {
        ui.setPresetsMode('angry');
        fetchPresetsList(true);
    });
    if (modeTabDance) modeTabDance.addEventListener('click', () => {
        ui.setPresetsMode('dance');
        fetchPresetsList(true);
    });
    if (overwriteModeBtn) overwriteModeBtn.addEventListener('click', () => ui.toggleOverwriteMode());
    if (seqPlayBtn) seqPlayBtn.addEventListener('click', () => triggerSequenceAction());
    if (presetsReturnBtn) presetsReturnBtn.addEventListener('click', () => ui.switchAppsMode('controls'));

    // Event Delegation for dynamically rendered Presets Grid
    if (presetsGridContainer) {
        presetsGridContainer.addEventListener('click', (e) => {
            const slotBtn = e.target.closest('.preset-slot-btn');
            if (slotBtn) {
                const presetKey = slotBtn.getAttribute('data-preset');
                const presetLabel = slotBtn.getAttribute('data-label');
                if (presetKey && presetLabel) {
                    triggerMoveToPreset(presetKey, presetLabel);
                }
                return;
            }
            const pageBtn = e.target.closest('.preset-page-btn');
            if (pageBtn) {
                const newPage = parseInt(pageBtn.getAttribute('data-page'), 10);
                if (!isNaN(newPage)) {
                    ui.changePresetsPage(newPage);
                }
            }
        });
    }

    // View C: Studio
    const studioBackBtn = document.getElementById('studioBackBtn');
    const studioBtn = document.getElementById('studioBtn');

    if (studioBackBtn) studioBackBtn.addEventListener('click', () => {
        ui.openAppsSubView('launcher');
    });
    if (studioBtn) studioBtn.addEventListener('click', () => toggleServoStudio());

    // View D: Beat Bandit & Choreography Studio
    const bbBackBtn = document.getElementById('bbBackBtn');
    const bbAppToggleBtn = document.getElementById('bbAppToggleBtn');
    const bbFetchBtn = document.getElementById('bbFetchBtn');
    const bbPageBtn = document.getElementById('bbPageBtn');
    const bbTracksList = document.getElementById('bbTracksList');
    const bbMainDanceBtn = document.getElementById('bbMainDanceBtn');

    if (bbBackBtn) bbBackBtn.addEventListener('click', () => {
        ui.openAppsSubView('launcher');
    });
    if (bbAppToggleBtn) bbAppToggleBtn.addEventListener('click', () => toggleBeatBanditApp());
    if (bbFetchBtn) bbFetchBtn.addEventListener('click', () => startBeatBanditFromInput());
    if (bbPageBtn) bbPageBtn.addEventListener('click', () => ui.handleBeatBanditPageToggle());
    if (bbMainDanceBtn) bbMainDanceBtn.addEventListener('click', () => handleMainDanceBtnClick());

    // Event Delegation for dynamically rendered Beat Bandit Tracks
    if (bbTracksList) {
        bbTracksList.addEventListener('click', (e) => {
            const trackCard = e.target.closest('.bb-track-card');
            if (trackCard) {
                const trackId = trackCard.getAttribute('data-track-id');
                const title = trackCard.getAttribute('data-title');
                const artist = trackCard.getAttribute('data-artist');
                if (trackId) {
                    ui.selectBeatBanditTrack(trackId, title, artist);
                    if (bbStudioTab !== 'player') {
                        loadChoreographyForTrack(trackId);
                    }
                }
            }
        });
    }

    // Studio SubTab Navigation
    const navPlayer = document.getElementById('bbNavPlayer');
    const navTimeline = document.getElementById('bbNavTimeline');
    const navPoses = document.getElementById('bbNavPoses');
    const navSettings = document.getElementById('bbNavSettings');

    if (navPlayer) navPlayer.addEventListener('click', () => ui.switchBbStudioTab('player'));
    if (navTimeline) navTimeline.addEventListener('click', () => {
        ui.switchBbStudioTab('timeline');
        loadChoreographyForTrack(selectedBeatBanditTrackId);
    });
    if (navPoses) navPoses.addEventListener('click', () => {
        ui.switchBbStudioTab('poses');
        loadChoreographyForTrack(selectedBeatBanditTrackId);
    });
    if (navSettings) navSettings.addEventListener('click', () => {
        ui.switchBbStudioTab('settings');
        loadChoreographyForTrack(selectedBeatBanditTrackId);
    });

    // Timeline Transport & In/Out Marker Buttons
    const rewindBtn = document.getElementById('bbRewindBtn');
    const playSectionBtn = document.getElementById('bbPlaySectionBtn');
    const stopChoreoBtn = document.getElementById('bbStopChoreoBtn');
    const loopSectionBtn = document.getElementById('bbLoopSectionBtn');
    const setInBtn = document.getElementById('bbSetInBtn');
    const setOutBtn = document.getElementById('bbSetOutBtn');
    const clearInOutBtn = document.getElementById('bbClearInOutBtn');

    if (rewindBtn) rewindBtn.addEventListener('click', () => {
        setTimelinePlayheadTime(timelineInTime !== null ? timelineInTime : 0.0);
        ui.renderTimeline();
    });
    if (playSectionBtn) playSectionBtn.addEventListener('click', () => startBeatBanditSectionPlay());
    if (stopChoreoBtn) stopChoreoBtn.addEventListener('click', () => stopBeatBanditDance());
    if (loopSectionBtn) loopSectionBtn.addEventListener('click', () => {
        setTimelineLoopEnabled(!timelineLoopEnabled);
        ui.renderTimeline();
    });
    if (setInBtn) setInBtn.addEventListener('click', () => {
        setTimelineInTime(Number(timelinePlayheadTime.toFixed(1)));
        if (timelineOutTime !== null && timelineOutTime <= timelinePlayheadTime) {
            setTimelineOutTime(null);
        }
        ui.renderTimeline();
        api.sendPlaySound({ kind: 'smw_save_menu' }).catch(() => {});
    });
    if (setOutBtn) setOutBtn.addEventListener('click', () => {
        if (timelineInTime !== null && timelinePlayheadTime <= timelineInTime) {
            setTimelineInTime(0.0);
        }
        setTimelineOutTime(Number(timelinePlayheadTime.toFixed(1)));
        ui.renderTimeline();
        api.sendPlaySound({ kind: 'smw_save_menu' }).catch(() => {});
    });
    if (clearInOutBtn) clearInOutBtn.addEventListener('click', () => {
        setTimelineInTime(null);
        setTimelineOutTime(null);
        ui.renderTimeline();
    });

    // Timeline Zoom & Global Action Buttons
    const zoomInBtn = document.getElementById('bbZoomInBtn');
    const zoomOutBtn = document.getElementById('bbZoomOutBtn');
    const addMoveBtn = document.getElementById('bbAddMoveBtn');
    const autoChoreoBtn = document.getElementById('bbAutoChoreoBtn');
    const saveChoreoBtn = document.getElementById('bbSaveChoreoBtn');

    if (zoomInBtn) zoomInBtn.addEventListener('click', () => {
        setTimelinePixelsPerSec(Math.min(120, timelinePixelsPerSec + 10));
        ui.renderTimeline();
    });
    if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => {
        setTimelinePixelsPerSec(Math.max(15, timelinePixelsPerSec - 10));
        ui.renderTimeline();
    });
    if (addMoveBtn) addMoveBtn.addEventListener('click', () => {
        if (!activeChoreoData || !activeChoreoData.duration) {
            ui.setHeaderAlert('NO CHOREOGRAPHY LOADED');
            return;
        }
        const tracks = activeChoreoData.tracks;
        if (!tracks) {
            ui.setHeaderAlert('CHOREOGRAPHY HAS NO TRACKS');
            return;
        }
        const ch = selectedMoveChannel || 'spine_gaze';
        if (!tracks[ch]) tracks[ch] = [];
        
        const newId = 'move_' + Date.now();
        const st = timelinePlayheadTime;
        const et = Math.min(activeChoreoData.duration, st + 3.0);
        let newBlock = { id: newId, name: 'New Move', start_sec: st, end_sec: et };

        if (ch === 'body_pose' || ch === 'spine_gaze') {
            if (!selectedPoseName) {
                ui.setHeaderAlert('NO POSE SELECTED');
                return;
            }
            newBlock.pose_name = selectedPoseName;
            newBlock.transition_sec = 0.5;
        } else if (ch === 's7_pedestal') {
            newBlock.target_deg = 0.0;
        } else if (ch === 's8_gantry') {
            newBlock.target_pos = 2400;
            newBlock.speed = 800;
        }

        tracks[ch].push(newBlock);
        tracks[ch].sort((a, b) => a.start_sec - b.start_sec);
        ui.openMoveInspector(ch, newBlock);
    });
    if (autoChoreoBtn) autoChoreoBtn.addEventListener('click', () => openAIDirectorModalFlow());
    if (saveChoreoBtn) saveChoreoBtn.addEventListener('click', () => saveCurrentChoreography());

    // AI Stage Director Modal Event Listeners
    const dirCloseBtn = document.getElementById('bbDirectorCloseBtn');
    const dirCancelBtn = document.getElementById('bbDirectorCancelBtn');
    const dirAcceptBtn = document.getElementById('bbDirectorAcceptBtn');
    const dirGenerateBtn = document.getElementById('bbDirectorGenerateBtn');

    if (dirCloseBtn) dirCloseBtn.addEventListener('click', () => ui.closeDirectorModal());
    if (dirCancelBtn) dirCancelBtn.addEventListener('click', () => ui.closeDirectorModal());
    if (dirAcceptBtn) dirAcceptBtn.addEventListener('click', () => submitDirectorFeedbackFlow(true));
    if (dirGenerateBtn) dirGenerateBtn.addEventListener('click', () => submitDirectorFeedbackFlow(false));

    // Delegate quick-directive chips
    const dirModal = document.getElementById('bbDirectorModal');
    if (dirModal) {
        dirModal.addEventListener('click', (e) => {
            const chip = e.target.closest('.bb-director-chip');
            if (chip) {
                const text = chip.getAttribute('data-text');
                const feedbackInput = document.getElementById('bbDirectorFeedbackInput');
                if (feedbackInput && text) {
                    const curr = feedbackInput.value.trim();
                    feedbackInput.value = curr ? `${curr}\n${text}` : text;
                    feedbackInput.focus();
                }
            }
        });
    }

    // Timeline Track Canvas Interaction (Clicking Blocks, Gap Slots, Scrubber)
    const timelineContainer = document.getElementById('bbTimelineTrackCanvas');
    if (timelineContainer) {
        timelineContainer.addEventListener('click', (e) => {
            const blockEl = e.target.closest('.bb-move-block');
            if (blockEl) {
                const channel = blockEl.getAttribute('data-channel');
                const blockId = blockEl.getAttribute('data-id');
                const tracks = (activeChoreoData && activeChoreoData.tracks) ? activeChoreoData.tracks[channel] : [];
                const block = (tracks || []).find(b => b.id === blockId);
                if (block) {
                    ui.openMoveInspector(channel, block);
                }
                return;
            }

            // Clicked empty canvas or ruler: move playhead (offset 100px for label width)
            const rect = timelineContainer.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const targetTime = Math.max(0, (clickX - 100) / timelinePixelsPerSec);
            setTimelinePlayheadTime(Number(targetTime.toFixed(1)));
            ui.renderTimeline();
        });
    }

    // Inspector Drawer Interaction
    const inspPreviewBtn = document.getElementById('bbInspectorPreviewBtn');
    const inspDupBtn = document.getElementById('bbInspectorDuplicateBtn');
    const inspDelBtn = document.getElementById('bbInspectorDeleteBtn');
    const inspCloseBtn = document.getElementById('bbInspectorCloseBtn');
    const inspNameInp = document.getElementById('bbInspectorNameInput');
    const inspDynamicCtrls = document.getElementById('bbInspectorDynamicControls');

    if (inspCloseBtn) inspCloseBtn.addEventListener('click', () => ui.closeMoveInspector());
    if (inspNameInp) inspNameInp.addEventListener('input', (e) => {
        if (selectedMoveBlock) {
            selectedMoveBlock.name = e.target.value;
            ui.renderTimeline();
        }
    });

    if (inspPreviewBtn) inspPreviewBtn.addEventListener('click', () => {
        if (!selectedMoveBlock || !activeChoreoData) return;
        if (selectedMoveChannel === 'body_pose' || selectedMoveChannel === 'spine_gaze') {
            const poses = activeChoreoData.poses;
            if (!poses || !poses[selectedMoveBlock.pose_name]) {
                ui.setHeaderAlert(`POSE '${selectedMoveBlock.pose_name}' NOT FOUND`);
                return;
            }
            const p = poses[selectedMoveBlock.pose_name];
            api.previewBeatBanditPose(p).catch(() => {});
        } else if (selectedMoveChannel === 's7_pedestal') {
            api.previewBeatBanditMovement('s7_pedestal', selectedMoveBlock.target_deg).catch(() => {});
        } else if (selectedMoveChannel === 's8_gantry') {
            api.previewBeatBanditMovement('s8_gantry', selectedMoveBlock.target_pos).catch(() => {});
        }
    });

    if (inspDupBtn) inspDupBtn.addEventListener('click', () => {
        if (!selectedMoveBlock || !activeChoreoData || !activeChoreoData.duration) return;
        const tracks = activeChoreoData.tracks[selectedMoveChannel] || [];
        const dur = selectedMoveBlock.end_sec - selectedMoveBlock.start_sec;
        const dup = Object.assign({}, selectedMoveBlock, {
            id: 'move_' + Date.now(),
            start_sec: selectedMoveBlock.end_sec,
            end_sec: Math.min(activeChoreoData.duration, selectedMoveBlock.end_sec + dur)
        });
        tracks.push(dup);
        tracks.sort((a, b) => a.start_sec - b.start_sec);
        ui.openMoveInspector(selectedMoveChannel, dup);
    });

    if (inspDelBtn) inspDelBtn.addEventListener('click', () => {
        if (!selectedMoveBlock || !activeChoreoData) return;
        const tracks = activeChoreoData.tracks[selectedMoveChannel] || [];
        const idx = tracks.findIndex(b => b.id === selectedMoveBlock.id);
        if (idx !== -1) {
            tracks.splice(idx, 1);
        }
        ui.closeMoveInspector();
    });

    // Inspector dynamic input delegator
    if (inspDynamicCtrls) {
        inspDynamicCtrls.addEventListener('input', (e) => {
            if (!selectedMoveBlock) return;
            const id = e.target.id;
            const val = e.target.value;

            if (id === 'inspStartSec') {
                selectedMoveBlock.start_sec = parseFloat(val) || 0;
                ui.renderTimeline();
            } else if (id === 'inspEndSec') {
                selectedMoveBlock.end_sec = parseFloat(val) || 0;
                ui.renderTimeline();
            } else if (id === 'inspBasePose') {
                selectedMoveBlock.pose_name = val;
                ui.renderTimeline();
            } else if (id === 'inspHeadPitch') {
                selectedMoveBlock.head_pitch = val;
                ui.renderTimeline();
            } else if (id === 'inspGantryMode') {
                selectedMoveBlock.mode = val;
                ui.renderTimeline();
            } else if (id === 'inspTransSlider') {
                selectedMoveBlock.transition_sec = parseFloat(val) || 0.5;
                const v = document.getElementById('inspTransVal');
                if (v) v.innerText = `${parseFloat(val).toFixed(1)}s`;
                ui.renderTimeline();
            } else if (id === 'inspS7Slider') {
                selectedMoveBlock.target_deg = parseFloat(val);
                const v = document.getElementById('inspS7Val');
                if (v) v.innerText = `${val > 0 ? '+' : ''}${val}°`;
                ui.renderTimeline();
            } else if (id === 'inspS8Slider') {
                selectedMoveBlock.target_pos = parseInt(val, 10);
                const v = document.getElementById('inspS8Val');
                if (v) v.innerText = `${val}`;
                ui.renderTimeline();
            } else if (id === 'inspGrooveSlider') {
                selectedMoveBlock.groove_intensity = parseFloat((parseInt(val, 10) / 100).toFixed(2));
                const v = document.getElementById('inspGrooveVal');
                if (v) v.innerText = `${val}%`;
                ui.renderTimeline();
            } else if (id === 'inspTiltSlider') {
                selectedMoveBlock.tilt_deg = parseFloat(val);
                const v = document.getElementById('inspTiltVal');
                if (v) v.innerText = `${val > 0 ? '+' : ''}${val}°`;
                ui.renderTimeline();
            } else if (id === 'inspLyricTextInput') {
                selectedMoveBlock.text = val;
                selectedMoveBlock.name = val;
                selectedMoveBlock.is_user_edited = true;
                ui.renderTimeline();
            } else if (id === 'inspLyricType') {
                selectedMoveBlock.type = val;
                selectedMoveBlock.is_user_edited = true;
                if (val === 'breath') {
                    selectedMoveBlock.text = '[breath]';
                    selectedMoveBlock.name = 'Breath Inhale';
                }
                ui.renderTimeline();
            }
        });

        inspDynamicCtrls.addEventListener('change', (e) => {
            if (!selectedMoveBlock) return;
            const id = e.target.id;
            const val = e.target.value;
            if (id === 'inspLyricType') {
                selectedMoveBlock.type = val;
                selectedMoveBlock.is_user_edited = true;
                if (val === 'breath') {
                    selectedMoveBlock.text = '[breath]';
                    selectedMoveBlock.name = 'Breath Inhale';
                }
                ui.renderTimeline();
            } else if (id === 'inspUserOverride') {
                selectedMoveBlock.user_override = e.target.checked;
                ui.renderTimeline();
            } else if (id === 'inspBounceEnabled') {
                if (!selectedMoveBlock.bounce_modifier) {
                    selectedMoveBlock.bounce_modifier = { enabled: true, intensity: 0.12, target: 'body_bounce' };
                } else {
                    if (selectedMoveBlock.bounce_modifier.target === 'hip_sway') {
                        selectedMoveBlock.bounce_modifier.target = 'body_bounce';
                    }
                }
                selectedMoveBlock.bounce_modifier.enabled = e.target.checked;
                selectedMoveBlock.is_user_edited = true;
                ui.renderTimeline();
            } else if (id === 'inspBasePose' || id === 'inspHeadPitch' || id === 'inspGantryMode') {
                ui.renderTimeline();
            }
        });

        inspDynamicCtrls.addEventListener('click', (e) => {
            if (!selectedMoveBlock) return;

            const vocalStyleBtn = e.target.closest('.insp-vocal-style-btn');
            if (vocalStyleBtn) {
                const st = vocalStyleBtn.getAttribute('data-style');
                selectedMoveBlock.style = st;
                ui.openMoveInspector(selectedMoveChannel, selectedMoveBlock);
                ui.renderTimeline();
                return;
            }

            const nudgeBtn = e.target.closest('.insp-nudge-btn');
            if (nudgeBtn) {
                const nudge = parseFloat(nudgeBtn.getAttribute('data-nudge') || '0');
                const dur = Math.max(0.1, selectedMoveBlock.end_sec - selectedMoveBlock.start_sec);
                selectedMoveBlock.start_sec = Math.max(0, parseFloat((selectedMoveBlock.start_sec + nudge).toFixed(1)));
                selectedMoveBlock.end_sec = parseFloat((selectedMoveBlock.start_sec + dur).toFixed(1));
                ui.openMoveInspector(selectedMoveChannel, selectedMoveBlock);
                return;
            }

            const snapBtn = e.target.closest('#inspSnapBeatBtn');
            if (snapBtn && activeChoreoData && activeChoreoData.beat_times) {
                const bts = activeChoreoData.beat_times;
                let closest = bts[0] || 0;
                let minDiff = 9999;
                bts.forEach(bt => {
                    const diff = Math.abs(bt - selectedMoveBlock.start_sec);
                    if (diff < minDiff) { minDiff = diff; closest = bt; }
                });
                const dur = Math.max(0.1, selectedMoveBlock.end_sec - selectedMoveBlock.start_sec);
                selectedMoveBlock.start_sec = parseFloat(closest.toFixed(2));
                selectedMoveBlock.end_sec = parseFloat((closest + dur).toFixed(2));
                ui.openMoveInspector(selectedMoveChannel, selectedMoveBlock);
                return;
            }

            const s7Preset = e.target.closest('.insp-s7-preset');
            if (s7Preset) {
                const deg = parseFloat(s7Preset.getAttribute('data-deg') || '0');
                selectedMoveBlock.target_deg = deg;
                const sl = document.getElementById('inspS7Slider');
                const v = document.getElementById('inspS7Val');
                if (sl) sl.value = deg;
                if (v) v.innerText = `${deg > 0 ? '+' : ''}${deg}°`;
                ui.renderTimeline();
                return;
            }

            const s8Preset = e.target.closest('.insp-s8-preset');
            if (s8Preset) {
                const pos = parseInt(s8Preset.getAttribute('data-pos') || '2400', 10);
                selectedMoveBlock.target_pos = pos;
                const sl = document.getElementById('inspS8Slider');
                const v = document.getElementById('inspS8Val');
                if (sl) sl.value = pos;
                if (v) v.innerText = `${pos}`;
                ui.renderTimeline();
                return;
            }

            const groovePreset = e.target.closest('.insp-groove-preset');
            if (groovePreset) {
                const gVal = parseInt(groovePreset.getAttribute('data-val') || '50', 10);
                selectedMoveBlock.groove_intensity = parseFloat((gVal / 100).toFixed(2));
                const sl = document.getElementById('inspGrooveSlider');
                const v = document.getElementById('inspGrooveVal');
                if (sl) sl.value = gVal;
                if (v) v.innerText = `${gVal}%`;
                ui.renderTimeline();
                return;
            }

            const tiltPreset = e.target.closest('.insp-tilt-preset');
            if (tiltPreset) {
                const tDeg = parseFloat(tiltPreset.getAttribute('data-deg') || '0');
                selectedMoveBlock.tilt_deg = tDeg;
                const sl = document.getElementById('inspTiltSlider');
                const v = document.getElementById('inspTiltVal');
                if (sl) sl.value = tDeg;
                if (v) v.innerText = `${tDeg > 0 ? '+' : ''}${tDeg}°`;
                ui.renderTimeline();
                return;
            }
        });
    }

    // Poses Studio Interaction
    const posesContainer = document.getElementById('bbPosesListContainer');
    const previewPoseBtn = document.getElementById('bbPreviewPoseBtn');
    const capturePoseBtn = document.getElementById('bbCapturePoseBtn');
    const savePoseBtn = document.getElementById('bbSavePoseBtn');
    const newPoseBtn = document.getElementById('bbNewPoseBtn');

    if (posesContainer) {
        posesContainer.addEventListener('click', (e) => {
            const poseItem = e.target.closest('.bb-pose-item');
            if (poseItem) {
                const pName = poseItem.getAttribute('data-pose');
                if (pName) {
                    setSelectedPoseName(pName);
                    ui.renderPosesList();
                }
            }
        });
    }

    function handlePoseSliderInput() {
        const uiPan = parseFloat(document.getElementById('bbSliderPan')?.value || '50');
        const uiLift = parseFloat(document.getElementById('bbSliderLift')?.value || '50');
        const uiElbow = parseFloat(document.getElementById('bbSliderElbow')?.value || '50');
        const uiWristF = parseFloat(document.getElementById('bbSliderWristFlex')?.value || '50');
        const uiWristR = parseFloat(document.getElementById('bbSliderWristRoll')?.value || '50');

        const rawPan = (uiPan * 2.0) - 100.0;
        const rawLift = (uiLift * 2.0) - 100.0;
        const rawElbow = (uiElbow * 2.0) - 100.0;
        const rawWristF = (uiWristF * 2.0) - 100.0;
        const rawWristR = (uiWristR * 2.0) - 100.0;

        ui.updatePoseSliders({
            shoulder_pan: rawPan,
            shoulder_lift: rawLift,
            elbow_flex: rawElbow,
            wrist_flex: rawWristF,
            wrist_roll: rawWristR
        });
    }

    ['bbSliderPan', 'bbSliderLift', 'bbSliderElbow', 'bbSliderWristFlex', 'bbSliderWristRoll'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', handlePoseSliderInput);
    });

    if (previewPoseBtn) previewPoseBtn.addEventListener('click', () => {
        api.previewBeatBanditPose(currentCustomPoseJoints).catch(() => {});
    });

    if (capturePoseBtn) capturePoseBtn.addEventListener('click', () => {
        const btn = document.getElementById('bbCapturePoseBtn');
        if (btn) btn.innerText = '⌛ CAPTURING...';
        api.captureBeatBanditPose(selectedPoseName)
            .then(r => r.json())
            .then(d => {
                if (d.pose && activeChoreoData) {
                    activeChoreoData.poses[selectedPoseName] = d.pose;
                    ui.updatePoseSliders(d.pose);
                    api.sendPlaySound({ kind: 'smw_save_menu' }).catch(() => {});
                }
                if (btn) btn.innerText = '🦾 CAPTURE FROM ARM';
            })
            .catch(() => {
                if (btn) btn.innerText = '🦾 CAPTURE FROM ARM';
            });
    });

    if (savePoseBtn) savePoseBtn.addEventListener('click', () => {
        if (!activeChoreoData) return;
        if (!activeChoreoData.poses) activeChoreoData.poses = {};
        activeChoreoData.poses[selectedPoseName] = Object.assign({}, currentCustomPoseJoints);
        saveCurrentChoreography();
        ui.renderPosesList();
    });

    if (newPoseBtn) newPoseBtn.addEventListener('click', () => {
        if (!activeChoreoData) return;
        if (!activeChoreoData.poses) activeChoreoData.poses = {};
        const count = Object.keys(activeChoreoData.poses).length + 1;
        const newName = `custom_${count}`;
        activeChoreoData.poses[newName] = Object.assign({}, currentCustomPoseJoints);
        setSelectedPoseName(newName);
        ui.renderPosesList();
    });

    // Settings Studio Interaction
    const saveSettingsBtn = document.getElementById('bbSaveSettingsBtn');
    const resetSettingsBtn = document.getElementById('bbResetSettingsBtn');

    function handleSettingsSliderInput() {
        if (!activeChoreoData) return;
        if (!activeChoreoData.settings) activeChoreoData.settings = {};

        const elGate = document.getElementById('bbSliderJawGate');
        const elMaxO = document.getElementById('bbSliderJawMax');
        const elNod = document.getElementById('bbSliderNodDepth');
        const elVib = document.getElementById('bbSliderVibrato');
        const elSpd = document.getElementById('bbSliderGantrySpeed');
        const elAgil = document.getElementById('bbSliderAgility');

        if (!elGate || !elMaxO || !elNod || !elVib || !elSpd || !elAgil) {
            console.error('Missing Section 4 slider element in DOM');
            return;
        }

        const gate = parseFloat(elGate.value);
        const maxO = parseFloat(elMaxO.value);
        const nod = parseFloat(elNod.value);
        const vib = parseFloat(elVib.value);
        const spd = parseInt(elSpd.value, 10);
        const agil = parseFloat(elAgil.value);

        activeChoreoData.settings.jaw_gate_threshold = gate;
        activeChoreoData.settings.jaw_max_open = maxO;
        activeChoreoData.settings.head_nod_depth = nod;
        activeChoreoData.settings.vibrato_amplitude = vib;
        activeChoreoData.settings.gantry_default_speed = spd;
        if (!activeChoreoData.settings.joint_alphas) activeChoreoData.settings.joint_alphas = {};
        activeChoreoData.settings.joint_alphas.wrist_flex = agil;

        ui.renderSettingsView();
    }

    function handleProbabilitiesSliderInput() {
        if (!activeProbabilitiesData) {
            console.error('FAIL-FAST: activeProbabilitiesData is not loaded from backend');
            ui.setHeaderAlert('PROBABILITIES NOT LOADED');
            return;
        }
        const p = activeProbabilitiesData;

        // Section 1: Pedestal & Torso
        const elPedShift = document.getElementById('bbSliderPedShiftProb');
        const elTorso = document.getElementById('bbSliderTorsoCounterProb');
        const elPedLeft = document.getElementById('bbSliderPedLeftRom');
        const elPedRight = document.getElementById('bbSliderPedRightRom');

        if (!elPedShift || !elTorso || !elPedLeft || !elPedRight) {
            console.error('Missing Section 1 slider element in DOM');
            return;
        }

        const pedShiftVal = parseFloat(elPedShift.value);
        const torsoCounterVal = parseFloat(elTorso.value);
        const pedLeftVal = parseFloat(elPedLeft.value);
        const pedRightVal = parseFloat(elPedRight.value);

        if (!p.pedestal_s7) p.pedestal_s7 = {};
        p.pedestal_s7.vocal_start_shift_probability = pedShiftVal / 100.0;
        if (!p.pedestal_s7.target_rom) p.pedestal_s7.target_rom = {};
        p.pedestal_s7.target_rom.shift_left = pedLeftVal;
        p.pedestal_s7.target_rom.shift_right = pedRightVal;

        if (!p.torso_s1) p.torso_s1 = {};
        p.torso_s1.audience_counter_probability = torsoCounterVal / 100.0;

        // Section 2: Gantry & Head Tilt
        const elGanProb = document.getElementById('bbSliderGantryProb');
        const elGanDropSpd = document.getElementById('bbSliderGantryDropSpd');
        const elTiltCenter = document.getElementById('bbSliderHeadTiltCenterProb');
        const elTiltSnap = document.getElementById('bbSliderHeadTiltSnapProb');
        const elTiltRom = document.getElementById('bbSliderHeadTiltRom');
        const elRollSweep = document.getElementById('bbSliderHeadRollSweep');

        if (!elGanProb || !elGanDropSpd || !elTiltCenter || !elTiltSnap || !elTiltRom || !elRollSweep) {
            console.error('Missing Section 2 slider element in DOM');
            return;
        }

        const ganProbVal = parseFloat(elGanProb.value);
        const ganDropSpdVal = parseInt(elGanDropSpd.value, 10);
        const tiltCenterVal = parseFloat(elTiltCenter.value);
        const tiltSnapVal = parseFloat(elTiltSnap.value);
        const tiltDeltaVal = parseFloat(elTiltRom.value);
        const rollSweepVal = parseFloat(elRollSweep.value);

        if (!p.gantry_s8) p.gantry_s8 = {};
        p.gantry_s8.non_drop_move_probability = ganProbVal / 100.0;
        if (!p.gantry_s8.speeds) p.gantry_s8.speeds = {};
        p.gantry_s8.speeds.drop_glide = ganDropSpdVal;

        if (!p.head_tilt_s5) p.head_tilt_s5 = {};
        p.head_tilt_s5.center_probability = tiltCenterVal / 100.0;
        p.head_tilt_s5.snap_pulse_probability = tiltSnapVal / 100.0;
        p.head_tilt_s5.continuous_roll_probability = Math.max(0.0, 1.0 - (p.head_tilt_s5.center_probability + p.head_tilt_s5.snap_pulse_probability));
        p.head_tilt_s5.snap_pulse_left_rom = 50.0 - tiltDeltaVal;
        p.head_tilt_s5.snap_pulse_right_rom = 50.0 + tiltDeltaVal;
        p.head_tilt_s5.snap_pulse_duration_sec = 0.8;
        p.head_tilt_s5.continuous_roll_amplitude_rom = rollSweepVal;
        p.head_tilt_s5.continuous_roll_freq_hz = 1.0;
        p.head_tilt_s5.center_rom = 50.0;

        // Section 3: Climax Posture
        const elMaxArches = document.getElementById('bbSliderMaxArches');
        const elMinSep = document.getElementById('bbSliderMinSeparation');

        if (!elMaxArches || !elMinSep) {
            console.error('Missing Section 3 slider element in DOM');
            return;
        }

        const maxArchesVal = parseInt(elMaxArches.value, 10);
        const minSepVal = parseInt(elMinSep.value, 10);

        if (!p.spine_gaze) p.spine_gaze = {};
        p.spine_gaze.max_climax_arches = maxArchesVal;
        p.spine_gaze.min_separation_bars = minSepVal;

        ui.renderSettingsView();
    }

    ['bbSliderJawGate', 'bbSliderJawMax', 'bbSliderNodDepth', 'bbSliderVibrato', 'bbSliderGantrySpeed', 'bbSliderAgility'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', handleSettingsSliderInput);
    });

    ['bbSliderPedShiftProb', 'bbSliderTorsoCounterProb', 'bbSliderPedLeftRom', 'bbSliderPedRightRom', 'bbSliderGantryProb', 'bbSliderGantryDropSpd', 'bbSliderHeadTiltCenterProb', 'bbSliderHeadTiltSnapProb', 'bbSliderHeadTiltRom', 'bbSliderHeadRollSweep', 'bbSliderMaxArches', 'bbSliderMinSeparation'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', handleProbabilitiesSliderInput);
    });

    if (saveSettingsBtn) saveSettingsBtn.addEventListener('click', () => saveAndRecompileSettings());
    if (resetSettingsBtn) resetSettingsBtn.addEventListener('click', () => {
        if (activeChoreoData) {
            activeChoreoData.settings = {
                jaw_gate_threshold: 0.18,
                jaw_max_open: 45.0,
                head_nod_depth: 6.0,
                vibrato_amplitude: 20.0,
                gantry_default_speed: 800,
                joint_alphas: { shoulder_pan: 0.20, shoulder_lift: 0.18, elbow_flex: 0.22, wrist_flex: 0.35, wrist_roll: 0.28 }
            };
        }
        setActiveProbabilitiesData({
            pedestal_s7: { vocal_start_shift_probability: 0.30, target_rom: { shift_left: 42.0, shift_right: 58.0, center: 50.0 }, transition_beats: { vocal_shift: 1.0, return_center: 2.0, hold: 1.0 } },
            gantry_s8: { non_drop_move_probability: 0.65, move_type_probabilities: { full_glide: 0.40, early_step: 0.30, late_step: 0.30 }, drop_targets_rom: [85.0, 15.0], normal_targets_rom_left: [15.0, 40.0], normal_targets_rom_right: [60.0, 85.0], speeds: { drop_glide: 700, drop_hold: 600, hold: 250, min_glide: 350, max_glide: 700 } },
            torso_s1: { audience_counter_probability: 0.80 },
            head_tilt_s5: { center_probability: 0.70, snap_pulse_probability: 0.20, continuous_roll_probability: 0.10, snap_pulse_left_rom: 42.0, snap_pulse_right_rom: 58.0, snap_pulse_duration_sec: 0.8, continuous_roll_amplitude_rom: 8.0, continuous_roll_freq_hz: 1.0, center_rom: 50.0 },
            neck_pitch_s4: { up_probability: 0.15, down_probability: 0.05, level_probability: 0.80, pitch_up_rom: 50.0, pitch_down_rom: 85.0, pitch_level_rom: 70.0 },
            spine_gaze: { max_climax_arches: 2, min_separation_bars: 4 },
            bounce_modifier: { default_intensity: 0.12, targets: ["hip_sway", "body_bounce", "head_bob"] }
        });
        ui.renderSettingsView();
    });

    // 5. Tab 4: Power & Backend Tools
    // View 1: Main Launcher
    const backendPowerMenuBtn = document.getElementById('backendPowerMenuBtn');
    const backendConfigMenuBtn = document.getElementById('backendConfigMenuBtn');

    if (backendPowerMenuBtn) backendPowerMenuBtn.addEventListener('click', () => ui.openBackendSubView('power'));
    if (backendConfigMenuBtn) backendConfigMenuBtn.addEventListener('click', () => ui.openBackendSubView('config'));

    // View 2: Power Management
    const powerBackBtn = document.getElementById('powerBackBtn');
    const masterDaemonBtn = document.getElementById('masterDaemonBtn');
    const wifiRestoreBtn = document.getElementById('wifiRestoreBtn');
    const pi500PowerOnBtn = document.getElementById('pi500PowerOnBtn');
    const wifiDisableBtn = document.getElementById('wifiDisableBtn');
    const emergencyKillBtn = document.getElementById('emergencyKillBtn');

    if (powerBackBtn) powerBackBtn.addEventListener('click', () => ui.openBackendSubView('main'));
    if (masterDaemonBtn) masterDaemonBtn.addEventListener('click', () => triggerPi500MasterDaemonRestart());
    if (wifiRestoreBtn) wifiRestoreBtn.addEventListener('click', () => triggerWifiRestore());
    if (pi500PowerOnBtn) pi500PowerOnBtn.addEventListener('click', () => triggerPi500PowerOn());
    if (wifiDisableBtn) wifiDisableBtn.addEventListener('click', () => triggerWifiDisable());
    if (emergencyKillBtn) emergencyKillBtn.addEventListener('click', () => triggerEmergencyKillAll());

    // View 3: Config Management
    const configBackBtn = document.getElementById('configBackBtn');
    const cfgSensLow = document.getElementById('cfgSensLow');
    const cfgSensNorm = document.getElementById('cfgSensNorm');
    const cfgSensHi = document.getElementById('cfgSensHi');
    const cfgVol50 = document.getElementById('cfgVol50');
    const cfgVol75 = document.getElementById('cfgVol75');
    const cfgVol100 = document.getElementById('cfgVol100');
    const cfgVol150 = document.getElementById('cfgVol150');
    const cfgSpeed35 = document.getElementById('cfgSpeed35');
    const cfgSpeed50 = document.getElementById('cfgSpeed50');
    const cfgSpeed70 = document.getElementById('cfgSpeed70');
    const cfgSpeed100 = document.getElementById('cfgSpeed100');
    const cfgArm03 = document.getElementById('cfgArm03');
    const cfgArm06 = document.getElementById('cfgArm06');
    const cfgArm10 = document.getElementById('cfgArm10');
    const cfgArm15 = document.getElementById('cfgArm15');

    if (configBackBtn) configBackBtn.addEventListener('click', () => ui.openBackendSubView('main'));
    if (cfgSensLow) cfgSensLow.addEventListener('click', () => applyConfig('clack_threshold', 7500));
    if (cfgSensNorm) cfgSensNorm.addEventListener('click', () => applyConfig('clack_threshold', 5200));
    if (cfgSensHi) cfgSensHi.addEventListener('click', () => applyConfig('clack_threshold', 3500));

    if (cfgVol50) cfgVol50.addEventListener('click', () => applyConfig('volume_pct', 50));
    if (cfgVol75) cfgVol75.addEventListener('click', () => applyConfig('volume_pct', 75));
    if (cfgVol100) cfgVol100.addEventListener('click', () => applyConfig('volume_pct', 100));
    if (cfgVol150) cfgVol150.addEventListener('click', () => applyConfig('volume_pct', 150));

    if (cfgSpeed35) cfgSpeed35.addEventListener('click', () => applyConfig('rover_max_speed_pct', 35));
    if (cfgSpeed50) cfgSpeed50.addEventListener('click', () => applyConfig('rover_max_speed_pct', 50));
    if (cfgSpeed70) cfgSpeed70.addEventListener('click', () => applyConfig('rover_max_speed_pct', 70));
    if (cfgSpeed100) cfgSpeed100.addEventListener('click', () => applyConfig('rover_max_speed_pct', 100));

    if (cfgArm03) cfgArm03.addEventListener('click', () => applyConfig('arm_speed_sec', 0.3));
    if (cfgArm06) cfgArm06.addEventListener('click', () => applyConfig('arm_speed_sec', 0.6));
    if (cfgArm10) cfgArm10.addEventListener('click', () => applyConfig('arm_speed_sec', 1.0));
    if (cfgArm15) cfgArm15.addEventListener('click', () => applyConfig('arm_speed_sec', 1.5));
}

// ==========================================
// Initialization on Load
// ==========================================

function initApp() {
    bindEventListeners();

    try {
        const params = new URLSearchParams(window.location.search);
        const savedTab = params.get('tab') || localStorage.getItem('active_tab') || 'apps';
        if (['gantry', 'controls', 'apps', 'power'].includes(savedTab)) {
            ui.switchTab(savedTab);
        }
        const savedAppsSub = params.get('apps_sub') || localStorage.getItem('apps_subview') || 'launcher';
        ui.openAppsSubView(savedAppsSub);
        fetchBeatBanditTracks();
        const reqTrack = params.get('track');
        if (reqTrack) {
            setSelectedBeatBanditTrackId(reqTrack);
            loadChoreographyForTrack(reqTrack);
        }
        if (savedAppsSub === 'beat_bandit') {
            const savedStudioTab = params.get('bb_tab') || 'player';
            if (['player', 'timeline', 'poses', 'settings'].includes(savedStudioTab)) {
                ui.switchBbStudioTab(savedStudioTab);
                if (savedStudioTab !== 'player') {
                    loadChoreographyForTrack(reqTrack || selectedBeatBanditTrackId);
                }
            }
        }
        const savedBackendSub = params.get('backend_sub') || localStorage.getItem('backend_subview') || 'main';
        ui.openBackendSubView(savedBackendSub);
        const savedMode = params.get('mode') || localStorage.getItem('apps_mode') || 'controls';
        ui.switchAppsMode(savedMode);
        const savedPresetMode = params.get('preset_mode') || localStorage.getItem('preset_mode') || 'normal';
        if (['normal', 'demo', 'angry', 'dance'].includes(savedPresetMode)) {
            ui.setPresetsMode(savedPresetMode);
        }
        const savedBbPage = parseInt(params.get('bb_page') || localStorage.getItem('bb_page') || '0', 10);
        if (!isNaN(savedBbPage)) setBeatBanditTrackPage(savedBbPage);
        ui.renderBeatBanditTracksList(cachedBeatBanditTracks);
    } catch(e) {}

    // Start sequential telemetry loop
    pollTelemetry();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
