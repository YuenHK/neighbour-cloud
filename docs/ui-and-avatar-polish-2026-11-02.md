# 鄰伴啟動畫面、數字人動作及內嵌機械人控制

2026-11-02 已部署到原入口 https://neighbour-yuenhk-live.onrender.com 。Render Free／Singapore／單實例，runtime `0b0d053c63a4a7a1cf102daf2123dfff1a390a57`，deploy `dep-dbjtv0142hec73e2fq1g`，00:59:10 UTC 應用 ready。沒有更換供應商、正式資料庫或網址。

## 畫面與使用流程

- 居民入口加入無聲啟動畫面，按真實連接、介面、角色狀態切換；同源預載已核對的程式／樣式。角色 mounted 後才顯示完整畫面。30 秒仍未完成會提供重新連接；聊天面板已準備時才提供先用文字開始。沒有假百分比或刻意延時。Free 主機在 HTML 送出前的冷啟動仍需等待，動畫不能消除這段時間。
- 移除「再聽一次」及額外頁尾；朗讀中仍可停止。管理登入改為寬鬆卡片，手機按鈕直排。
- AIRI 工具列及「儲存至平台」合成同一行，窄屏可橫向捲動。保留原版九個設定入口。既有內建角色／模型／場景同步範圍不變；其他工作室偏好與自訂素材仍依既有方式儲存於瀏覽器。
- Live2D 加入招呼、傾聽、發言及柔和關懷的短暫點頭／側頭動作。只在本機逐格運算，單次約 1.7–2.6 秒；不新增模型請求、不改保存姿勢、鏡頭或口型，結束回復基準。尊重減少動態效果設定。VRM 保留原有動作，未新增同款手勢。

## 機械人登入及內嵌流程

管理工作台「機械人控制」直接內嵌原控制台，沿用現有職員登入，不再另要求 Google。

瀏覽器只向同源 API 發送記憶體中的職員 session；雲端驗證職員身份後，僅轉送至保存的固定現場 ngrok 免費端點。現場閘道向固定雲端 session API 核對身份，再用自己的 loopback capability 轉送至原硬件程式。token 不寫入檔案或日誌，短暫核對快取只保存摘要；管理登入仍是必要條件，居民與匿名身份不可使用控制 API。原全站舊模式仍保留原 Google 保護，今次只有 hardware-only 模式改為平台管理登入。

不接受任意網址、client operator key 或重新導向，不自動重送結果不明的控制指令。原租約、放開即停、影像時效及故障保護保留。入頁只讀清單／已有組網碼，不自動搜尋、配網、連線、開鏡頭或移動。離開分頁會通知原控制台放開控制。

現場電腦及轉接程式需保持運行，才能使用街外控制；居民對話與管理資料仍可在 Notebook 關機後由雲端提供。自動巡查辨識／新相片上傳尚未接通此硬件程式的雲端回報，仍明示停用，未在此次 UI 更新中冒稱完成。

## 驗證與資料保留

`frontend28` lint／typecheck／build 通過，原生源碼 byte 還原，未寫入原生 dist。隔離瀏覽器使用新測試 profile、合成身份／資料與靜音假音訊，核對三輪上下文、曉曼請求格式、模型載入、無重播按鈕、桌面／手機登入、原版九入口、單行工具列及內嵌控制台；沒有真人收音、播放或真供應商請求。

Python 路由／轉接／角色／部署閘門測試、Node 傳輸與動作測試通過。正式 HTTPS 程式及 main/settings chunk SHA 符合 manifest；管理身份 relay 真 GET 200，匿名 401、居民 403，現場公開無身份 401 且沒有 Google redirect。只讀清單顯示兩部機體未連線，沒有控制指令或新工單。

部署先以全新 release barrier 啟動唯讀維護殼。獨立核對舊 s9lw6/PID40 已於 00:45:50 UTC 退出，唯一新 tvn85/PID58、完整生命週期無舊程序重啟；平台 live 超過 90 秒、保存正式資料只讀基線後，才寫入新的簽署技術放行行。原 probe、quota、controls 未覆寫，沒有 ENV／金鑰變更、DDL 或重匯；不可重用本次放行部署其他程式。

前後 8 個案及 8 短號、設定、三個控制狀態摘要相同，MB842=1，全部原 quota 期不減；原六份 EP 記錄 SHA 相同。現場既有硬件程式與兩個 console_worker 父子程序保持原樣，均非本次啟動；只更新遠端轉接程式，唯讀確認所有機體未連線及無控制／影像活動後才切換。沒有初始化、連線、鏡頭、移動或警示。

原退休 Render 服務保持暫停，native cloud-primary fence 保留。Gemma＋Azure 曉曼 F0、Whisper／Tavily、90 日保存與 managed backup 規則不變。實際聽感、真人咪及實機遙控仍由用戶驗收。

完整收據：`.runtime/ui-polish-20261102/HANDOFF.json`、`LIVE-HTTP-VERIFIED.json`、`CONSERVATION-BEFORE.json`、`CONSERVATION-AFTER.json`、`ACTIVATION-STOP-RECEIPT.json`、`ROLLOUT-APPROVAL-RECEIPT.json`。
