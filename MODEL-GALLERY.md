# 模型圖庫及安全整理（2026-11-02）

本平台用途由擁有人確認為非商業學習。保留 Gemma、Azure 曉曼 F0、Cloudflare Whisper、Tavily、全部原有資料及用量；未操作 EP、真人麥克風或播放音訊。

## 使用方法

管理工作台 → 數字人設定 → 角色模型。現有 23 款已核對的一鍵預覽，包括原有 7 款、本輪 15 款及按非商業用途重新核對的ずんだもん。預覽後按原有「儲存至平台」才發佈，居民正在進行的對話不會被中途換角。

每次已驗證的職員進入工作台，背景檢查 Live2D 官方、VTuber Nook 與模之屋公開目錄。一分鐘內重複進入合併；一般居民啟動仍用六小時快取。更新不擋住工作台，不消耗 AI API quota；來源失敗時保留上次清單。今次實讀為官方 28 組、Nook 124 條（含精選）及模之屋 297 個 Live2D 條目，不代表全部都可匯入。

新增條目會自動出現在外站目錄。已核對版本對應一鍵預覽；未知作者條款、禁止轉發、收費或需要登入／驗證的項目保留來源及原因，不繞過作者限制，不自動轉存未知 ZIP，也不自動更換居民角色。

## 自動整理自己的 ZIP

選 ZIP、確認有權在平台使用，按「自動整理並預覽」。若 ZIP 有多款模型，先列出供選擇，不默認取第一款。支援嵌套檔案、路徑斜線／大小寫及執行檔重整；保留原 moc3、貼圖 bytes 及文字授權；移除編輯專案和額外音效連接，維持曉曼。按可見角色範圍等比例取景，現有舊式口型參數可接回平台朗讀。

原檔保留在使用者裝置；整理 API 不寫入模型庫或發佈設定，失敗不改原角色。32 MiB 輸入、128 MiB 解壓上限、1024 檔案上限，ZIP 中央目錄先檢查再讀取，同時只處理一款。沒有把 PSD/cmo3、Cubism 2、加密 ZIP 或新版核心模型假裝轉換成功，也不自動壓縮貼圖畫質。此功能仍需實際預覽，無法補畫缺失部件。

ずんだもん原 ZIP 9,303,563 bytes → 執行包約 2.8 MiB；原 ReadMe、來源及角色指引保留。實際半身模型及口型參數通過隔離瀏覽器。Rice 可顯示，但沒有通用開口參數，不承諾與其他模型相同的口型。

## 為何非商業仍不等於全部可以轉存

免費下載、教育用途、可展示及可重新分發是不同條件。需同時核對模型作者、角色權利人、轉存／再分發及署名；部分聯名角色明確不容許轉發。沒有改模型設計仍可能涉及原檔複製。來源：Live2D 樣本條款 https://www.live2d.com/en/learn/sample/model-terms/ ；免費素材協議 https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html ；ずんだもん指引 https://zunko.jp/guideline.html 。

Miku 另核對 PCL 正文 https://piapro.jp/license/pcl 及角色指引 https://piapro.jp/license/character_guideline （公開、宣傳及模型轉存條件不可只看免費標籤）。Unity-chan 官方舊授權頁目前跳轉未提供可讀的相應正文，本輪沒有擅自當作開放授權。兩款保留待核對，而不是宣稱一律禁止非商業。

## 其餘 23 組官方樣本逐款結果

