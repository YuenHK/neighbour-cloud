# 多標記聯合定位：離機候選

這一批新增 `edge_hub/board_localisation.py`，沿用已有的相機／標記校準資料及定位輸出介面，沒有修改已部署的單標記程式或行車控制器。新方法只分析已儲存 JPEG；不開相機、網絡、串口或 SDK，也不會給予移動權限。

原方法逐一估計每張標記的位置，再取誤差較小的一張。新方法將至少兩張已勘察標記的全部角點，放在同一個世界座標下共同求解。它需要實測相機內參／畸變、固定相機安裝、標記尺寸及相對位置，不能從截圖或地圖猜尺度。[OpenCV board 說明](https://docs.opencv.org/4.13.0/db/da9/tutorial_aruco_board_detection.html)

共面角點採用 IPPE，非共面角點採用 SQPnP，保留每個原始可能解與細化後的解。只要有誤差接近、但位置或角度相差過大的物理解，就回報未定位；不能因為細化程序最後收斂到同一個點，就當作歧義已消失。至少兩張標記亦不代表一定可靠，還要通過角點面積、影像／世界基線、幾何分布、正深度、平地姿態、逐標記重投影及局部數值可觀測性檢查。[OpenCV PnP 方法](https://docs.opencv.org/4.13.0/d5/d1f/calib3d_solvePnP.html)

局部數值敏感度只計入假設的像素雜訊，不包括實際鏡頭校準誤差、標記張貼偏差或世界模型誤差，因此不是屋苑實際精準度／信賴區間。程式明確回傳 `motion_authorized=false` 及 `is_real_world_accuracy_guarantee=false`。新方法需要 2–12 個不同的已勘察標記；失去足夠標記時不會暗中切回單標記或用舊位置推算。

## 固定合成比較

`tools/navigation_board_lab.py` 產生 54 幀真正經投影、加雜訊及 JPEG 壓縮的 ArUco 影像，包括共面與非共面布局、三種位置、橫移及正面零角度。兩種方法使用同一批影像及完全相同的合成校準，沒有接觸真人影像或機體。

| 合成測量 | 原逐標記法 | 新聯合法 |
| --- | ---: | ---: |
| 定位／總幀數 | 51／54 | 53／54 |
| 被拒絕幀數 | 3 | 1 |
| 定位成功幀平均位置誤差 | 2.34 cm | 0.885 cm |
| 定位成功幀 P95 位置誤差 | 8.65 cm | 2.15 cm |
| 定位成功幀最大位置誤差 | 9.74 cm | 2.34 cm |
| 兩者都成功的相同 50 幀平均誤差 | 2.36 cm | 0.875 cm |
| 此次純處理平均時間 | 2.58 ms | 3.21 ms |

新方法增加了少量計算，沒有宣稱更快。它拒絕的一幀是共面正面近似解；同一類正面情況換成有充分非共面幾何的標記布局，測試可得到位置。這些數字只描述該 54 幀、該部電腦和該 OpenCV 版本，不能當作真機準確率、SLAM、導航成功率或物理停止保證。

重播命令：

```powershell
& .venv/Scripts/python.exe -m tools.navigation_board_lab --output .runtime/gaia-expansion-20261105/navigation/BENCHMARK-replay.json
```

工具拒絕覆寫已有報告。現有比較保留在 `.runtime/gaia-expansion-20261105/navigation/BENCHMARK-54.json`。缺標記、重複編號、錯誤勘察、過期／未固定鏡頭、差幾何及禁相機／禁網絡測試另行驗證。

## 整合邊界

```python
from edge_hub.board_localisation import BoardLocaliser
from edge_hub.fiducial_localisation import Calibration

localiser = BoardLocaliser(Calibration.parse(measured_calibration))
pose = localiser.estimate(saved_jpeg, frame_key=frame_identity,
    captured_at_ms=captured_ms, now_ms=observed_ms, camera_fixed=True)
```

應由職員明確選擇聯合標記模式。定位成功仍不代表路徑有即時安全空間；原有行車重播所需的獨立障礙觀測、地圖／校準綁定及停止規則全部保留。實際使用前仍需量度現場標記位置、鏡頭校準與機體安裝，並完成人在場的機體停止及障礙驗收。
