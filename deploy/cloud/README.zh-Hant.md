# 鄰伴獨立雲端部署準備

## 2026-10-30 正式接線候選（尚未啟用）

新增獨立 `managed_release.py`／`release_envelope.py`，只在已完成原寫入者停止、啟動防重複、一致匯出、逐項匯入及復原驗證後才接受正式設定。它與 stage 的格式／用途／衍生密鑰範圍分開；驗證完成前不改環境或重用 stage 安裝器開正式功能。以既有已授權 Render secret 作傳輸材料，正式 service secrets 只以服務／origin 綁定密文交正常 Render 工具，無需本人再次複製 key；雲端磁碟只有小型參照／metadata，沒有 DPAPI 解密替代、原用量預設值或可作正式權威的暫存 SQLite。

`maintenance.py` 已接上可選正式 HTTP lifespan：先停止新請求進入，等既有請求及被 shield 的語音辨識完成，再單一維護執行者處理90日保存和備份；取消時亦不讓 SQL worker 脫離仍繼續寫入。維護失敗保持閘門，職員仍可讀無 SQL 寫入的快取維護狀態；成功才恢復接收。大批到期資料分批清理，剩餘過期內容未清完前不開放。固定三分鐘交接及明確長期記憶不改。這是單服務實例的閘門，**不是分散式租約**；往後部署／復原也必須先使舊正式寫入者停止，不能讓兩個正式版本同時寫入。

正式接線亦有一次性 `release_probe.py`：只用固定公開蛋糕三輪對話檢查 Gemma 上下文，再以固定句子由曉曼產生記憶體音訊交 Whisper。先保存嘗試紀錄；通過後冷啟動只讀回紀錄，不重新消耗模型額度，未知／失敗的嘗試不自動重送，不改用本機聲線或其他模型。沒有開咪、播放音訊或保存完整對話／錄音，原免費預留及失敗請求計數照常生效。這是待正式部署時的服務驗證，不代表已取得真人咪高峰、實聽或手機／Notebook-off 驗收。

`sql_snapshot.page_limit` 及逐值摘要比對會先按 SQL 伺服器回傳的實際字節上限分頁，避免 `fetchmany` 之前已一次載入整批約60MB相片。新增本機 `cloud_primary.py`／啟動合約，只有實際建立 cutover marker 後才阻擋原 Hub／語音寫入及自動重啟，正常啟動入口改往已核准雲網址；目前尚未建立 marker，沒有停止正常本機服務。這不是自動回滾：不能刪 marker 後用舊計數重新開本機。

已建立獨立正式九類空庫及備份空庫，仍在同一鄰伴 Free 群組、$0／overages=false，未上傳私人資料或讓服務使用它們；另有讀／寫憑證，真遠端唯讀拒寫及寫入回滾後仍空白已核。驗收庫及原 token 不改。正式 SQL 憑證的到期日有本機紀錄，約一年後須按原程序更新；不會自動開計費。這批程式接線仍待合併驗證及真正一致切換，不能因資源已建立或本機預覽副本可復原，便稱平台已關機可用。

## 2026-10-30 原資料匯出、批次匯入及耐久備份候選

`native_export.py` 可預覽六類 SQLite 的一致讀取副本，保留所有歷史用量、原短號、序列、BLOB、MB842 文字標記及原收據；預覽明確不是跨庫一致快照。正式匯出必須由仍然有效的唯一寫入者停止檢查逐步核對，期間若 DB／WAL、暫停／冷卻或收據改變便停止。現有本機 controls 是 JSON，原本沒有雲端 StateStore／簽署帳本／帳本 key；不得把這當作遺失原 key，或以隔離 stage key 代替。不存在的 Cloudflare stop／cooldown 檔只按本機既有語義記錄為 inactive，原用量完全不歸零。

`native_adapters.py` 只在新私人資料夾準備雲端控制、首次雲端帳本及舊遮蓋相片保存副本。原相片路徑、摘要、各事件引用及缺失引用分開保存，不補造缺少相片，不宣稱舊相已經雲端 AI 核實或有左／右三個視角。現有 native expiry 表轉成新帳本的既有清除意圖，舊收據保持原樣。這不會上傳、覆寫原檔或操作 EP。

`sql_import.py` 使用有界多行 INSERT，目的地必須完全空白，逐項比對表結構、每個值、隱藏 rowid、短號序列、用量及 header metadata，提交後由呼叫端重新連線核對。Turso 的 header PRAGMA 不容許設定；當原值已相同時避免無意義 setter，非零版本無法保留仍然停止，不放寬比對。提交回覆丟失會回報結果未明，不能盲目再匯入已有資料庫。

`backup_store.py` 把八類已協調關閉的快照分成 256 KiB 區塊，交由獨立 SQL 備份庫持久保存；刪除帳本及簽署 key 不放入可還原備份。所有區塊回讀及簽署 manifest 核對後才標示完成；中斷留 pending，不自動覆寫或清走。只可在當日新備份成功且無 pending 後輪替本功能建立的七份每日備份；原搬機包／本機既有備份不會被此工具刪除。保存中的備份可依**現行獨立**清除帳本重寫個案、事件及相片，保留原完成時間／備份時間，用量、控制及明確記憶不變，並記錄前後簽署摘要。共享舊相只在最後一個事件引用到期後移除。SQL 清除不等於供應商磁碟／離線舊包的物理抹除。

這批仍是搬遷及備份候選，未接上正式排程／雲端資料切換。下載備份只是私人復原輸入，**不能直接替換正式庫**；必須另核對現行帳本、合併現行用量／較嚴格控制並確認唯一寫入者。原居民／管理本機服務沒有停用，雲端仍處於登入及 storage acceptance 閘門，Notebook-off 目標尚未完成。

## 2026-10-30 Google → 居民／管理介面候選

新增同源 Google 登入外殼，身份只留記憶體；後端核對後才載入居民或職員畫面，登出／更換畫面清除舊請求。storage acceptance 仍不載入居民及管理 iframe，兩頁直接訪問為423，不能啟用咪高峰或寫正式資料。首次 Google 真登入已在上一版核對，不需重設帳戶。

雲端 AIRI 使用獨立 App／profile，移除原生 WebSocket bridge、PWA、模型預載、未使用的 DuckDB 初始化及大型字型；保留原數字人渲染、PCM 嘴型、居民三分鐘交接與已批准的 Whisper 分支。原 vendor 逐檔 SHA 還原，正式 dist／本機服務沒改。隔離 frontend9 的 lint／typecheck／build 全部 exit0。以 SHA manifest 選出約64MB程式資產，未直接上傳原390MB dist；沒有本機 profile、source maps、service worker、Notebook模型或居民照片。公開示例模型及素材聲明見 THIRD-PARTY.md。

實際隔離 Chromium 檢查發現並修正原生語音 host 門檻、Pixi CSP 相容、內嵌 WASM／ZIP blob 圖像讀取及多餘 CDN 字型宣告。沒有放開 JavaScript unsafe-eval、變更 Windows 執行政策或借用用戶的 Chrome profile。隔離瀏覽器已驗：stage 不建立媒體畫面、真正角色模型尺寸與畫布、三輪完整文字上下文、三次曉曼格式零值PCM替身、職員更新個案／屋苑資料分頁與登出；所有網絡攔截，零正式資料寫入／實際開咪播音／EP。供應商和 Google 身份都是替身，不能當新雲端真 AI／真聲音驗收。測試腳本 tests/isolated-cloud-ui.browser.cjs。

管理台沿用個案、關懷、相片、屋苑資料及額度元件，以 Google 同源傳輸取代本機 operator key；移除原生 EP 背景、自訂供應商、Notebook資源及本機 iframe。職員事件／三相跟進有明確身份、版本衝突及相片核對；修正進度更新後相片保存狀態漏同步的候選缺陷。未知 commit 回覆保留 durable outbox，讀回鏡像後才完成；不重設完成日期或90日期限。隔離測試不是正式遠端資料驗收。

**尚待：**真雲端完整前台／語音測試、正式一致快照與單寫入者切換、原quota／暫停／冷卻／短號／MB842／原刪除帳本及回條、備份與90日復原、Notebook-off／外網手機驗收。這次不會因程式已部署便解開驗收閘門，也不要求用戶再貼 key。

## 2026-10-30 雲端 Whisper 已獲用戶批准，候選接線完成

