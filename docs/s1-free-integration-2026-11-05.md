# S1 免費接入：官方路線及離機工具

今次找到一條之前未完整考慮的路線：**原裝 S1 可以經官方 S‑Bus 輸入，由外部開發板控制**，不一定要 root 或修改 S1 韌體。因此，「S1 完全不能外接」並不準確；但這與 EP 的網絡 Python SDK 是兩回事。[DJI 官方 S1 問答](https://www.dji.com/robomaster-s1/specs)

## 已實作及仍待驗收

新增程式只處理離機封包、模擬看門狗、Lab 程式產生及人工診斷資料，沒有串口／socket 寫入器，沒有接駁、初始化、拍攝或移動任何機體。沒有改動原 EP 控制、故障審計或正式資料。

- `edge_hub/s1_sbus.py`：S‑Bus 編解碼及記憶體內的命令預覽。未完成五項實體證據前，不會產生活動預覽；過期、重放、時鐘倒退或錯誤會撤銷舊命令。
- `edge_hub/s1_lab.py`：單次只讀位置／姿態範本，以及預設停用的封閉場地短路線範本。人工匯入的資料永遠不具備即時控制資格。
- `tools/s1_offline_kit.py`：產生可供職員檢視的範本檔案，不覆寫已有工具包。
- `tests/test_s1_free_paths.py`：用假時鐘、假 Lab API、記憶體封包驗證；不是 S1 實機或其專用 Python 解譯器驗收。

## 官方 S‑Bus 接駁

DJI 使用手冊 v1.8 第 48–49 頁列明 S‑Bus 要求 S1 韌體至少 `00.05.0046`，並提供接線與通道表。已逐頁查看原 PDF；本次沒有查詢或更新機體韌體。[DJI 原手冊](https://dl.djicdn.com/downloads/robomaster-s1/20220429UM/RoboMaster_S1_User_Manual_v1.8_EN.pdf)

| 通道 | 官方用途 | 本批離機預覽 |
| --- | --- | --- |
| 1／2 | 底盤橫向／前後 | 小幅度預覽，並非已校準的行車速度 |
| 3 | 雲台俯仰（底盤跟隨模式） | 保持中位 |
| 4 | 自由模式下底盤轉向 | 小幅度預覽 |
| 5／6 | 速度檔／行車模式 | 慢速／自由模式 |
| 7 | 底盤保持輸出／釋放 | 保持輸出，不自動釋放 |
| 其餘通道 | 本批不使用 | 固定中位，沒有發射功能 |

標準 S‑Bus 使用反相的 100000 baud、8E2，25 bytes，含失幀及 failsafe 位元。現有 codec 只接受此格式，拒絕額外數碼通道與未知旗標；沒有直接搬用第三方原碼。[Bolder Flight 協議及 Arduino 實作說明（MIT）](https://github.com/bolderflight/sbus)

原記錄顯示用戶有 UNO R3。它可以設定串口格式，但其 UART 是 5V，並非原生反相 S‑Bus。**只有一塊 UNO，未足以證明可以直接安全接上 S1。** 必須先核對現有線材、反相電路、兩端訊號電壓及接地；S1 插座的供電電壓不能當作訊號耐壓。現場若已有合適電路及三針線，可研究不另購配件；本次沒有購買或假設已經具備。[Arduino UNO 接口](https://docs.arduino.cc/retired/boards/arduino-uno-rev3-with-long-pins/)、[官方串口設定](https://docs.arduino.cc/language-reference/en/functions/communication/serial/begin/)

S‑Bus 是控制輸入，沒有在這條線取得 S1 相機、里程計或停止回覆。Python 模擬的 failsafe 也不能保證主機斷電時機體停止；真正接入前還需要開發板獨立看門狗、斷線／急停實測及在場操作員。只有通過這些證據後，才可另接真實串口 transport。

## 官方 Lab：先讀數，再考慮封閉場地任務

只讀範本採用官方 `get_position_based_power_on`、`get_attitude` 和運行時間 API，單次讀取後結束，變數由職員在 Lab／FPV 監看。沒有假設 Lab 支援 HTTP、socket、JSON 匯出或隱藏 UART API。[DJI Programming Guide](https://www.dji.com/robomaster-s1/programming-guide)

封閉場地範本使用同一份官方指南的 `move_degree_with_speed`、`is_impact` 及 `stop`。預設 `MOTION_ENABLED=False`，連感測器或停止命令都不會呼叫。真正啟用前，須由本人另外確認封閉空曠場地、座標單位與方向，以及實體停止驗收；範本不替人確認。

限制是總路程最多兩米、軸對齊、最高 0.15m/s、二十秒、維持初始朝向。座標跳變、偏離路線、姿態／時間異常、讀取例外或逾時會離開流程並呼叫 `stop`。沒有預先避障；碰撞旗標只代表已經發生碰撞。感測器或 `stop` 若在硬件內阻塞，Python 的 `finally` 不能保證物理停止，仍要本人在場及獨立停止方法。

這是**封閉場地候選程式，不是公共空間自主巡邏**。Power-on 里程計會漂移、重啟會改基準；讀數單位與軸向也要在現場核對。因此人工 snapshot 保留 raw 座標，不能充當已校準地圖位置。平台真正定位／避障／公共區行車仍需另外驗收。

產生離機工具包：

```powershell
& .experiments/cloud-runtime-20261030/python/Scripts/python.exe -m tools.s1_offline_kit --out .runtime/free-paths-20261105/s1/kit
```

此指令只建立檔案。職員日後可檢查並自行貼到官方 Lab；不要設成開機自動程式。本批未執行這些範本於實機。

## 為何沒有直接安裝 ROS／CAN 方案

ROS1 作者在準備步驟明確要求 S1 root，本次排除。[ROS1 作者 README](https://github.com/jukindle/robomaster_ros#preparation)

ROS2 專案雖有 `model:=s1`，其介紹將官方遠端 SDK 支援列為 EP／EP Core；選 S1 模型可以改 URDF／模組，並不能單憑這個名稱證明原裝 S1 可接受 SDK 網絡連線。[ROS2 介紹](https://jeguzzi.github.io/robomaster_ros/introduction.html)、[模型選項](https://jeguzzi.github.io/robomaster_ros/getting_started.html)

Cambridge CAN 程式則需要 Linux SocketCAN 及對應 CAN 硬件，README 的測試配置包括 Raspberry Pi＋CAN HAT、Jetson；不是目前已確認的 UNO 免費直駁方案。本次沒有改機、接 CAN 或繞過保護。[CAN 專案原作者說明](https://github.com/proroklab/robomaster_sdk_can)
