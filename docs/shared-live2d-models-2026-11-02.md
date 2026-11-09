# 共享 Live2D 模型及免費圖庫

2026-11-02 已部署至 https://neighbour-yuenhk-live.onrender.com/ 。正式程式版本為 `c7b03a9797dce9b57e0f6c1118b2379bce94a640`，Render Free、Singapore、單實例，沒有新增付款、憑證或改動 Gemma／Azure 曉曼 F0。

## 管理員操作

1. 進入管理工作台 → 數字人設定 → AIRI「角色模型」。
2. 在「免費模型圖庫」閱讀官方使用條款，確認適用後，按模型的「一鍵匯入預覽」。第一批為 Mark、Wanko 及 Haru。
3. 也可以保留原本 AIRI 的 Select model → Import → Live2D，匯入自己的 ZIP。
4. 預覽確認後，按最上方「儲存至平台」。只有這一步才會上載並發佈模型；單純預覽不會改動其他居民裝置。
5. 其他裝置新進入居民服務台時使用已發佈模型。已開啟畫面在可見且閒置時每 60 秒檢查，或於「下一位」／閒置交接後更新。若已有對話、草稿或處理中的請求，不會中途切換角色。

「平台共享模型」保留舊版本。選擇舊模型作預覽，再儲存至平台即可還原；不會自動刪除其他版本或本機模型庫。原版九個設定入口仍保留；本次共享匯入支援包含 `model3.json`／`moc3` 的 Live2D ZIP，並非所有 VRM／Spine／MMD 自訂檔都已同步。

## 免費圖庫來源

- 官方來源：Live2D/CubismWebSamples，固定版本 `b1de66b0b1f1cb881d95fb6158622aeb6a2827bd`。
- [官方免費模型圖庫](https://www.live2d.com/en/learn/sample/)、[免費素材授權](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)、[各角色使用條款](https://www.live2d.com/en/learn/sample/model-terms/)。
- Mark 保留卡通風格，Wanko 保留麻糬主題。官方免費模型有用途及機構資格限制，不能將「免費下載」視為任何用途皆可使用。
- 只整理官方模型為可匯入 ZIP，保留角色外觀及來源；Haru 移除四個附帶語音連結，不包含聲音檔，以保留原有曉曼語音。沒有自動購買、登入第三方圖庫或匯入未核對的網址。
- 本批模型及縮圖隨已核對的程式資產提供，不在每次開頁時爬取網站，也不使用 AI 對話、朗讀或搜尋額度。日後新增圖庫項目需要核對來源、條款、檔案摘要及相容性。

This content uses sample data owned and copyrighted by Live2D Inc. The sample data are utilized in accordance with terms and conditions set by Live2D Inc. This content itself is created at the author’s sole discretion.

## 儲存、失敗及保留

- 每個 ZIP 上限 32 MiB，共享模型儲存預留上限 64 MiB／100 版本。這是本平台的保守上限，不是官方免費餘額；到上限即停止新上載，不自動加費或刪舊檔。
- 模型保存於原正式 Turso 屋苑資料庫的新獨立資料表，按 SHA-256 保存不可覆寫的原檔，256 KiB 分段。不是 Render 暫存磁碟或只留在上載者的瀏覽器。
- 職員身份才可上載；居民只可下載目前已發佈版本。模型編號不是存取金鑰，不會把 token 放入網址。上載不帶居民對話或個案資料。
- 裝置自行快取已核對模型，避免每位居民都重新下載。儲存不足時可使用記憶體；校驗失敗／暫時無法下載時保留可用角色或內建角色，文字及語音對話仍可運作。
- ZIP 拒絕外部引用、路徑跳出、程式、加密／重複檔、額外聲音及超限解壓內容。下載須核對大小及完整摘要。
- 上載原檔和發佈設定分成兩步；上載成功但發佈失敗時原角色不變。中途斷線的寫入由服務追蹤至完成，不能盲目重送或自動清除不確定結果；重新開啟設定先查閱已保存模型。
- 新資料表納入原屋苑資料的每日備份及復原路徑；每日備份並非每次儲存後即時新增一份。原個案／照片完成後 90 日及 managed backup 清理規則不變，角色模型不是個案相片，不會被該清理流程誤刪。

## GitHub Pages 入口

https://wcy.hk/neighbour/ 會直接跳到正式平台，沒有額外按鈕。既有 GitHub Pages 根頁及其他遊戲頁保留。Pages 只提供入口，對話及管理功能仍在 Render／Turso；沒有在公開庫放入私人平台原始碼、居民資料或憑證。

## 驗證及切換紀錄

- frontend38 lint、型別檢查、正式建置通過；所有暫時裝配的原版 AIRI 檔案逐 byte 還原，未覆寫本機執行資產。
- 隔離瀏覽器用真正官方 Mark／Wanko／Haru 檔案匯入並載入各自的 Live2D 動作及預覽。另以原有 Hiyori ZIP 完成原版 Import、一次上載、CAS 發佈、兩個獨立瀏覽器取得同一摘要、對話不被打斷及下一位交接同步。
- 損壞下載回到內建角色後仍可對話；原版九入口、服務設定儲存重開、合成三輪上下文及無聲曉曼管線回歸通過。正式環境沒有上載測試模型、建立測試個案、呼叫正式模型／朗讀／辨識、開真人咪或播放音訊。
- 原版匯入缺少 `display.initialize()`，令縮圖工具未初始化的錯誤已修正。內嵌長頁的原版模型對話框會按實際可見視窗定位，避免滾動後匯入按鈕落在可見區外。
- 私人 GitHub 部署庫已更新。新 `barrier6` 等候舊 `pjll4/PID58` 於 `04:57:03.055054051Z` 真正退出、完整官方 CLI 日誌及唯一新 `npdz2/PID59` 確認，逾 90 秒後才簽署本次放行紀錄。不能重用本次紀錄作其他部署。
- 舊寫入者停止後，已建立關閉的一致私人屋苑副本，另以獨立 reader 核對；只新增兩個空白模型表，原四表結構、資料、rowid 及 metadata 摘要不變。沒有重新匯入或更改原個案、短號、設定、用量／暫停冷卻及 MB842。
- 正式 HTTPS 根頁、居民／管理頁、程式雜湊、三款官方模型與縮圖及職員模型清單均已核對。用戶自己的新模型仍須由用戶選擇及儲存；未代替用戶發佈任何新角色。

完整收據：`.runtime/cloud-model-publish-20261102/`；GitHub Pages 收據：`.runtime/github-pages-entry-20261102/`。EP 完全未操作，原本機 cloud-primary fence、退休 Render 暫停狀態、所有既有修改及資料保留。
