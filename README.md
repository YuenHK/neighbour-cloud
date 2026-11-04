# 鄰伴 / Neighbour — private cloud deployment

Current service: https://neighbour-yuenhk-live.onrender.com/ . Residents enter directly; management uses the configured shared password. The former neighbour-yuenhk.onrender.com service remains suspended and must not be resumed alongside this writer.

The reviewed program runs on Render Free in Singapore with one instance and automatic deployment disabled. It uses the existing Turso Free durable databases, Cloudflare Gemma dialogue, Azure HiuMaan F0 speech, Cloudflare Whisper speech recognition, and Tavily search. No paid upgrade, quota reset, or automatic provider substitution is enabled.

## 2026-11-04: voice-driven lip sync and conversational movement are live

Current runtime `fb7bd0c1ea4cef129d80fb711fd920f9ab5aeffb`, official CLI deploy `dep-dbl9egijnfac73f9r16g`, release `avatar-performance-20261104-barrier22`; existing URL and Gemma + Microsoft HiuMaan F0 remain unchanged. The selected character and every original case, model, memory marker, control flag, ledger, event, Operations record (including VRoid) and historical quota period were retained.

The resident PCM stream now feeds one stable analysis bus into AIRI's native VRM/Live2D lip driver. The installed wLipSync worklet and WASM are served from this origin without weakening CSP. Switching analysis cannot disconnect audible playback. Speech completion closes the mouth, and gentle head/chest gestures follow conversation while respecting reduced motion and the original idle pose. No webcam or resident face tracking is enabled.

430 backend tests, 60 Node tests, network faults, Chromium/WebKit workbench flows and 36 dialogue evaluations passed for the runtime source. Frontend80 lint/typecheck/build passed and native sources were restored byte-for-byte. Actual published Miku VRM mesh expressions and Live2D mouth inputs animated in silent synthetic-PCM loopback HTTPS tests and returned to zero. Thirty-nine exact production HTTPS program/assets and auth rejection checks passed; no actual provider, microphone, playback or EP calls were made. New human lip-sync/iPhone acceptance is not claimed. Old writer exit and the sole inert new instance were independently verified before a new signed release approval.

This README and bundle update is documentation only; do not redeploy it.

## Earlier 2026-11-04: responsive resident interface


The previous runtime was `9412ad86d14a2600fee150753f188d0152a14a5e`, official CLI deploy `dep-dbl84o6tlv9c73b9agt0`, release `resident-responsive-20261104-barrier21`. The public URL is unchanged. Conversation and speech provider/model/voice IDs, selected character and stored data are preserved; the visible voice name is now “Microsoft 語音服務”.

The resident view uses proportional desktop columns instead of squeezing the avatar beside a fixed 600px chat column. Bounded grid rows and a scrollable notice area keep the composer accessible when the viewport is short or follow-up/speech errors are long. Mobile retains the translucent chat panel. Public model attribution moves into the concise top privacy menu, with active-frame/origin checks, safe public URLs and an acknowledged standalone fallback outside the chat. Original author and Live2D notices remain accessible.

The final source-matching gate passed 426 backend tests, 56 Node tests, network faults, workbench Chromium/WebKit flows and 36 dialogue evaluations. Frontend75 lint, typecheck and build passed with native source restored. A full isolated resident portal passed 12 viewport sizes, resize/draft retention, long notices with a synthetic speech failure, safe attribution messaging and chat. Thirty-five real HTTPS pages/assets matched exactly; 201 unchanged thumbnail hashes match the prior release evidence. Original cases, IDs, selected model, presentation, memory marker, controls, deletion ledger, events and all Operations records including the sealed VRoid connection matched their stopped baseline; previous quota periods were nondecreasing. No resident data, credentials or models were reimported or republished, and no real AI/audio/EP requests were used to validate this UI change. The old formal process was confirmed exited before the sole new release was approved.

This README/bundle metadata update is documentation only and does not require another deployment.

## Earlier 2026-11-04: reviewed VRoid library

Runtime commit `bfd84823d65d0f4390711ecae75bcf4cdf9ca787` was deployed with the official Render CLI as `dep-dbl7apmc6qcc73ak9reg`, release `vroid-library-20261103-barrier20`. The prior process had actually exited; only the new inert instance was present before independent data checks and release approval. This documentation update does not require another deployment.

The picker retains 26 existing curated models and adds 201 distinct reviewed VRM files from 126 VRoid creators, for 227 choices. This does not represent 20 independent library platforms or 227 Live2D models. Models were checked as original files and in native AIRI previews; blank, deformed, unsuitable and near-duplicate variants were excluded. Downloads recheck author permissions, version, size and SHA-256. Preview does not publish; the existing explicit Save action publishes through the immutable content store. Current selections remain unchanged.

The owner approved the existing cloud credential destination. VRoid credentials were transferred once over the fixed authenticated HTTPS endpoint and independently read back from durable AES-GCM storage outside Git. The program permits catalogue/resource reads and OAuth renewal, and blocks media publication, likes and account mutations. The cloud now owns token renewal; the encrypted local prior copy is preserved and cannot compete for renewal. Bounded latest-model discovery caches candidates separately from verified usable choices.

Verification included the source-matching isolated gate (426 backend tests, 54 Node tests, network faults, Chromium/WebKit flows and 36 dialogue evaluations), six operator tests, 232 exact public HTTPS assets and unauthorized API rejection. A real 19,381,084-byte cloud preview matched the previously verified public original without publishing a model. Original cases, short IDs, presentation, stored models, memory marker, controls, deletion ledger, events and pre-existing Operations records matched their stopped baseline; all previous quota periods were nondecreasing. Only the new sealed VRoid namespace was intentionally added. No Gemma, speech, real microphone, playback or EP calls were made for this release.

The owner previously accepted iPhone text, microphone and speech, session handover and physical Notebook-off digital-human use. Real mobile push delivery, EP hardware/site-vision acceptance and the goal of 20 independent compatible library sources remain outstanding. The Windows installer and Chrome troubleshooting were cancelled.

The 2026-10-31 repair fixes unsupported remote estate cache polling and self-hosts the exact ONNX runtime required for browser voice activity detection. Bounded recovery renews expired anonymous sessions and retries only requests proven not to have reached their operation/provider. Unknown outcomes retain the draft and are not blindly replayed. The workbench restores cloud-supported presentation settings, equally spaced navigation, and a compact truthful quota view.

For the original 2026-10-31 repair, the old process was confirmed stopped before the new service connected to the same stores. No resident data was reimported. The additive presentation table was independently read back; historical quotas and control flags were preserved. Fixed HTTP checks retained conversation context, returned HiuMaan audio, and recognised a synthetic Whisper sample. Those agent checks did not use a real microphone, play audio or operate EP; subsequent human acceptance is recorded above.

Native startup remains fenced; the launcher opens the new cloud URL. EP hardware requires a separate site connection and is outside this cloud repair. Keep the original local hardware files and audit intact. Future runtime deploys or restores still require stopping the sole formal writer; the in-process gate is not a distributed lease. Documentation-only commits do not require deployment.

This private repository contains program and synthetic test assets only. Resident databases, photos, memories, credentials, native models, and execution files are excluded. Private operational evidence lives outside Git. See deploy/cloud/README.zh-Hant.md and deploy/cloud/REPAIR-2026-10-31.zh-Hant.md for implementation and limitations.

## wLipSync 1.3.0 license

The native audio-analysis dependency is retained under its original MIT license:

The MIT License (MIT)

Copyright (c) 2021 hecomi
Copyright (c) 2024 Noeri Huisman

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

