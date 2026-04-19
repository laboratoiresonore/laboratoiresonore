<h1 align="center">Le Laboratoire Sonore</h1>

<p align="center">
  <em>A creative research facility. We make the tools we wish existed.</em>
</p>

<p align="center">
  <a href="https://github.com/laboratoiresonore/spellcaster"><img alt="Spellcaster" src="https://img.shields.io/badge/Flagship-Spellcaster-7c3aed?style=for-the-badge"/></a>
  <a href="https://www.reddit.com/r/Spellcaster_Studio/"><img alt="Reddit" src="https://img.shields.io/badge/subreddit-Spellcaster__Studio-ff4500?style=for-the-badge&logo=reddit&logoColor=white"/></a>
</p>

---

## What we're working on

### [Spellcaster](https://github.com/laboratoiresonore/spellcaster) — middleware between ComfyUI and everything else

A GIMP + Darktable plugin and standalone chat UI that hides 24 ComfyUI custom
node packs and 9 model architectures behind 69 one-click tools. It auto-detects
your hardware, your models, and your taste — so you never pick a sampler, write
a negative prompt, or learn what a VAE is.

- **[Spellcaster](https://github.com/laboratoiresonore/spellcaster)** — the app (Python, GPL-2.0)
- **[ComfyUI-Spellcaster](https://github.com/laboratoiresonore/ComfyUI-Spellcaster)** — 4 architecture-aware ComfyUI nodes we extracted from the app, installable on its own

### The Whimweaver ecosystem — AI companions for writing and play

A separate family of tools (private while it's still cooking): **Whimweaver**
(interactive novelist), **Whimspider** (local AI companion), **Beatweaver**
(audio side), **Whimweaver-ST** (SillyTavern integration).

---

## How we ship

- **Fully local.** Every tool runs on your own GPU. Nothing calls out to OpenAI,
  Anthropic, Google, or us. The only network traffic is between your editor and
  your own ComfyUI server — which can be `localhost`.
- **Auto-everything.** Installers that detect your hardware and download the right
  models. Auto-updaters with 3-tier recovery. Calibration wizards that tune
  defaults to your taste via optometrist-style A/B testing.
- **Zero duplication.** The same `spellcaster_core/` library powers the GIMP plugin,
  the Wizard Guild chat UI, and the standalone ComfyUI node pack. One source of truth,
  three deployments.

---

## Stack

**Languages:** Python 3.12 · TypeScript · React · JavaScript
**AI:** ComfyUI · Flux 2 Klein · SDXL · Illustrious · Chroma · Wan 2.2 · LTX · Qwen3 VL
**Editors:** GIMP 3 · Darktable · DaVinci Resolve · SillyTavern
**Platforms:** Windows · macOS · Linux

---

<p align="center">
  <sub>Based in France. Open-source when we can, private when we can't, always local.</sub>
</p>
