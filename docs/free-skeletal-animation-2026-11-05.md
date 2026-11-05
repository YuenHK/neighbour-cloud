# 鄰伴免費骨架動畫接入

本批新增獨立的 **Rigby JSON** 動畫路線，保留 Live2D、VRM、Gemma 及 Microsoft 語音服務。這份紀錄描述候選程式及隔離驗證；正式部署版本及資料核對以本批最終交接為準。

## 免費方案與原有 Spine 的分別

AIRI 原生 Spine 播放器使用 `@esotericsoftware/spine-webgl`。Spine 官方的試用版只供評估；學校符合 Education 資格，亦不代表已獲免費 Runtime 發佈授權。因此本批沒有購買、啟用或改名包裝該 Runtime。

新播放器使用 Rigby2D 作者公開的獨立 JavaScript／WebGL 實作，固定版本為 `72bc84625fac4959e185574df12adbd33add11d6`。其原始碼標示 MIT OR Apache-2.0，JSON／binary reader 說明採獨立 clean-room 實作。實查核心及 WebGL 模組的相對 imports、原始檔標頭、套件依賴及第三方聲明，沒有引入 Esoteric 套件。保留 16 個未修改 runtime JS 檔，原文授權及來源摘要另行保存。

鄰伴只啟用經這次驗證的 JSON 子集，顯示名稱是「免費骨架（Rigby JSON）」，格式為 `rigby-json-zip/v1`。原生 Spine 格式在雲端保持停用；新格式不代表所有 Spine、DragonBones 或其圖庫模型都可以直接使用。

## 可以做甚麼

- 播放模型自帶的 idle、wave、listen 等動作；缺少某個動作時不憑空生成。
- 有 `mouth`、`mouth_open` 或 `jaw` 骨骼時，按現有 Microsoft 語音的本機分析訊號開合嘴形。這是音量驅動，並非完整逐個語音的嘴形辨識。
- 接入原有歡迎／聆聽／關懷動作訊號、暫停、縮放取景及畫面截圖。
- 經 AIRI 模型選單匯入，在本機預覽後，按原有「儲存至平台」才作共享發佈。沿用原有不可變 SHA、儲存預留、上載權限及設定版本核對，不另建資料表。
- 操作不需購買 Editor、Runtime、訂閱或額外 AI API。

## ZIP 格式

檔名建議使用 `角色名稱.rigby.zip`。內容包括：

```text
rigby-manifest.json
model.rigby.json
model.atlas
original.png
LICENSE.txt
```

清單例子：

```json
{
  "format": "rigby-json-zip/v1",
  "skeleton": "model.rigby.json",
  "atlas": "model.atlas",
  "license": {"name": "作者提供的授權名稱", "author": "模型作者"}
}
```

模型素材與播放器的授權分開。清單必須保留作者及授權資料；仍須確認作者容許實際的展示、下載及平台共享用途。只修改 ZIP 標記不能令受限素材取得新權利。

支援 JSON 3.8／4.2／4.3 的區域貼圖及無權重網格、骨骼及插槽動作。暫不接受 `.skel`、加權／linked mesh、約束、變形、圖片序列或音效事件。Rigby 原始碼的 binary reader 目前只處理部分 4.3 編碼，故本批沒有啟用 binary 相容功能。

上載及裝置端各自驗證：ZIP 最大 32 MB、最多 64 個檔、解壓總量 40 MB；骨架 3 MB、atlas 64 KB、PNG 每張 16 MB、最多 8 張及總計 32 百萬像素。拒絕外部網址、危險路徑、執行檔、重複檔、無效數字、父節點循環、缺貼圖及尺寸不符。前端採有界串流解壓並核對 CRC；PNG 尺寸在解碼前先檢查。沒有自動修改住戶資料、計數或現用角色。

## 隔離驗證紀錄

- 31 項新後端案例涵蓋合法包、外部引用、循環、無效數字、網格／圖像尺寸、明確授權標記、同資料庫持久儲存、重複上載、格式混淆及發佈前核對。
- 17 項 Node 案例驗證裝置端檢查與 PNG 預先尺寸驗證。
- 額外 ZIP 實驗確認真正 TS loader 可載入原創 3,468 bytes 樣本，並拒絕 CRC 篡改、實際展開量超出聲稱、重複檔、外連、缺圖及程式。
- Chromium 與 WebKit 真 WebGL 播放原創幾何角色，手臂骨骼實際由 0 轉至 36 度、嘴骨由 0.2 轉至 1，前後畫面摘要不同，沒有外連或頁面錯誤。
- 這些是軟件及合成圖像測試，未開真人鏡頭、咪高峰、音訊播放或機械人；沒有下載或發佈受限的 Spine／Rigby 示範角色。

原創合成樣本、畫面及收據位於 `.runtime/free-paths-20261105/animation/`。此樣本供驗證匯入及動作，並非新增的一個外部圖庫來源。

## 其他免費路線

DragonBonesJS 的 Runtime 為 MIT，可作另一種自製骨架動畫方案，但現有 Pixi 整合版本及素材授權仍須分開測試；本批沒有將其冒稱已接入 AIRI。Inochi2D 為 BSD-2-Clause，網頁路線要額外處理 WebAssembly 工具鏈，同樣沒有列作本批已完成播放器。

## 來源及授權保存

- [Rigby2D 固定版本與原始碼](https://github.com/jaisurya-dev-art/rigby2d/tree/72bc84625fac4959e185574df12adbd33add11d6)
- [Rigby JavaScript runtime 說明](https://github.com/jaisurya-dev-art/rigby2d/blob/72bc84625fac4959e185574df12adbd33add11d6/docs/runtimes.md)
- [Rigby MIT 授權](https://github.com/jaisurya-dev-art/rigby2d/blob/72bc84625fac4959e185574df12adbd33add11d6/LICENSE-MIT)
- [Rigby 第三方聲明](https://github.com/jaisurya-dev-art/rigby2d/blob/72bc84625fac4959e185574df12adbd33add11d6/THIRD_PARTY_NOTICES.md)
- [Spine 官方 Editor 條款](https://esotericsoftware.com/spine-editor-license)、[Runtime 條款](https://esotericsoftware.com/spine-runtimes-license)
- [DragonBonesJS MIT 授權](https://github.com/DragonBones/DragonBonesJS/blob/master/LICENSE)
- [Inochi2D BSD 授權](https://github.com/Inochi2D/inochi2d/blob/main/LICENSE)

原文公告隨平台程式保存於 `deploy/cloud/web/free-skeletal-notices.txt`，網頁固定入口為 `/cloud/free-skeletal-notices.txt`。Pinned runtime 每檔的 SHA-256 在 `airi_overlay/free-skeletal-runtime/PROVENANCE.json`；打包時不可改動上游檔案或刪除原文公告。
