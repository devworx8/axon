/* ══════════════════════════════════════════════════════════════
   Axon — Voice Boot Sound (Web Audio API synth)
   Cinematic JARVIS-style "system coming online" tone
   ══════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  let _audioCtx = null;

  function getCtx() {
    if (!_audioCtx) {
      _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (_audioCtx.state === 'suspended') {
      _audioCtx.resume().catch(() => {});
    }
    return _audioCtx;
  }

  /**
   * Robotic reactor power-up sequence (~6 seconds).
   * Mechanical servo whirs, digital stutter steps, low power hum,
   * culminating in a sustained reactor online tone.
   */
  function playBootSound() {
    try {
      const ctx = getCtx();
      const now = ctx.currentTime;
      const master = ctx.createGain();
      master.gain.setValueAtTime(0.20, now);
      master.connect(ctx.destination);

      // ── 1. Servo whir: mechanical startup (0 – 2.5s) ──
      // Square wave stepping up in discrete frequency jumps
      const servo = ctx.createOscillator();
      const servoGain = ctx.createGain();
      servo.type = 'square';
      servo.frequency.setValueAtTime(40, now);
      servo.frequency.setValueAtTime(55, now + 0.4);
      servo.frequency.setValueAtTime(72, now + 0.8);
      servo.frequency.setValueAtTime(90, now + 1.2);
      servo.frequency.setValueAtTime(110, now + 1.6);
      servo.frequency.setValueAtTime(130, now + 2.0);
      servoGain.gain.setValueAtTime(0, now);
      servoGain.gain.linearRampToValueAtTime(0.06, now + 0.15);
      servoGain.gain.setValueAtTime(0.08, now + 0.4);
      servoGain.gain.setValueAtTime(0.06, now + 0.42);
      servoGain.gain.setValueAtTime(0.09, now + 0.8);
      servoGain.gain.setValueAtTime(0.06, now + 0.82);
      servoGain.gain.setValueAtTime(0.10, now + 1.2);
      servoGain.gain.setValueAtTime(0.06, now + 1.22);
      servoGain.gain.setValueAtTime(0.10, now + 1.6);
      servoGain.gain.setValueAtTime(0.05, now + 1.62);
      servoGain.gain.setValueAtTime(0.08, now + 2.0);
      servoGain.gain.linearRampToValueAtTime(0, now + 2.5);
      const servoFilter = ctx.createBiquadFilter();
      servoFilter.type = 'bandpass';
      servoFilter.frequency.value = 200;
      servoFilter.Q.value = 5;
      servo.connect(servoFilter).connect(servoGain).connect(master);
      servo.start(now);
      servo.stop(now + 2.6);

      // ── 2. Digital stutter beeps (0.5 – 3.5s) ──
      // Short repeating tones like a machine self-testing
      const beepFreqs = [220, 330, 275, 440, 350, 550, 440, 660];
      beepFreqs.forEach((freq, i) => {
        const t = now + 0.5 + i * 0.38;
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square';
        osc.frequency.setValueAtTime(freq, t);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.06, t + 0.02);
        g.gain.setValueAtTime(0.06, t + 0.08);
        g.gain.linearRampToValueAtTime(0, t + 0.14);
        const f = ctx.createBiquadFilter();
        f.type = 'bandpass';
        f.frequency.value = freq;
        f.Q.value = 8;
        osc.connect(f).connect(g).connect(master);
        osc.start(t);
        osc.stop(t + 0.16);
      });

      // ── 3. Low power hum building up (0.3 – 4.5s) ──
      const hum = ctx.createOscillator();
      const humGain = ctx.createGain();
      hum.type = 'sawtooth';
      hum.frequency.setValueAtTime(48, now + 0.3);
      hum.frequency.linearRampToValueAtTime(60, now + 2.0);
      hum.frequency.linearRampToValueAtTime(72, now + 3.5);
      hum.frequency.linearRampToValueAtTime(80, now + 4.5);
      humGain.gain.setValueAtTime(0, now + 0.3);
      humGain.gain.linearRampToValueAtTime(0.12, now + 1.0);
      humGain.gain.linearRampToValueAtTime(0.20, now + 2.5);
      humGain.gain.linearRampToValueAtTime(0.25, now + 3.5);
      humGain.gain.linearRampToValueAtTime(0.15, now + 4.3);
      humGain.gain.linearRampToValueAtTime(0, now + 4.8);
      const humFilter = ctx.createBiquadFilter();
      humFilter.type = 'lowpass';
      humFilter.frequency.setValueAtTime(120, now + 0.3);
      humFilter.frequency.linearRampToValueAtTime(300, now + 2.5);
      humFilter.frequency.linearRampToValueAtTime(500, now + 4.0);
      humFilter.Q.value = 3;
      hum.connect(humFilter).connect(humGain).connect(master);
      hum.start(now + 0.3);
      hum.stop(now + 4.9);

      // ── 4. Reactor core charging tone (2.5 – 5.5s) ──
      // Triangle wave slowly rising — the core powering up
      const core = ctx.createOscillator();
      const coreGain = ctx.createGain();
      core.type = 'triangle';
      core.frequency.setValueAtTime(80, now + 2.5);
      core.frequency.linearRampToValueAtTime(140, now + 3.5);
      core.frequency.linearRampToValueAtTime(200, now + 4.5);
      core.frequency.linearRampToValueAtTime(220, now + 5.5);
      coreGain.gain.setValueAtTime(0, now + 2.5);
      coreGain.gain.linearRampToValueAtTime(0.10, now + 3.0);
      coreGain.gain.linearRampToValueAtTime(0.18, now + 4.0);
      coreGain.gain.linearRampToValueAtTime(0.22, now + 5.0);
      coreGain.gain.linearRampToValueAtTime(0.10, now + 5.4);
      coreGain.gain.linearRampToValueAtTime(0, now + 5.8);
      const coreFilter = ctx.createBiquadFilter();
      coreFilter.type = 'bandpass';
      coreFilter.frequency.setValueAtTime(180, now + 2.5);
      coreFilter.frequency.linearRampToValueAtTime(400, now + 5.0);
      coreFilter.Q.value = 2;
      core.connect(coreFilter).connect(coreGain).connect(master);
      core.start(now + 2.5);
      core.stop(now + 5.9);

      // ── 5. "Online" confirmation tone (4.5 – 6.2s) ──
      // Single clean sine — system ready
      const ready = ctx.createOscillator();
      const readyGain = ctx.createGain();
      ready.type = 'sine';
      ready.frequency.setValueAtTime(440, now + 4.5); // A4
      readyGain.gain.setValueAtTime(0, now + 4.5);
      readyGain.gain.linearRampToValueAtTime(0.14, now + 4.65);
      readyGain.gain.linearRampToValueAtTime(0.12, now + 5.2);
      readyGain.gain.exponentialRampToValueAtTime(0.01, now + 6.2);
      ready.connect(readyGain).connect(master);
      ready.start(now + 4.5);
      ready.stop(now + 6.3);

      // ── 6. Static/digital texture throughout (0 – 3s) ──
      const noiseLen = 3.0;
      const noiseBuf = ctx.createBuffer(1, ctx.sampleRate * noiseLen, ctx.sampleRate);
      const noiseData = noiseBuf.getChannelData(0);
      for (let i = 0; i < noiseData.length; i++) {
        // Stepped noise — quantized to sound digital
        noiseData[i] = Math.round((Math.random() * 2 - 1) * 4) / 4 * 0.3;
      }
      const noise = ctx.createBufferSource();
      noise.buffer = noiseBuf;
      const noiseGain = ctx.createGain();
      noiseGain.gain.setValueAtTime(0.03, now);
      noiseGain.gain.linearRampToValueAtTime(0.05, now + 0.8);
      noiseGain.gain.linearRampToValueAtTime(0.04, now + 1.5);
      noiseGain.gain.exponentialRampToValueAtTime(0.005, now + 3.0);
      const noiseBand = ctx.createBiquadFilter();
      noiseBand.type = 'highpass';
      noiseBand.frequency.value = 2000;
      noiseBand.Q.value = 0.5;
      noise.connect(noiseBand).connect(noiseGain).connect(master);
      noise.start(now);
      noise.stop(now + 3.0);

      // ── Master envelope ──
      master.gain.setValueAtTime(0.20, now);
      master.gain.linearRampToValueAtTime(0.20, now + 5.5);
      master.gain.linearRampToValueAtTime(0, now + 6.5);

    } catch (_) {
      // Web Audio not available — silently skip
    }
  }

  window.axonVoiceBootSound = { play: playBootSound };

  /**
   * Reactor power-down sequence (~3 seconds).
   * Descending tone, servo wind-down, digital stutter fading out.
   */
  function playSleepSound() {
    try {
      const ctx = getCtx();
      const now = ctx.currentTime;
      const master = ctx.createGain();
      master.gain.setValueAtTime(0.18, now);
      master.connect(ctx.destination);

      // ── 1. Descending reactor tone (0 – 2.5s) ──
      const tone = ctx.createOscillator();
      const toneGain = ctx.createGain();
      tone.type = 'sine';
      tone.frequency.setValueAtTime(660, now);
      tone.frequency.exponentialRampToValueAtTime(80, now + 2.5);
      toneGain.gain.setValueAtTime(0.12, now);
      toneGain.gain.linearRampToValueAtTime(0.06, now + 1.5);
      toneGain.gain.linearRampToValueAtTime(0, now + 2.5);
      tone.connect(toneGain).connect(master);
      tone.start(now);
      tone.stop(now + 2.5);

      // ── 2. Servo wind-down (0.2 – 2s) ──
      const servo = ctx.createOscillator();
      const servoGain = ctx.createGain();
      servo.type = 'square';
      servo.frequency.setValueAtTime(130, now + 0.2);
      servo.frequency.setValueAtTime(110, now + 0.5);
      servo.frequency.setValueAtTime(90, now + 0.9);
      servo.frequency.setValueAtTime(72, now + 1.2);
      servo.frequency.setValueAtTime(55, now + 1.5);
      servo.frequency.setValueAtTime(40, now + 1.8);
      servoGain.gain.setValueAtTime(0.06, now + 0.2);
      servoGain.gain.linearRampToValueAtTime(0.03, now + 1.5);
      servoGain.gain.linearRampToValueAtTime(0, now + 2.0);
      const servoFilter = ctx.createBiquadFilter();
      servoFilter.type = 'bandpass';
      servoFilter.frequency.value = 180;
      servoFilter.Q.value = 4;
      servo.connect(servoFilter).connect(servoGain).connect(master);
      servo.start(now + 0.2);
      servo.stop(now + 2.0);

      // ── 3. Low hum fade-out (0 – 3s) ──
      const hum = ctx.createOscillator();
      const humGain = ctx.createGain();
      hum.type = 'triangle';
      hum.frequency.setValueAtTime(120, now);
      hum.frequency.exponentialRampToValueAtTime(45, now + 3);
      humGain.gain.setValueAtTime(0.08, now);
      humGain.gain.linearRampToValueAtTime(0, now + 3);
      hum.connect(humGain).connect(master);
      hum.start(now);
      hum.stop(now + 3);

      // ── Master fade out ──
      master.gain.linearRampToValueAtTime(0, now + 3);

    } catch (_) {
      // Web Audio not available — silently skip
    }
  }

  window.axonVoiceSleepSound = { play: playSleepSound };
})();