| 官方組別 | 本輪結果 | 原因 |
|---|---|---|
| [ずんだもん](https://www.live2d.com/en/learn/sample/zundamon/) | 一鍵預覽 1 款 | 用戶已明確非商業學習用途；Live2D 免費素材／樣本條款及角色方非商業指引重新核對，原 ReadMe／標示保留，AIRI 實際半身預覽通過。 |
| [Ren Foster](https://www.live2d.com/en/learn/sample/ren-foster/) | 未加入一鍵包 | 新格式模型被現有 AIRI Cubism 5.0 核心拒絕；官方指示 5.3 需整體 SDK 更新，不能只換核心。 |
| [Sample for Parameter Controller](https://www.live2d.com/en/learn/sample/param-ctrl/) | 未加入一鍵包 | 官方 ZIP 只有編輯／動畫素材，未提供 .moc3／.model3.json 執行檔。 |
| [Kei](https://www.live2d.com/en/learn/sample/kei/) | 一鍵預覽 2 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [Hatsune Miku](https://www.live2d.com/en/learn/sample/hatsune-miku/) | 未加入一鍵包 | 非商業學習用途已記錄，但 PCL 另有限制宣傳／廣告用途；尚未核對本平台公開展示及模型轉存的全部適用條件，未當作禁止所有非商用。 |
| [Jin Natori](https://www.live2d.com/en/learn/sample/natori-jin/) | 未加入一鍵包 | 聯名角色條款禁止轉發檔案；只提供官方入口。 |
| [Miara](https://www.live2d.com/en/learn/sample/miara/) | 一鍵預覽 1 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [Tororo & Hijiki](https://www.live2d.com/en/learn/sample/tororo-hijiki/) | 一鍵預覽 2 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [Mark-kun (video version)](https://www.live2d.com/en/learn/sample/mark-video/) | 未加入一鍵包 | 影片製作用素材，官方 ZIP 未提供可執行模型。 |
| [Hiyori Momose (video version)](https://www.live2d.com/en/learn/sample/momose-hiyori-video/) | 未加入一鍵包 | 影片製作用素材，官方 ZIP 未提供可執行模型。 |
| [Simple model](https://www.live2d.com/en/learn/sample/simple-model/) | 一鍵預覽 1 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [Epsilon](https://www.live2d.com/en/learn/sample/epsilon/) | 未加入一鍵包 | 已實際測試：目前 AIRI 畫面有缺件／透明／構圖異常，未通過完整角色顯示驗收。 |
| [Haru](https://www.live2d.com/en/learn/sample/haru/) | 未加入一鍵包 | 已實際測試：目前 AIRI 畫面有缺件／透明／構圖異常，未通過完整角色顯示驗收。 |
| [Chitose](https://www.live2d.com/en/learn/sample/chitose/) | 一鍵預覽 1 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [Shizuku](https://www.live2d.com/en/learn/sample/shizuku/) | 未加入一鍵包 | 已實際測試：目前 AIRI 畫面有缺件／透明／構圖異常，未通過完整角色顯示驗收。 |
| [Hibiki](https://www.live2d.com/en/learn/sample/hibiki/) | 未加入一鍵包 | 已實際測試：目前 AIRI 畫面有缺件／透明／構圖異常，未通過完整角色顯示驗收。 |
| [Koharu & Haruto](https://www.live2d.com/en/learn/sample/koharu-haruto/) | 一鍵預覽 2 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [[Collaboration character] Tsumiki Harugasa](https://www.live2d.com/en/learn/sample/tsumiki-harugasa/) | 未加入一鍵包 | 聯名角色條款禁止轉發檔案；只提供官方入口。 |
| [Unity-chan](https://www.live2d.com/en/learn/sample/unity-chan/) | 未加入一鍵包 | 官方授權連結目前轉至未顯示條款內容的新頁，未能確認平台轉存條件。 |
| [Izumi](https://www.live2d.com/en/learn/sample/izumi/) | 未加入一鍵包 | 已實際測試：目前 AIRI 畫面有缺件／透明／構圖異常，未通過完整角色顯示驗收。 |
| [Gantzert & Felixander](https://www.live2d.com/en/learn/sample/gantzert-felixander/) | 未加入一鍵包 | 已實際測試：目前 AIRI 畫面有缺件／透明／構圖異常，未通過完整角色顯示驗收。 |
| [Nito](https://www.live2d.com/en/learn/sample/nito/) | 一鍵預覽 5 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |
| [Rice Glassfield](https://www.live2d.com/en/learn/sample/rice-glassfield/) | 一鍵預覽 1 款 | 官方原創授權及原條件已核對；AIRI 實際完整角色預覽通過。 |

## 驗證與部署證據

原 22 款在 frontend53 已逐款實際 canvas 驗證；frontend55 核對原包 SHA 不變、原款與新增第 23 款的一鍵預覽、來源分頁及文字轉義，原版 ZIP Import→一次不可變上載→儲存→另一瀏覽器讀回，以及損壞包保留原角色仍可對話。新增整理功能實際 UI 預覽，後端權限／不寫模型庫／格式錯誤／路徑／多模型／重新啟動的持久刷新間隔等測試通過。

證據位置：`.runtime/gallery-expansion-20261102/` 與 `.runtime/gallery-refresh-20261102/`。正式版本、原資料／quota 保留及停止舊寫入者的簽收請讀最新 HANDOFF.json；不因這份文件另行重部署。