用戶明確同意雲端版用現有 Cloudflare 免費 Whisper Turbo 辨識；錄音會交 Cloudflare，與 Gemma 共用免費額度，本機 SenseVoice／Gemma／曉曼不變。新增嚴格同源身份保護的 transcription 接口、完整最多45秒WAV驗證、先預留現有8,000-Neuron共用守護、短期同段去重／兩工作上限／逾時不重送。正式使用仍需明確 whisper Free／user_approved 設定及原有模型 key；staging 模式照舊拒絕 POST，不會為驗證而啟用供應商。

前台新增同源錄音請求與30秒取消；真 Vue script 測過改用文字、下一位／三分鐘清場後，舊 ASR 不會插入新對話。隔離 AIRI cloud index 分支不回本機 ASR，原 vendor／正式 dist 均還原或未改。這不是已啟用的完整雲端居民畫面：Google-to-AIRI 啟動、靜態資產／analytics／service worker整理、管理台、正式一致匯入與單writer、備份保存及 Notebook-off 仍待。詳見本機 docs/cloud-speech-input-2026-10-30.md 與 cloud-asr-20261030 回條。

## 2026-10-30 08:29Z 隔離主機已上線、真 Google 登入已通過

私人來源 v27／26f16512215441410af90f576633f823df058479 已核對遠端，Render Free 的 dep-dbi594ui0phs73ctcl40 終態 live。AES-GCM 設定更新已只以密文經現有 Render 專用工具合併，沒有再次要求本人貼 raw key；API 儲存自動觸發部署，沒有重複 trigger。真 Linux 九類 Store 啟動約 5.612 秒，這不是對話延遲或效能承諾。

外網 root／JS 與來源 SHA256 一致，login-config 只有核准 public clientID，未登入／偽 token 401；本人 Google 登入成功，後端 2026-10-30T08:29:20Z session GET200 已核。HTTPS 在現有 loopback forwarding allowlist 已正常，沒有擴大信任範圍。Computer Use 本身仍受網址辨認 guard 阻擋，沒有修好或繞過該工具；部署設定已改由正常 Render 連接完成。

這是只供驗收的登入入口，health 仍 public_ready=false，不會開咪、合成／播放音訊或操作 EP。完整居民與職員前台、ASR、正式一致資料匯入與唯一 writer、持久備份／90 日清理／復原及 Notebook-off 整體驗收仍未完成。本機原服務與所有資料保持；不要把隔離主機 live 當作整個平台已完成。

## 2026-10-30 最新接續：Google 已核、隔離設定更新已測試

本人已完成 Google 登入及首位職員綁定；不再需要重做本機設定。其後 Computer Use 在正常 Chrome 服務頁（包括先啟用視窗）仍無法可靠辨認網址而強制停止，沒有改安全設定或換瀏覽器控制繞過。本人已正常把 staging 設定存入 Render；手動觸發的 e6c3ce2 舊版本部署 update_failed，新版 managed-stage 尚未上線。

新增只限隔離驗收的 stage_envelope：以本人已存入該服務的舊 staging writer 憑證作 HKDF-SHA256 的傳輸密鑰材料、隨機 salt 與 nonce，AES-256-GCM 驗證並綁定服務 ID／origin；Render 專用工具只接收密文。接收端先解密及核對完整 managed-stage metadata，成功才安裝七個允許變數；拒絕模型憑證、任意變數或改 forwarding trust，沒有明文金鑰進入聊天、來源庫、傳輸日誌或新剪貼簿。這個舊 SQL 憑證已撤銷資料庫存取，但作為傳輸密鑰仍須在 Render secret storage 保密；密文本身亦只存此服務，不能當公開設定。不得把此隔離入口用來切換正式資料。

截圖曾包含 staging 憑證材料，已用官方 group rotate 撤銷該唯一合成資料群組的 SQL tokens；兩條舊 token 真遠端 HTTP 401，新 reader／writer 分開、14 日有效、只 DPAPI 保存。新建 neighbour-stage-deletion-ledger-r2 及新測試簽名 key，舊測試帳本／收據及加密備份保留不改；正式原 key、收據、MB842、居民資料與用量沒有改動或上傳。

82 項受影響測試與 Ruff 通過，使用合成 Google／暫存 SQLite 與本機 libsql；真遠端舊 token 拒絕及新測試帳本重開另有回條。完整居民網站、正式 Google 外網登入、ASR、單正式 writer 搬遷及 Notebook-off 仍未驗收，不得稱整個平台已部署完成。


2026-10-29：用戶要求 Notebook 關機後仍可使用。此目錄是準備及核對工具，**尚未完成雲端部署**，不可把 ngrok Notebook 網址當成已完成。

## 2026-10-30 Render 已建立，Google 登入設定進行中

本人已完成 Render GitHub App 的新私人庫授權。重新核對沒有重複資源後，已建立 `neighbour-yuenhk`（`srv-dbi41m2fngtc73c82fq0`），My Workspace／Singapore／**compute plan=free**／autoDeploy=no。網址已分配 `https://neighbour-yuenhk.onrender.com`，**尚不可當作可用平台**。原兩個其他服務沒有改動。

首個部署 `dep-dbi41mifngtc73c82hbg` 來源為 `c0f71203f58d2a7c1a26317ee27ed90dbebe8add`。Render 的真實 Linux／Python 3.12.10 已安裝所有鎖定依賴，07:02:15Z 回報 Build successful；隨後應用程式因尚未提供 `/etc/secrets/neighbour-host.json` 而以固定 `cloud_host_configuration_required` 拒絕啟動，部署終態 **update_failed**。這是未配置前的停止條件，不得移除檢查、設假身份／臨時資料或重試相同未配置部署求綠燈。尚未輸入正式 key、資料或 Google 帳戶設定；沒有公開居民功能。

已新增只限本機的 Google 首位職員設定工具 `deploy.cloud.login_setup`。由本人在 Google 建立 Web application Client ID，JavaScript origins 包括上面雲端 origin、`http://localhost` 及 `http://localhost:8924`；只需基本身份 scopes，不需 Client secret、開計費或下載憑證。工具保留指定電郵、固定 Google JWKS／簽名／audience／issuer／時效核對，再核對本輪 nonce，成功才把最少帳戶 metadata 用 Windows CurrentUser DPAPI 加密保存；不保存 ID token、Google 密碼、Client secret 或居民資料，不覆寫既有設定。

本機入口只綁 127.0.0.1:8924，HTTP Host 固定 localhost、同源 POST 加程序 nonce、拒外網／重複欄位／大 body、不記存取 log，30 分鐘自停。HTML／JS 不開咪、不播放音訊、不操作 EP；這不是雲端公開註冊端點，也不會自行授權任意居民帳戶。合成 Google 簽名／失效 nonce／錯帳戶／偽 token／CSRF／DPAPI 真往返／失敗不明文及打包排除測試通過；真人 Google Client ID、彈窗與登入仍待本人完成。

代理嘗試「驗證並背景啟動本機設定工具」的指令被自動審查在執行前拒絕 `blocked by policy`，未提供細項原因。沒有代啟動、產生 PID、改政策或換另一控制途徑重試；獨立測試／lint 已另外正常執行。已準備可供本人檢查及前台執行的 `OPEN-CLOUD-LOGIN-SETUP.cmd`，須由本人開啟後再訪問 `http://localhost:8924`，不應假稱頁面已開。加密輸出位置是 `.runtime/cloud-host-20261029/private-deployment-20261030/render-service-20261030/google-login.dpapi`；不要把其內容、ID token 或個人帳戶識別寫入聊天／程式庫。

## 2026-10-30 已核實進度

Turso 官方第一方登入已成功，帳戶 `yuenhk`；不再需要重試 Codex MCP 或找 API Tokens 選單。由官方 CLI v1.0.34 原碼建立的本機工具，加入只限此工具的 Windows CurrentUser DPAPI 保存及正常第一方登入連結；保留 state／TLS，沒有關閉 Codex issuer 檢查。憑證只加密保存在本機，不在程式庫、聊天或日誌。

實際 Platform API 已核對訂閱 `starter` 為 **$0／月、overages=false**；此名稱不是 Render 的付費 Starter。已建立鄰伴專用 `neighbour` 群組、Singapore 的九個 `neighbour-stage-*` 驗收資料庫，**只放公開合成資料**，沒有搬居民資料。管理 token 僅該組織／群組的 read、db:create、db:mint-token、group:mint-token；資料寫入及唯讀 token 分開，不含刪除或計費管理權限。

