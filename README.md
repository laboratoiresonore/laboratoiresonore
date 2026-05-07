<p align="center">
  <img src="https://github.com/laboratoiresonore/spellcaster/raw/main/assets/wizard_banner.gif" alt="Le Laboratoire Sonore" width="58%"/>
</p>

<h1 align="center">Le Laboratoire Sonore</h1>

<p align="center">
  <em>A creative research facility. We make the tools we wish existed.</em>
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster"><img alt="Spellcaster" src="https://img.shields.io/badge/AI%20Image-Spellcaster-7c3aed?style=for-the-badge"/></a>
  <a href="https://github.com/laboratoiresonore/beatweaver"><img alt="BeatWeaver" src="https://img.shields.io/badge/DJ%20Tool-BeatWeaver-f59e0b?style=for-the-badge"/></a>
  <a href="https://github.com/laboratoiresonore/ComfyUI-Spellcaster"><img alt="ComfyUI nodes" src="https://img.shields.io/badge/ComfyUI-Custom%20Nodes-5b8def?style=for-the-badge"/></a>
  <a href="https://www.reddit.com/r/Spellcaster_Studio/"><img alt="Reddit" src="https://img.shields.io/badge/subreddit-Spellcaster__Studio-ff4500?style=for-the-badge&logo=reddit&logoColor=white"/></a>
</p>

---

## What we ship

Three public projects, all 100% local, all open-source.

### 🪄 [Spellcaster](https://github.com/laboratoiresonore/spellcaster) — AI image generation, hidden behind one menu

> **Type "hair" in GIMP. It selects the hair. Perfectly. In one second.**

A middleware that turns ComfyUI from "open the graph editor + wire 40 nodes" into "click a menu item and it just works." It's a GIMP plug-in, a Darktable plug-in, a DaVinci Resolve plug-in, and a standalone chat UI — all driven by the same core library.

What's in the menu:
- 69 one-click AI tools across **selection** (SAM3 — type the thing you want selected, get a perfect mask in 1 second), **restoration** (SUPIR for old photos, face restoration, background removal, colourisation), **manipulation** (LaMa erase, IC-Light relighting, FaceID, style transfer, ControlNet anything), **3D workflows** (image → SAM3 → normal map → enhancement → blend), **animation** (WAN 2.2 image-to-video, Hunyuan, LTX), and **architecture-aware generation** (auto-detect SDXL / Flux / Klein / Illustrious / Chroma + use the right CLIP, sampler, and prompt scaffold for each).
- Across **9 model architectures** with auto-detection — you never pick a sampler, write a negative prompt, or learn what a VAE is.
- Wraps **24 ComfyUI custom-node packs** so the user never installs them by hand.

<p align="center">
  <img src="https://github.com/laboratoiresonore/spellcaster/raw/main/assets/sam3demo.png" alt="SAM3 selection demo" width="48%"/>
  <img src="https://github.com/laboratoiresonore/spellcaster/raw/main/assets/showcase_supir.png" alt="SUPIR restoration" width="48%"/>
</p>

<p align="center">
  <img src="https://github.com/laboratoiresonore/spellcaster/raw/main/assets/showcase_klein_flux2.png" alt="Klein-Flux2 generation" width="48%"/>
  <img src="https://github.com/laboratoiresonore/spellcaster/raw/main/assets/showcase_wan_breathing.gif" alt="WAN 2.2 video" width="48%"/>
</p>

