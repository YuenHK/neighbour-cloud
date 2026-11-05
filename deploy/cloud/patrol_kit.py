"""A bounded source-only review kit; generating it does not open any hardware."""
import hashlib
import io
import json
import zipfile
from pathlib import Path


def source_kit():
    root = Path(__file__).resolve().parents[2]
    names = ('edge_hub/fiducial_localisation.py', 'edge_hub/route_follower.py',
             'edge_hub/s1_lab.py', 'edge_hub/s1_sbus.py')
    contents = {'edge_hub/__init__.py': b''}
    for name in names:
        path = root/name
        if path.is_symlink() or path.stat().st_size > 100_000:
            raise ValueError('unexpected_kit_source')
        contents[name] = path.read_bytes()
    from edge_hub.s1_lab import closed_course_lab_script, readonly_lab_script
    from edge_hub.s1_sbus import route_capabilities
    contents['s1-lab-readonly.py'] = readonly_lab_script().encode()
    contents['s1-lab-closed-course-DISABLED.py'] = closed_course_lab_script([(0., 0.), (.3, 0.)]).encode()
    contents['s1-capabilities.json'] = json.dumps(route_capabilities(), ensure_ascii=False, indent=2).encode()
    # Local CLI is not a runtime dependency of the cloud host.
    tool = root/'tools/localisation_replay.py'
    if tool.is_file():
        contents['localisation_replay.py'] = tool.read_bytes()
    contents['README.txt'] = '''鄰伴 S1／定位離機準備工具

本工具沒有串口、SDK連線或開機自動執行功能，不會控制 EP。
s1-lab-readonly.py 可由本人放入官方 RoboMaster Lab，讀取一次位置／姿態變數。
開機里程座標並不等於樓層地圖定位，須先核對單位、軸向及漂移。

SBus 是 DJI 官方 S1 外接板路線，須韌體、腳位、反相及電平匹配。
不能把 UNO 的 5V TX 直接插入 S1。程式只編解碼及產生記憶體預覽。
缺少現場接線／停止／通道驗收，不會啟用硬件輸出。

fiducial_localisation.py 只分析已儲存 JPEG。
須實測鏡頭內參、畸變、黑方塊尺寸、各標記在地圖的位置及固定相機安裝。
沒有標記、影像過期、鏡頭轉動或解有歧義，回傳未定位，不猜位置。
localisation_replay.py marker --id 7 --output marker7.png 產生標記。
使用現有已核對的 Python/OpenCV/numpy/Pillow 環境，不自動安裝程式。

route_follower.py 只作閉環重播，必須另外有新鮮障礙感測，儲存地圖不能當避障。
S1 任務源碼（如有）預設只模擬；封閉場地人工確認後才可自行試用。
沒有公共空間自主行車、SLAM或真機驗收的完成聲明。
'''.encode()
    manifest = {'format': 'neighbour-patrol-review-kit-v1', 'hardware_commands': 0,
        'execution_enabled': False, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    contents['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    return output.getvalue()
