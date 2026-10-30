# 雲端前台素材

本輪為學校專題研究用途的固定居民數字人畫面；沒有開放雲端新增或改造角色模型。正式商業機構採用前，須另外核對機構適用的素材及 SDK 許可，不將研究版本的資格當成所有商業用途都免費。

- AIRI 程式採 MIT License，作者 Neko Ayaka；部署庫保留原授權全文。
- Hiyori Momose (Free)：插畫 Kani Biimu、模型 Live2D。使用原包，不改設計、名稱或刪包內 ReadMe。頁面「資料與私隱 → 數字人素材」保留指定著作權聲明。
- Live2D Cubism Core：原本 AIRI SDK 下載器已使用的 Redistributable Code；保留原檔授權標頭及條款連結，不當成 MIT 程式。僅選出應用所需執行檔，不傳整套 SDK。
- ONNX Runtime Web、Hugging Face Transformers 的瀏覽器 VAD 路徑沿用 AIRI 原依賴；只用作偵測語音段落，居民辨識文字仍交給已批准的 Cloudflare Whisper。沒有將 Notebook 的 SenseVoice／Ollama 權重搬到雲端。
- `@pixi/unsafe-eval` 6.5.10（MIT）：與已安裝的 Pixi Core 同版本，官方 `install({ ShaderSystem })` 以一般函式同步 shader uniforms，令畫面可在禁止 JavaScript eval 的 CSP 下運作。不是單純跳過檢查，也沒有開放 `unsafe-eval`。原碼及授權全文保留；npm tarball SHA512 在本機回條核對。參考 [官方用法](https://api.pixijs.io/@pixi/unsafe-eval.html)。

2026-10-30 核對第一方條款：[示例素材](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)、[Hiyori 等示例使用條件](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)、[Cubism Core](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)。這份紀錄不代替各元件的原授權。