真實遠端驗收已確認：無憑證 401、提交後關閉／重新連線仍讀到 Unicode 及 BLOB、交易回滾、唯讀 token 拒絕寫入；九類 Store 的完整啟動、短編號、記憶、日誌、合成用量、暫停狀態及已簽署刪除紀錄也已核對，沒有產生本機 SQLite 後備。這是隔離庫驗收，不是正式搬遷或 Notebook-off 驗收。原本機用量、私人資料、MB842、簽名 key 及 EP audit 完整保留。

已修正兩項真實供應商相容問題：Turso 拒絕 `PRAGMA query_only=ON`，新版 profile 改用供應商強制唯讀 token；也拒絕記憶連線的 `PRAGMA secure_delete=ON`，雲端只開已核對的既有表，原本機仍沿用原清除指令。**SQL 刪除不等於雲端磁碟／平台備份的物理抹除**，90 日保存及備份清理仍是正式上線前必須完成的項目。

啟動將表格、欄位、quick_check、foreign_key_check 合併成每庫一輪查詢，仍保留短號、事件 stream／接收序列／完成日期及簽名檢查；雲端 Store 明確使用 `initialize=False`，不重跑本機建表、補號或升級。額外最多四個唯讀驗證執行緒可選，預設一個。Notebook 跨網絡九庫完整啟動實測 45.188 秒；這不是同區 Render 或對話延遲。API host 有 60 秒有界啟動預算，未就緒仍拒絕請求，不把超時當通過，也沒有自動重試或放寬資料完整性條件。

私人來源庫 `YuenHK/neighbour-cloud` 及 Render Free service 已建立，建置結果見開首。完整雲端前台／Google 登入／ASR、正式一致資料搬遷、唯一寫入者切換、持久備份及關機後外網驗收仍未完成；不要直接公開原本機 app，也不要停止仍正常運行的本機服務。最新本機證據位於 `.runtime/cloud-host-20261029/private-deployment-20261030/turso-provisioning/`，不會納入來源包。

### 歷史 Render 私人庫存取阻擋（已由本人解決）

2026-10-30 已嘗試在本人確認的 My Workspace 建立 `neighbour-yuenhk`，明確 Free／Singapore／手動部署，不傳任何私人資料或 key。官方工具回覆 HTTP 400：`passed in repository URL is invalid or unfetchable`，**未建立服務**。來源 URL 格式正確；目前連接不能取用新私人庫，確切 GitHub App 設定尚無法由工具查看。不要再用相同參數不停重試、把 repo 改成公開、放 token 進 Git URL 或新建重複庫。

已請本人到 https://github.com/apps/render/installations/new ，在 YuenHK 的 Render Configure 保留原有 repo 存取，再加入 `neighbour-cloud`。如未連接 Git Deployment Credentials，需在 Render Account Settings 正常連接 GitHub。這是來源庫授權，不是 Turso 登入失敗；Turso 不必重做登入。官方步驟：https://render.com/docs/git-provider#fixing-github-app-permissions 。此來源授權其後已由本人完成，Render service／首次建置結果見開首；本機服務保持正常。

Linux amd64／Python 3.12 的 24 個相容 wheel 已在隔離目錄成功解析及下載（約 37 MB），含 libsql；沒有安裝到正式環境或執行 Linux。這只排除「沒有相容 wheel」的部分問題，**不是 Linux、512 MB 主機或實際 Render 建置通過**。

## 選擇及現實限制

Oracle 註冊已由用戶確認失敗，**不再沿此路徑等候或重複註冊**。目前轉向 Render Free 程式託管與 Turso Free 永久資料庫。2026-10-30 用戶已回覆原待辦確認「同意，只用免費方案」：允許以現有 Google／GitHub 登入或建立這兩個免費帳戶，建立鄰伴專用 DB 憑證並只加密保存；不加信用卡、不升級或購買。歷史交接中的 pending 已由本次回覆取代，不要再次要求同一授權。目前僅建立下述隔離資源，未部署公開平台或上傳私人資料。

本次開到 Render 登入頁後，瀏覽器控制中斷；接續工具明確回報 `Local browser use is disabled in Work settings`。這是工具設定阻擋，**不是用戶未授權**。不自行更改安全／工具權限、不從瀏覽器私有檔案提取登入狀態。其後 Render 官方連接工具已成功接通，用戶確認使用 My Workspace；GitHub 私人來源庫 `YuenHK/neighbour-cloud` 已建立並核對私有狀態、推送及遠端提交。這只是來源庫，尚未建立鄰伴 Render 服務；Turso 隔離 DB 的新進度見本文件開首，未上傳私人資料。

其後用戶已確認「Browser 已啟用，Browse 允許／逐次批准」，但工具端新檢查仍回同一錯誤。不要再要求用戶重複更改同一設定／重批帳戶授權；這是介面確認與工具狀態的落差，確切原因未能確認。可使用已授權的官方連接工具／API，不能藉其他瀏覽器控制方式繞過限制。

Turso 官方 MCP 設定已由用戶在本機加入，但 OAuth 被現版 CLI 的 issuer 安全檢查拒絕。2026-10-30 實際公開 metadata 的 issuer／token endpoint 在 `api.turso.tech`，授權入口在 `app.turso.tech`，未宣告 `authorization_response_iss_parameter_supported`。不要再重複登入、關閉驗證、改寫 metadata 或降級繞過。最新 Turso 官方 API 已支援組織／群組及個別權限限制，應選用該正式途徑；舊文章稱所有 API token 皆跨組織，已不能當作現況。這類群組限定憑證其後已透過官方 API 建立並 DPAPI 保存，見開首。

來源：https://docs.turso.tech/api-reference/authentication 、https://docs.turso.tech/api-reference/tokens/create

2026-10-30 重新核對官方 Turso 價格頁：Free 列示 $0／月、100 個 DB、5 GB 儲存、每月讀取 5 億行／寫入 1,000 萬行，毋須信用卡。九個資料角色的數量在列示上限內；後續已另用實際帳戶 API 核對零元方案、禁超額及 Singapore；價目表本身不證明剩餘額度或搬遷成功。Render Free 閒置後的首次請求約需一分鐘喚醒，不能承諾即開即用或用假流量保持運行。

來源：https://turso.tech/pricing 、https://render.com/docs/free

原候選 Oracle 官方 Always Free A1 配額為總共 2 OCPU、12 GB RAM；不是舊教學的 4 OCPU、24 GB。即使免費主機亦有容量不足及閒置資源收回限制，不能保證免費服務全年不停機。

來源：https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

Render Free 閒置 15 分鐘後休眠，本機 SQLite／照片會在重啟後遺失，免費 Postgres 30 日到期，不能直接搬現有資料庫到該暫存磁碟。Turso 作永久 DB 的方向須先通過交易、錯誤、快照、90 日清理與備份相容測試；照片也要有永久保存方案，不能漏做。libsql 0.1.11 僅裝研究環境，隔離遠端驗收已完成但原本機正式 Store 未切換；其原生錯誤有 ValueError 而非只用 libsql.Error，適配器必須統一錯誤且不洩漏 SQL／私人值。

來源：https://render.com/docs/free

## 保留功能

居民 Gemma、曉曼 F0、Tavily、個案短編號、同事項補充、關懷、屋苑資料、長期記憶、90 日保存及備份必須保留，並在新主機逐項重新驗收。ASR 仍需 SenseVoice 模型及 Linux CPU wheel／實測；不得未告知就改用另一款辨識。

EP 在屋苑內網，需要現場裝置作連接。此批不會連線、初始化、解除鎖定、開相機或移動 EP。雲端開機前保留 `ep-manual-operation.json`；現場橋接尚待另外實作及本人手動驗收。

## 程式與私人資料分開

### 小型雲端 API 的獨立依賴

`python -m pip install -r deploy/cloud/requirements.txt` 供候選雲端 API 的獨立 Python 3.12 環境使用；不要直接安裝 `.[cloud]`，後者仍會連原本機的 OpenCV、ONNX、sklearn 等依賴一齊安裝。原本機 pyproject／venv／GPU、巡查及語音辨識依賴沒有移除。新 requirements 保留 Gemma、曉曼 HTTPS 串流、BM25 屋苑資料檢索、SQL 相片、Google 認證及 libSQL 所需套件；`constraints.txt` 固定這次 Windows 隔離環境已解析的版本，不會單靠 constraints 安裝測試套件。