Python 3.12 · GPL-2.0 · Windows / Linux. ([repo →](https://github.com/laboratoiresonore/spellcaster))

---

### 🎚️ [BeatWeaver](https://github.com/laboratoiresonore/beatweaver) — DJ overlay tool for non-musicians

A desktop app that listens to your DJ mix, detects BPM and key in real time, and lets you layer 32 hand-tuned synthesized presets on top using a Novation Launch Control XL or on-screen controls. Every pattern is authored in C and auto-transposed to the live-detected key, so your overlay never clashes with the track underneath.

- **Real-time BPM + key detection** (AudioWorklet + Krumhansl–Schmuckler tonal-hierarchy correlation) with confidence-based locking.
- **32 presets** across 4 categories (Bass, Energy, Texture, FX) × 2 banks. 6-instrument SynthFactory: acid bass, supersaw stab, arp, pad, lead, perc — with FM, sub-osc, formant filtering.
- **First-class MIDI controller integration** with hot-plug, full LED feedback, and per-preset knob mapping.
- **Per-column modulator slots** — Chorus / Phaser / Tremolo with seamless type-switching.
- **4-tier TTS announcer** (local Kobold → bundled offline-neural Companion → Electron SAPI → browser SpeechSynthesis) for hands-free preset names + key-change cues. The Companion auto-sizes a [Piper TTS](https://github.com/rhasspy/piper) voice to the host hardware on first launch — no LLM server required.
- **Pioneer-CDJ-inspired UI** with a live VU meter as the BeatWeaver backdrop.

For DJs who want to layer harmonic ear-candy without learning music theory — feed your mixer's monitor send into the laptop, hit a launch pad, you're now playing in key.

Electron · React · Tone.js · MIT · Windows / macOS / Linux. ([repo →](https://github.com/laboratoiresonore/beatweaver))

---

### 🔧 [ComfyUI-Spellcaster](https://github.com/laboratoiresonore/ComfyUI-Spellcaster) — architecture-aware ComfyUI nodes

The four architecture-aware nodes we extracted from Spellcaster, installable on their own for ComfyUI users who don't want the full menu integration. Auto-detects whether a checkpoint is SD 1.5 / SDXL / Illustrious / ZIT / Flux Dev / Flux 2 Klein / Chroma, loads the matching CLIP and VAE, samples with optimal settings, and (optionally) enhances prompts via a local LLM. **One source of truth** — the same architecture definitions power the GIMP plug-in, the Darktable plug-in, the standalone Wizard Guild chat UI, and these nodes.

[![ComfyUI Registry](https://img.shields.io/badge/ComfyUI%20Registry-Spellcaster%20Nodes-5b8def)](https://registry.comfy.org/) [![License](https://img.shields.io/github/license/laboratoiresonore/ComfyUI-Spellcaster)](https://github.com/laboratoiresonore/ComfyUI-Spellcaster/blob/main/LICENSE)

Python · ComfyUI custom nodes. ([repo →](https://github.com/laboratoiresonore/ComfyUI-Spellcaster))

---

## How we ship

- **Fully local.** Every tool runs on your own GPU. Nothing calls out to OpenAI, Anthropic, Google, or us. The only network traffic on Spellcaster is between your editor and your own ComfyUI server — which can be `localhost`. BeatWeaver doesn't talk to the network at all unless you explicitly point its TTS tier at a Kobold endpoint.
- **Auto-everything.** Installers that detect your hardware and download the right models. Auto-updaters with multi-tier recovery. Calibration wizards that tune defaults to your taste via optometrist-style A/B testing. The user shouldn't have to know what a VAE is, what a sampler is, or which key their DJ track is in.
- **Zero duplication.** The same `spellcaster_core/` library powers the GIMP plug-in, the Wizard Guild chat UI, and the standalone ComfyUI node pack — one source of truth, three deployments.
- **Boring tech, sharp products.** Python 3.12, TypeScript, React, no esoteric build tools, no SaaS lock-in. The shape of the work matters more than the stack.

---

## Stack

**Languages:** Python 3.12 · TypeScript · React · JavaScript
**AI / ML:** ComfyUI · Flux Dev / Flux 2 Klein · SDXL · Illustrious · Chroma · WAN 2.2 · LTX · SAM3 · SUPIR · IC-Light · FaceID · LaMa · Qwen3 VL
**Audio:** Tone.js · realtime-bpm-analyzer · pitchfinder · Krumhansl–Schmuckler · Novation Launch Control XL (WebMIDI)
**Editors:** GIMP 3 · Darktable · DaVinci Resolve · ComfyUI · SillyTavern
**Platforms:** Windows · macOS · Linux

---

<p align="center">
  <img src="https://github.com/laboratoiresonore/spellcaster/raw/main/assets/wizardguild.png" alt="Wizard Guild chat UI" width="68%"/>
</p>

<p align="center">
  <sub>Based in France. Open-source when we can, always local. Talk to us on <a href="https://www.reddit.com/r/Spellcaster_Studio/">r/Spellcaster_Studio</a>.</sub>
</p>