隔離環境未安裝本機視覺／辨識引擎；曾重現巡查審核只引用 `ApprovedPhoto` 類別也間接 import OpenCV 的問題。該不可變資料類別現獨立於 `approved_photo.py`，舊 `photo_privacy.ApprovedPhoto` 引用維持同一類別，原遮罩、單次核准與未核准拒送流程不變。雲端不因此新增相片上傳或 EP 路由。

2026-10-30：全新 Windows Python 環境 463 項 cloud 測試、原本機 7 項相片審核回歸、pip check 及變更 Python 的 Ruff 通過。測試使用合成資料、假 HTTPS／JWKS及臨時 SQLite／libSQL 本機引擎，沒有真實 Turso／Render／AI／語音請求。仍未驗證 Linux wheel、實際 512 MB 主機、完整前台／ASR、登入或跨庫搬遷；這份依賴清單不是可以直接啟動的完整平台，更不是已部署的網址。

`python -m tools.cloud_bundle --output <新ZIP絕對路徑>` 只打包允許的程式來源；不含 `.git`、`.runtime`、資料、金鑰、模型、node_modules、個案或照片，也不包含整個 AIRI vendor/build，因此不是可直接運行的安裝檔。`CLOUD-BUNDLE.json` 列出每個檔案的 SHA256 及缺少項目；不覆寫現有 ZIP。

新主機需另外準備固定 AIRI commit `dbf812488829a61cc2e95909e021b215704d066c`、現有 overlay、Node 22／pnpm 10.33.0、已驗證前台、Python 3.12、SenseVoice 模型、永久資料磁碟及 HTTPS 認證。尚未有 Linux 主機，不能宣稱容器建置、ARM wheel 或開機部署已通過。

## 金鑰

### 可啟動的 API 工廠（仍非完整居民網站）

`deploy.cloud.host:create_host` 已提供明確的 Uvicorn ASGI 工廠。只在 lifespan 啟動時開啟已匯入的遠端 DB；單純 import、建立工廠或缺設定都不會連線。正常關閉、啟動失敗或取消會清理取得的組件；啟動失敗會明確失敗，不讓前台等住或自動重試。這仍不包含靜態前台／真實 Google 登入、ASR、跨庫搬遷及單一寫入者證明；健康回覆保留 `public_ready=false`，不能直接建立公開服務當作完成。

`NEIGHBOUR_CLOUD_CONFIG` 必須指向已有的絕對 JSON 路徑。格式 `neighbour-cloud-host-v1`，只允許 `format`、`origin`、`google_client_id`、`accounts`、`database_profile`、`runtime_root`、`settings_root`、`scratch_root`。origin 必須是完全吻合的 HTTPS origin；accounts 是已核准 Google subject 對 staff／resident 的對照，至少有一位職員。三個目錄須已存在、不同；settings_root 必須吻合明確雲端 backend 的 `NEIGHBOUR_SETTINGS_ROOT`。拒絕原生 DPAPI 模式、重複／額外欄位及 symlink 路徑，不產生空資料庫／用量或預設身份。

原刪除帳本簽名 key 可能包含任意二進位 bytes。供此工廠使用的 host secret 必須是 `base64:<原 key 的標準 base64>`；工廠會先解碼，再用原 bytes 核對簽名，不能把 base64 文字當新 key、另造 key 或重置現有收據。key 不可進入此 JSON、程式庫、日誌或聊天。

本批 45 項相關離機測試及變更檔 Ruff 通過，包含兩個本機 DB 引擎、假身份／供應商、合成帳本、失敗及取消清理。沒有真 Turso／Render 推論、語音或硬件請求；Linux、實際平台 proxy／HTTPS、登入、前台及 Notebook-off 驗收仍待完成。

Windows 預設 DPAPI 不改。只有明確 `NEIGHBOUR_CREDENTIAL_BACKEND=systemd` 才啟用新主機模式；同時需已存在的絕對 `NEIGHBOUR_SETTINGS_ROOT` 及 systemd 提供的 `CREDENTIALS_DIRECTORY`。

雲端設定內 `*-key.dpapi` 僅存 `NEIGHBOUR-SYSTEMD-CREDENTIAL-v1:<名稱>` 的參照，不存真 key。允許 cloudflare-gemma-key、azure-speech-f0-key、tavily-key 三項；真正值由主機的私密 systemd credentials 注入。不能把現有 Windows blob 當 Linux key，不能用普通文字包假稱加密，亦不能由網頁重設這些憑證。尚未匯出或上傳任何正式 key。

Render 候選另支援明確 `NEIGHBOUR_CREDENTIAL_BACKEND=managed-environment`：設定檔只放 `NEIGHBOUR-HOST-SECRET-v1:<名稱>` 參照，從固定的 `NEIGHBOUR_SECRET_*` 執行期變數讀取。不能讓參照任意挑選其他環境變數，亦不接受跨 backend 的參照、空值或控制字元；錯誤不回顯 secret。此程式本身**不會加密環境變數**，實際 host secrets 保護及部署注入方式仍須核對，不能宣稱已加密上雲。額外保留 turso-data-token、turso-read-token 及 retention-ledger-key 參照供日後 DB／刪除收據使用，實際 staging 資料／唯讀 token 及 staging 專用簽名 key 只 DPAPI 保存；正式 key 沒有匯出或注入主機。

官方設定方式：https://render.com/docs/configure-environment-variables

## 明確選用的遠端 DB 連線候選

`database_profile.py` 只接受完整、標明已核對 Free 的 libSQL remote-primary 設定；這個標記本身不是官方帳戶查詢或搬遷成功證明。新版 `neighbour-cloud-storage-v2` 使用 `plan_verification` 記錄官方 API 核對的來源、組織、零元方案、禁超額、UTC 時間及原回條 SHA256；不偽稱 `ui_verified`。每庫必須同時列 `credential=turso-data-token` 及 `read_credential=turso-read-token`。唯讀 URI 只取後者，不執行不相容的 query_only PRAGMA；讀取 key 不存在或失敗便停止，不改用寫入 key。v1 原明確 UI profile 保留原行為以便相容；生產雲端須使用已驗證的 v2。這些設定標記只是部署回條，不是每次呼叫都查官方計費或保證永遠免費。

九個角色（個案、事件、屋苑資料、記憶、職員日誌、用量、控制狀態、照片、獨立刪除帳本）必須有不同的核准 Turso endpoint。只允許無內嵌密碼／query／port 的 `libsql://*.turso.io`；不接受任意 URL、重複 JSON 欄位、未列出的資料路徑或已有內容的本機 DB，亦不會在失敗時改用空的暫存 SQLite。

個案、事件、資料、記憶、日誌及配額類別已有明確 `connection_factory=` 接口；原本未傳這個參數時仍使用原 SQLite。沒有改全域 sqlite3，也沒有在本機自動啟用 cloud profile。未知 EP 控制 DB 不會被映射到雲端。記憶初始化失敗、職員日誌及配額初始化的短連線都有關閉檢查。

`file:...?mode=ro` 只映射到已綁定角色；v2 使用獨立供應商唯讀憑證，舊 v1 保留 query_only 行為。它不是任意檔案代理。密鑰／driver 錯誤不回顯敏感值，初始化失敗會關閉已建立的連線。可選 `.[cloud]` 固定 libsql 0.1.11、PyJWT 2.15.1 及 cryptography 50.0.2；沒有安裝到目前正式 venv。後兩項只放在獨立 `.experiments/cloud-auth-20261030/python` 研究環境，以官方 PyPI wheel 安裝並保存來源／摘要回條，沒有改動原本 AI 研究環境。

歷史離機測試的 endpoint 全由攔截 driver 導向 pytest 臨時 DB，分別用標準 SQLite 及真正的研究 libsql 本機引擎；其後的真實 Turso staging 與耗時證據見開首，仍未驗收正式資料切換或實際 Render 容量。目前主程式未選用此 factory；真實雲端啟動仍要接齊下述儲存 scope、CSV 快照 provider、保存／備份、照片路由及跨 DB 檢查，不能因建構子測試成功就公開。部署時還要在實際可用免費區域內盡量將程式與 DB 放同區，量度每輪 SQL 往返；不能假設搬上雲端一定更快。

## 用量及控制狀態的明確儲存 scope

`runtime_storage.py` 的 `RuntimeStorage`／`StorageMiddleware` 只是未啟用的雲端依賴容器。`storage_context.py` 用 ContextVar 將同一個明確選定的 DB profile 傳到請求、同步職員端點的工作執行緒及串流結束；退出／錯誤時復原，不污染其他 app 或本機預設。**只包住目前主程式並不足夠**：個案、事件、知識等核心 stores 必須在建構時明確綁定，正式程式目前沒有套用 scope，不會重導本機資料。

在此 scope 內，配額預留與 `usage_snapshot.py` 的讀取使用同一個永久 DB，即使 Render 暫存目錄沒有 SQLite 檔也會查真正計數；讀取失敗或資料異常顯示未知，不能顯示零。雲端執行期若遺失已匯入的 usage 表，拒絕預留及服務，不會重新建立空表。本機初次沒有 DB 時仍維持原行為。這些都是平台自身的守護計數，**不是官方免費剩餘額度**，沒有改變方案或放寬上限。

`state_store.py` 使用獨立控制 DB；只接受曉曼暫停、Cloudflare 官方 quota 停止及短暫冷卻三種固定欄位。初始化及首次匯入必須明確執行，拒絕覆寫舊旗標／縮短仍生效的封鎖；缺少或損壞的旗標不會自動視為可用。`control_state.py` 在雲端 scope 內只讀寫此 DB，不會取暫存檔作備援。曉曼解除暫停不清計數；Cloudflare quota 停止與網絡／限流冷卻成功寫入後可以跨程序保留，無自動換模型或重試。巡查的限流回覆也寫入同一控制 DB，未觸發任何 EP 或真雲端請求。

匯入須與原用量及原狀態一起核對；不能直接把測試用的過期時間或 False 當成正式預設。原本機單調時鐘冷卻值不是可攜式時間，切換時仍要停止舊寫入者並確認冷卻已結束，或保守保存其餘時間。若網絡令控制寫入結果不確定，程式保留本程序冷卻並記錄 `control_persistence=unavailable`；**這不保證重啟後已保存該次新冷卻**，部署前仍須完成寫入結果不明時的復原與單一寫入者驗收。沒有將不確定提交當成功。

## 巡查 CSV 的雲端快照候選

`EventStore` 新增明確 `export_snapshot_factory=`；原本機未指定時仍走原生 SQLite 備份快照。雲端建構時須同時傳入 `connection_factory=profile.connect`，以及 `EventExportSnapshot(event_path, connection_factory=profile.connect)` 作為匯出 provider。主程式沒有套用這個選擇；只有 remote factory 而未提供快照 provider 時，會在傳出 CSV 標頭前回固定服務暫不可用，不會嘗試改讀本機事件檔。

`event_export.py` 用一條專用、唯讀的遠端連線及一致讀交易，經 `sql_snapshot.py` 複製到本次專用暫存目錄；來源連線及交易在開始下載前已關閉。CSV 只讀該次完整副本，後續職員修改狀態或新事件不會改變同一次匯出。暫存 SQLite **只作下載副本，不是正式資料或永久備份**。仍限制每個 EventStore 同時兩份快照、準備最多五秒及 128 MiB；失敗、取消或下載完成會釋放名額並清走本次暫存，不移除其他檔案，不保存私人錯誤內容。

離機測試亦重現研究版 libsql 0.1.11 在關閉 connection 後再進入原生 handle 的 panic。適配器現會記錄已關閉狀態、同步呼叫與關閉、重複 close 不再進入 driver；後續讀寫／交易／游標 metadata 以標準 ProgrammingError 拒絕。這是本機研究引擎及假 endpoint 測試，不等同真實 Turso 網絡或 Linux 併發驗收。沒有延長原五秒限制；實際跨區延遲可能令匯出準備失敗，仍須在正式免費主機量度。

## 獨立啟動組件候選

`bootstrap.open_services(profile, signing_key_loader=...)` 可明確組裝個案、事件、屋苑資料、明確記憶、職員查閱日誌、用量與控制、照片及獨立刪除帳本，並綁定前述 CSV 快照 provider。它不載入本機 `edge_hub.app`，不建立 EP／視覺／本機語音服務，不呼叫模型、網上搜尋或語音供應商，不啟動排程執行緒或任何現場動作；另有上述 API-only ASGI 工廠，仍不能當作可公開的完整網站。只有明確呼叫工廠時才會經所選 profile 存取 DB，單純 import 不連線。簽名 key 由呼叫者的私密載入器提供，不在程式內產生或輸出。

組裝前會逐一唯讀檢查九個角色的既有表格、目前需要的欄位、完整性及外鍵；缺表或舊欄位會停止，不能當新機重新初始化。個案短編號對照、事件串流識別、接收序列及已完成事件的完成日期也要完整，避免原本供本機初次啟動的補建程序重新編號、產生新串流身份或重算 90 日時間。控制旗標不能缺少，刪除帳本須通過現有簽名檢查。這些最低結構及關係檢查**不是完整資料指紋、已簽搬遷收據、外部帳本新鮮度或跨 DB 原子快照的證明**。

`CloudServices.scope()` 將配額及狀態綁到同一組永久 DB；尚未包住正式請求。正常關閉或半途建構失敗會關閉本次已取得的連線，包括建構子取得 DB 後尚未返回物件就失敗的情況。重複關閉可安全退出；關閉後的記憶／日誌延遲開庫及新 scope 會拒絕。日後 ASGI 生命週期仍須先等正在進行的請求、搜尋及音訊串流結束，再關閉組件；此工廠不會代替整個應用的停機程序。

**部署仍必須先停止舊寫入者、完成一致匯入與核對，並阻止其他寫入者。** 九個 DB 的啟動檢查與後續建構不是同一個原子交易；不能只因工廠通過就聲稱具備全域單一寫入者或已安全完成切換。原本機所有 constructor 預設及正式服務都沒有改用此入口。測試只使用生成的案例／假 MB842 記憶與攔截 endpoint，沒有接觸正式資料；主機、認證、完整 HTTP／媒體、每日備份、保存清理及關機後外網驗收仍待完成。

## Google 身份及 HTTP API 候選

`google_identity.py` 用 PyJWT 驗證 Google ID token 的 RSA 簽名、發出者、指定 OAuth audience、時效及已核准帳戶。權限按預先指定的 Google `sub` 決定；不以瀏覽器聲稱的角色、電郵或本機操作員 token 授權。Google 建議以固定 `sub` 識別帳戶；本候選另核對電郵已驗證狀態，不自動接納第一次登入者。[Google 官方驗證要求](https://developers.google.com/identity/openid-connect/openid-connect)、[PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html)。

只向固定 Google 公開 JWKS 網址取公鑰，不傳 resident 訊息或登入 token、不呼叫 tokeninfo、不跟隨 token 裡的 key URL。公鑰快取有期限，過期而不能更新時拒絕登入，並限制未知 key／故障時的重複取用。測試用現場生成的合成 RSA key 簽假 token，再以假 HTTP 公鑰回覆核對；沒有登入真人帳戶、註冊 OAuth app、取得真 token 或建立新的服務 key。

`http_app.create_app(services, verifier, origin=...)` 是未公開的 API 工廠，沒有預設 `app` 或自動開 server。API 要求固定 HTTPS host／同源操作及 Google bearer token；不信任任意轉送標頭。正式反向代理及健康檢查的 TLS／host 方式仍須到實際免費主機核對，不能為取得綠燈而放寬成任意代理。請求與回覆串流使用同一身份及儲存 scope，職員查閱有 durable intent 日誌，錯誤及驗證失敗不回顯私人輸入。

目前候選已接居民分流／搜尋規劃、個案／職員進度／短號、固定 Cloudflare Gemma adapter、屋苑知識與明確記憶管理、職員 CSV。原本機 resident guard 保持預設 loopback；雲端只在明確組裝時傳入已核對身份的依賴，不全域改判斷或偽裝成 localhost。Gemma 失敗不轉 Gemini／Ollama；需要本機處理的私人記憶上下文仍回明確暫不可用，不偷偷轉交雲端。也補正「頭先提過／上一句」被當成上網查詢的已重現問題；一般垃圾分類等資料查詢仍可走搜尋，不誤開單。

**尚未有可用的居民／管理網上介面。** 真正 OAuth client／Google sub 核准、登入畫面與 token 更新、AIRI 同源託管及 WebSocket、實際曉曼播放、ASR、quota 工作台、照片／保存及備份整合仍待完成；居民面板的候選接線見下文。現候選不提供 robots／設定／API key 頁或 WebSocket；`/health` 也明確標示 `public_ready=false`，不是關機後外網驗收成功。原 Render／Turso 帳戶授權已取得，官方 Render 工具及 Turso 第一方 API 已接通；此 API 仍未部署或啟動公網。

照片的職員讀取 API 候選已補上（見下文），但相片遷移、現場上傳、正式清理及管理介面仍未完成；不能把單一讀取接口當作完整巡查服務。

## 資料回覆遺失處理候選

遠端 DB 的錯誤回覆不能證明「剛才一定沒有保存」。候選 API 現會將回覆標頭送出前的 SQLite／檔案讀寫異常轉為固定、不回顯私人內容的 503；不顯示原 SQL、路徑、key、住戶資料或 exception 字串，不自動重試或另建本機資料庫。讀取失敗標示 `read_unavailable`；未能確認寫入結果則保守標示 `unknown`，不能說成已回滾。

直接提交求助單時，回覆帶 `same_submission_id_same_content` 指示：沿用原傳送編號及原內容，已提交的回傳同一張單，未提交的只建立一次；同一編號換內容仍拒絕。職員更新則帶 `read_current_revision`，要先讀目前狀態；若上次其實已提交，舊版本重送會被既有版本檢查拒絕，不重複增加備註或活動。這些是雲端客戶端應保留的重送規則，尚未代表完整雲端前台已接好。

若職員查閱日誌在操作前無法記錄，回覆 `not_attempted`，不會繼續執行個案更新。操作已確認成功、只在日誌收尾失敗時，仍回原成功結果並留下未完成日誌意圖；不能將成功改成失敗而誘發重複操作。異常收尾本身再遇到 DB／檔案錯誤，也不再掩蓋原本的錯誤。

測試在臨時 SQLite 及研究 libsql 本機引擎中，真實提交或回滾後注入一次回覆遺失，核對單號／活動／版本及重送結果。這不是實際 Turso 網絡斷線驗收，也不提供跨 DB 原子性、已開始串流後改寫回覆或「恰好一次送達」保證。供應商冷卻／官方停止旗標的提交不明與跨程序復原守門仍待完成；本機服務未重新載入這套候選錯誤處理。

## 瀏覽器同源登入請求層候選

`airi_overlay/cloud-transport.js` 提供明確選用的 `createCloudTransport()`。需要已核准 HTTPS origin 及真正 Google 登入模組提供的 `{ token, expiresAtMs }`；模組本身不註冊帳戶、不顯示登入視窗、不自動啟用，也不把客戶端自稱角色當成權限。真正簽名、audience 及核准 Google sub 仍由前述後端驗證。**實際 Google 登入模組、OAuth 設定及整個頁面仍未接好。**

只有同源的居民／工作台、CSV、固定巡查相片及曉曼串流路徑才會帶登入 token；外部模型網址、loopback、EP、任意設定頁、額外 API key／Authorization header 或轉址／cookie 覆寫會在取 token 前拒絕。不將居民 body 交給登入 callback，亦不將憑證存入 localStorage、設定檔或日誌。所有請求固定不快取、不跟隨轉址、只向同源派送；權限仍以服務端為準。

並行請求合併一次登入等候，記憶體 token 在快到期前再取得；預設每次登入等候最多十秒。取消一個請求不會取消其他共用等候者，逾時／登出後遲到的結果不能重放到下一身份。401 只令下一次明確請求重新取得憑證，不自動重送目前請求；503／未知寫入結果與原 body、submission ID 原樣交回呼叫者處理，不另開新單、不換模型。原始登入／網絡 exception 字串不回顯。

`clearAuth()` 現會同步清登入等候／快取並切換請求的取消生命週期，向舊一輪全部進行中 fetch 發出 abort；個別呼叫者的原 AbortController 不會被改成已取消。若請求工具忽略 abort、仍遲到交回標頭，亦會拒絕將該舊回覆交給新畫面，盡力關閉其 body 而不等候無回應的清理。舊一輪 401 即使碰上新登入取得完全相同的 token 字串，也不能清走新一輪快取。新一輪先建立新的生命週期，再通知舊請求取消，避免取消回呼開始的新請求誤用已取消的訊號。

標準原生 fetch 會將 abort 傳到已回標頭但仍讀取中的 body；自訂 fetcher 也要遵守 AbortSignal，才能停止其已交出的串流。本批只用 Node 模擬這些事件，未做真實瀏覽器／外網驗收。UI 仍須清除本輪歷史、草稿世代及已解碼／排程的音訊；不能靠清登入撤回已送達資料、已建立個案、供應商已處理的請求或已預留額度。取消也不會自動重送或退款。

`ResidentPcm` 可明確傳入 `endpoint`，雲端使用 `/_audio/v1/audio/resident-stream` 及此請求層。原預設仍為本機 8765，曉曼及原速沒有改變，不會根據頁面網址自動猜測／偷偷退回 Notebook。居民規劃、Gemma、PCM 及計時的面板接線已補入下述候選；登入、託管啟動及 ASR 仍待完成，不能只換這些 endpoint 就宣稱整個平台已獨立上雲。

初版只在 Node Web APIs、假登入／fetch／AudioContext 下驗證。2026-10-30 已另完成下述候選的 AIRI stage-web 型別檢查、變更檔案 lint 及隔離生產建置；**沒有實際 Google 登入、公開網址、開咪或播放音訊**，沒有同步現行 dist 或重啟服務，測試後已還原暫存覆蓋的三個 vendor 來源檔。這不是瀏覽器／外網驗收。

### 居民面板的同源接線候選

`resident-api.js` 選定網絡邊界，居民 Vue 面板、PCM 及計時共用它。原生模式維持現有 AIRI provider／角色規劃；雲端模式必須在 AIRI 載入前明確設定 `__NEIGHBOUR_CLOUD__=true`，並提供 `__NEIGHBOUR_CLOUD_TRANSPORT__`（上述工廠建立的已認證 transport）。這些不是自動登入，也不是由網址猜選模式。transport 可稍後準備，但缺失時請求會失敗、保留草稿，**不退回 Notebook 或其他供應商**。不能直接公開普通 native build 當成 cloud build。

雲端面板先送同源 `/api/v1/resident/chat` 做搜尋、分流及回條規劃，再將有效 `resident.plan` 的角色提示及原對話送到固定免費 Gemma adapter；沿用同一 session／turn ID，未改原有重送語義。雲端不讀 AIRI 所選的其他模型／舊本機聲線作備援，朗讀只走同源曉曼 F0 PCM 原速；頁面握手也用同源 origin。真正 host boot／Google 登入、token 清除與頁面結束的整合仍須補齊。

`ResidentTiming` 可傳入同一 transport；同步 throw 或網絡失敗只捨棄本次計時，不影響對話。雲端新增已認證的 `/api/v1/resident/timing`，每個 app 獨立存最多 128 個樣本／階段，只接七種 0–180,000 ms 數值，不接文字／稱呼／個案或 session ID。這是未經信任的瀏覽器排程時間，非實際聽到聲音的驗收；主機重啟可清掉此暫存統計，不會重設用量／個案等永久資料。

本批 47 項相關 Node 測試包含真面板腳本在假 store／fetch／AudioContext 下連續三輪、完整上下文、Gemma turn ID、曉曼及三分鐘清場；36 項相關 Python API 測試包含未登入拒收、計時輸入限制及現有語音／資料路徑。stage-web typecheck、三個變更檔案 ESLint 0/0、新網絡邊界嚴格 checkJs、隔離 Vite build 與 Ruff 通過。完整 463 項上一批無變更套件沒有重跑。證據在 `.runtime/cloud-host-20261029/resident-wiring-20261030/`；建置位於 `verify2/stage-dist`，不是現行網站、完整託管安裝檔或已部署版本。

## 管理用量 API 候選

`quota_api.py` 現提供唯讀 `GET /api/v1/service-desk/quota`，只有已核准職員可讀，沿用 HTTPS 同源及職員查閱日誌。資料保留原用量表格的 `overview.active_rows` 格式，只列 Cloudflare Gemma、Azure 曉曼 F0、Tavily 搜尋；若 Tavily 回傳有效 key 上限，會另外列明同時生效，不能與帳戶餘額相加。不列舊 Google／MiMo／SiliconFlow 等試驗，不提供語音開關、API key、付費／重設操作，也不將 Notebook 的 CPU／記憶體冒充雲端資源。

Gemma 及曉曼的進度條來自同一個永久資料庫內的**保守預留計數**，不是官方已用或餘額。缺失、損壞或無法讀取 usage 表會顯示未知，不建立空表或以零代替；控制旗標未知時不能顯示服務可用。查閱不預留新額度、不改暫停／封鎖／冷卻，亦不清零現有計數。UTC 每日／每月守護重設時間有獨立標示，不能當成 Azure 資源的官方重設日期。Cloudflare、Azure 的官方剩餘未取得，仍明確標示未知；方案列示額度也不是即時剩餘或實際帳戶方案查詢結果。

只有 Tavily 透過既有搜尋 key 讀固定官方 `/usage` API，不傳 Google 登入 bearer 或居民對話。專用 client 不跟隨轉址；大於 64 KiB 的回應拒用，整個查詢最多等六秒，逾時會關閉串流。沿用每 key 六十秒快取及合併查詢，失敗不立即重試；不接受 query 強制繞過快取。更新失敗可標示本月上次記錄及時間，跨月的舊記錄則回復未知，避免把上月餘額當成本月數字。key 改變會捨棄上一帳戶快取。沒有為啟動或心跳暖機發出查詢，也不呼叫模型、語音或計費 API。

這仍是未公開的候選接口，未接完成的雲端管理頁／登入流程；官方 API 延遲及免費主機均未驗收。本批只用假 Tavily 回覆、假身份及導向臨時 DB 的 endpoint，沒有取得新的真實官方額度、讀取其他平台帳戶或重啟本機服務。

## 曉曼免費串流 API 候選

`voice_api.py` 現已接入候選 HTTP 工廠的 `/v1/audio/resident-stream` 及 `/_audio/v1/audio/resident-stream`，沿用同一套 Google 身份／HTTPS／同源及儲存 scope。兩個網址是同一個處理器，共用快取、在途重複攔截及兩個名額，不是兩套語音引擎。固定 Azure 曉曼 F0、原速、24 kHz 單聲道 16-bit PCM 的 SSE 格式；不轉本機、Google 舊聲線、其他 Azure 聲線或付費方案。不提供完整 WAV `/v1/audio/speech` 或 MP3 播放。

輸入最多 1,500 字元、JSON body 最多 8 KiB；拒絕其他模型、聲線、變速、額外 API key 欄位及異常文字。雲端生命週期持有專用共用 HTTPS client，讓後續句子可重用連線，關閉時會清理；沒有為暖機而發出合成請求。此設計可能減少建立連線的開支，**未量度真實主機首聲時間或驗證聽感**。現有本機 audio app 未改用此共用 client，亦未重啟。

沿用原語音守護及先預留後派送：暫停、資料不可讀或達到本機守護上限時，快取也不繞過停用；成功完整快取可避免同句重複預留。上游失敗不自動重試、不退回已預留計數、不保存部分音訊為成功快取。測試核對真實守護資料路徑經假 Turso endpoint，而不是製造本機 SQLite 檔令用量顯示為零；沒有真 Azure 呼叫或播放。

共用 `resident_stream.py` 亦修正已重現的資源問題：異常文字的 hash 失敗原本發生在取得名額後而未進入 finally，兩次便可耗盡名額；現先驗文字，再取得名額。取消或傳輸失敗時會明確關閉上游 iterator、歸還名額；來源關閉失敗不能產生成功 done 或快取。清理不再依賴垃圾回收。若同步網絡讀取已在執行，清理仍可能等待既有讀取逾時，**不保證立即中斷供應商處理或撤銷已花額度**；瀏覽器停止播放及完整外網測試仍另驗。修正只在來源及隔離環境，本機現行服務未重新載入。

## 巡查相片職員讀取候選

`photo_api.py` 現在提供與本機相同格式的 `GET /api/v1/patrol/events/{event_id}/photo?side=event|left|right`，預設讀主相。只有已核准職員身份可讀，沿用 HTTPS 同源與職員查閱日誌；不接受居民身份、本機操作員 key、瀏覽器提供的路徑或重複／未知 query 欄位。這不是公開圖片網址，回覆不快取；沒有上傳、預覽核准、相機、雲台或 EP 操作接口。

只讀已匯入的 EP 三相回報。事件本身須有完整主／左／右相片 manifest，照片 DB 的事件、方向及摘要必須逐一吻合，再驗證原 JPEG 內容；不能只找到同名檔案就回傳。事件狀態、照片保存狀態及完成日期要一致；完成滿 90 日、照片 tombstone、已清除事件，或獨立帳本已有已提交刪除意圖，均不會顯示。若資料缺失、簽名損壞或 DB 無法核對，明確失敗，不把錯誤當成「沒有刪除記錄」。

每個讀取前後重核事件及現行刪除帳本；途中改動回覆 409，不回傳本次圖片。照片內部的綁定、保存狀態及內容在同一讀取交易內核對，最多兩個同時請求、每張 1.5 MB，並有五秒協作預算。**這不能把不同 DB 變成同一個原子交易，也不能強制中斷已阻塞的 DB 呼叫。** 帳本現仍逐鏈驗證；大量歷史收據、真 Turso 網絡及免費主機的時間／容量要另行驗證，未有實際提速結論。正式切換仍須一致匯入、簽名收據與一個正式寫入者。

GET 不會刪除原相片、追加刪除收據、自動補狀態或重試。到期時停止顯示也不等於底層資料及備份已清除；每日保存清理、受管備份刪除與復原仍是獨立待辦。本批只用純色合成 JPEG、假身份及假遠端 endpoint，在 SQLite／研究 libsql 本機引擎測試，沒有讀取正式照片、呼叫雲端視覺或操作 EP；本機服務未重新載入。

## 已可離機驗證的保存候選

- `libsql_connection.py` 包含 SQLite 相容行資料、第一個同名欄位、交易及錯誤映射，尚未替換正式 stores。
- `sql_snapshot.py` 從專用閒置連線開一致讀取交易，分頁複製到全新 SQLite，不覆寫檔案。保留隱藏 rowid、AUTOINCREMENT 序列、原索引、Unicode/BLOB、user_version、application_id、WITHOUT ROWID 表；完成後真做 quick_check 及外鍵檢查。超時／容量／不支援 views 或 triggers 都失敗，不發成功回條。這是離機 SQL 復原實作，不等同已驗證 Turso 網絡交易、每日雲端備份或自動災難復原。
- `photo_store.py` 是 SQL BLOB 候選，測試只用生成的純色 JPEG／PNG，原 PNG 也不重新壓縮或改摘要。主／左／右照有固定事件、摘要及不覆寫約束；相同重送冪等、容量失敗回滾。只有已審核標記的圖片可進候選 store，但此標記本身不是自動遮罩或住戶同意證明。狀態用真正巡查的 pending／confirmed／resolved／false_positive；從職員完成日起算 90 日、後續備註不能延長舊完成日期，重開未過期個案會停止清理；已清除相片有 tombstone，不能重開該事件或用新 key 復活。還未接入正式相片端點或保存工作。

`photo_store.py` 的 tombstone 只保護目前 DB。**若直接還原較舊整庫備份而不套用最新外部保存刪除收據，仍會回復舊資料。** 以下已有離機候選，仍未接到正式服務／Turso；真正的雲端 row size／storage 限額及照片存取認證也未完成驗收，不可只因單元測試通過就公開。

## 獨立刪除收據與復原候選

`deletion_ledger.py` 用另一個專用 DB，只記個案／事件 ID、版本及清除時間，不記對話／照片／聯絡內容。收據串鏈並以外部穩定 key 簽署 head；初始化空帳本必須明確指定，遺失帳本不能自動從零建立。同一版本重送保留首次意圖時間；批次失敗全回滾。PhotoStore 到期時先確保收據提交成功，再刪照片；若提交回覆遺失，照片會保留，之後重送可沿用同一收據。不能把照片 DB 或其他應用資料混在帳本 DB，也不能在未提交的外層個案交易內執行到期清理。

`retention_restore.py` 只接受已關閉、SHA256 正確、沒有 WAL／journal 側檔的備份，並核對由**獨立現行帳本**讀取的 checkpoint。只寫全新輸出，不改舊備份或運行中資料；重建後清除過期個案文字／活動備註、事件區域及照片資料。即使舊備份仍顯示個案未完成，也要按新收據清除私人內容。原編號、序列、其他個案及備份時的職員狀態保留；這不會補回備份之後遺失的工作更新。完成後實做 VACUUM、完整性／外鍵檢查，再核對帳本與來源未變；中途有新清除記錄就不回傳 ready。到期事件有整個事件的標記，不能換新照片 key 復活。

限制：此候選沒有接正式清理／備份管理器，亦沒有真正的 Turso 網絡／主機重啟復原驗收。所有 scope 復原與正式切換仍要停止舊寫入者、檢查跨 DB 關係，並處理雲端受管備份中的原資料。簽名不等同新鮮度；不能將舊備份附帶的舊 checkpoint 當成現行帳本。若獨立帳本及其外部信任基準一起遺失或回退，必須停下由操作員處理，不能假稱可自動保證防回退。

## 用量庫復原防倒退候選

`usage_restore.recover_usage()` 只處理用量資料庫，接受已關閉、SHA256 正確及沒有 WAL／journal 側檔的備份，並透過明確的 `RuntimeStorage` 讀取仍然可信的現行用量庫。現行庫遺失或不可讀時停止，不建立空表、不改讀本機暫存庫，也不能拿舊備份自己充當「現行」數字。

它只寫全新輸出，不覆寫任何舊檔。每個 meter／UTC 期間取備份與現行計數的較高值，保留兩邊已有的歷史期間；即使計數已超出本機守護上限也原樣保留，下一次預留仍會被阻擋。不能退回失敗請求的預留、把數字截低至上限或清掉舊期間。所有計數、期間格式、已核對 meter、schema 及版本必須正確；最多 50,000 個計數、備份最多 128 MiB，SHA 用串流方式讀取，避免一次把整個備份放入記憶體。

準備前後會重新讀取現行庫，並重核備份摘要。途中有新用量、來源變更或超出協作期限就不回傳成功準備結果；失敗留下的輸出僅供診斷，不可啟用。成功也只回 `prepared=true`、`cutover_ready=false`，不是公開部署、單一寫入者證明、官方實際餘額或完整災難復原。

**仍須先確認權威來源並停止舊寫入者，才可正式切換。** 最後核對之後再有新請求仍可能改變用量，這個工具不能代替全系統切換鎖。它不復原或合併曉曼暫停、Cloudflare 停止／冷卻旗標，不取代前述現行刪除收據，也不覆蓋個案、記憶、照片或 EP audit；這些必須各自保持現行狀態並一致搬遷。若現行權威庫及所有可信基準已遺失，不能靠較舊備份推知已發生的額外消耗，必須由操作員核對，不能自動當作可用。

目前沒有 CLI、排程、自動復原或正式啟動連到這個工具。測試只使用隔離 SQLite／研究 libsql 本機引擎及合成數字，核對較高計數、歷史、超額阻擋、來源中途變更及檔案不覆寫；沒有還原正式資料、連接真 Turso 或呼叫 AI／語音服務。

## 控制旗標復原保護候選

`control_restore.recover_controls()` 與用量庫復原分開，亦只接受已關閉、SHA 正確的備份及明確可信的現行控制庫，僅建立新輸出。它要求完整三個既有旗標：曉曼暫停、Cloudflare 官方停止及短暫冷卻；缺失、損壞、未知欄位或版本不符時停止，不把它們默認成可用。

新副本的暫停值取兩邊的 OR，停止及冷卻時間則按包含時區的真正時間取較後者；同刻的冷卻保留較保守的限流原因。原已過期的冷卻仍用原時間，不因復原動作重新計時。若舊備份曾暫停、現行曾恢復，新副本會先保留暫停，留待操作員核對；**不會更改現行偏好或代人解除暫停**。輸出的版本編號會保留更高版本再遞增，不能溢位後歸零。

前後重核現行狀態及備份摘要，途中變更或逾時就不發準備成功結果。與用量工具一樣，成功亦明確為 `prepared=true`、`cutover_ready=false`，需要操作員核對；沒有 CLI、排程、正式服務或自動復原接入。它不啟動語音／對話、不重設用量、不處理 EP，也不修改來源。兩個工具分別準備副本不能代替一致的全系統備份、單一寫入者切換及現行刪除收據；若現行權威來源或未確認提交的狀態已遺失，仍須先停止切換並核對，不能從舊備份憑空重建。

本批只用隔離 SQLite／研究 libsql 本機引擎測試，沒有對正式資料執行復原、接真 Turso 或重啟本機服務。

## 復原完成前再次核對關閉備份

三個離線復原工具現在共用 `closed_backup.py` 的最後核對。已用真 SQLite WAL 寫入重現：準備途中即使有新資料寫入 `-wal`，主 SQLite 檔的 SHA256 仍可能完全一樣。只在開始時檢查側檔、結束時只比主檔摘要，會誤將已不是靜止來源的備份視為通過。

完成前會重核主檔摘要、`-wal`／`-shm`／`-journal` 不存在，以及 hash 讀取期間的檔案身份、大小、修改時間及符號連結狀態；觀察到新側檔或來源變更便不發 `prepared`／`ready` 結果，不會刪側檔、checkpoint 備份、停止其他程序或改寫來源。原已失敗的新輸出仍只作診斷，不能啟用。

只有**事前已核對關閉、摘要正確的本機備份檔**用 SQLite `mode=ro&immutable=1` 開啟，避免讀取已關閉但 header 仍標記 WAL 的備份時，自行產生空的輸入側檔。正常 WAL 格式關閉備份仍可讀取；現行雲端庫不使用這個選項，繼續用普通專用唯讀交易。不能拿 immutable 宣告代替確認關閉，亦不能為通過檢查而強行清除側檔。

這些核對不是全域檔案鎖，也不能保證最後檢查之後不再出現寫入者；真正切換仍要停止／隔離舊寫入者及核對所有 DB。測試只在合成資料及臨時檔案重現，沒有對正式資料執行復原或部署。

## 資料切換與驗收

1. 備份原資料、SHA256、完整性檢查；保留個案編號、MB842、故障及 audit。
2. 最終切換時才由管理員結束對話及停止舊寫入者。匯入資料、quota 計數、封鎖／暫停狀態及 90 日刪除收據；不能在新機從零計 quota。
3. 新主機只有一個正式寫入者；永久磁碟及受保護備份不能依賴 Notebook。
4. `python -m tools.cloud_preflight --settings <持久設定路徑> --model <SenseVoice路徑>` 只讀檢查，不發網路、不開 DB、不接 EP。缺項退出碼 2。它只准進入主機驗收，不代表已公開或完整對話已通過。
5. HTTPS、指定帳戶登入、三輪對話上下文、曉曼首聲／取消、語音輸入、分流／短號查詢、重啟後資料、Notebook 關機後外網使用全部另驗。

原 Render／Turso 帳戶及憑證授權已於 2026-10-30 取得，見本文開首；遇需要本人處理的身份／手機驗證仍須交接。只保留免費方案，遇付款／升級即停；不重試已失敗的 Oracle 註冊。未有已確認免費主機前，不變動本機正常服務。

2026-10-30 實際 Turso 匯入曾在索引 SQL 核對時回滾：平台將 `ON service_cases(case_number)` 顯示成 `ON service_cases (case_number)`。只針對 `CREATE [UNIQUE] INDEX` 的簡單、未加引號表名與左括號之間空白，摘要作相同處理；其餘 SQL、欄位、條件、字串內容、排序、定序、唯一性、隱藏 rowid、序列及所有資料仍逐一核對。原備份的 SQL 不改寫，實際格式差異及回滾診斷保留；不是忽略任意結構差異或跳過驗證。

每日快照對有隱藏 rowid 的表改用索引接續讀取，避免每一頁 `OFFSET` 再讀先前操作紀錄。仍保留原 rowid、空洞、資料及完整性核對，SQL 回覆大小上限不變。`WITHOUT ROWID` 表維持原分頁及定序方式，避免主鍵與欄位定序不同時漏行。兩萬筆公開合成資料的本機 SQLite VM 工作量由約 1,319,000 步減至 459,000 步；這是離機量度，不是 Turso 官方計費讀取量或雲端延遲承諾。
