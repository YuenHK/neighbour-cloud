"""Read only the currently connected Windows WLAN profile; never change networks."""
import ctypes as c
import os
import xml.etree.ElementTree as ET
from ctypes import wintypes as w


class WifiError(Exception):
    pass


def profile_values(xml):
    root = ET.fromstring(xml)
    ns = {'w': 'http://www.microsoft.com/networking/WLAN/profile/v1'}
    auth = root.findtext('.//w:authEncryption/w:authentication', '', ns)
    protected = root.findtext('.//w:sharedKey/w:protected', 'true', ns)
    key = root.findtext('.//w:sharedKey/w:keyMaterial', None, ns)
    if auth == 'open':
        return ''
    if protected != 'false' or key is None:
        raise WifiError('Windows 未授權讀取目前 Wi-Fi 密碼；請在本頁隱藏欄位輸入，不需改系統權限。')
    return key


def current_wifi(*, include_password=False):
    if os.name != 'nt':
        raise WifiError('目前 Wi-Fi 自動讀取只支援 Windows。')

    class Interface(c.Structure):
        _fields_ = [('guid', c.c_ubyte * 16), ('description', w.WCHAR * 256), ('state', w.DWORD)]

    class Ssid(c.Structure):
        _fields_ = [('length', w.DWORD), ('data', c.c_ubyte * 32)]

    class Connection(c.Structure):
        _fields_ = [('state', w.DWORD), ('mode', w.DWORD), ('profile', w.WCHAR * 256), ('ssid', Ssid)]

    api = c.WinDLL('wlanapi.dll')
    api.WlanOpenHandle.argtypes = [w.DWORD, c.c_void_p, c.POINTER(w.DWORD), c.POINTER(w.HANDLE)]
    api.WlanEnumInterfaces.argtypes = [w.HANDLE, c.c_void_p, c.POINTER(c.c_void_p)]
    api.WlanQueryInterface.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.c_void_p,
                                      c.POINTER(w.DWORD), c.POINTER(c.c_void_p), c.c_void_p]
    api.WlanGetProfile.argtypes = [w.HANDLE, c.c_void_p, w.LPCWSTR, c.c_void_p,
                                  c.POINTER(c.c_void_p), c.POINTER(w.DWORD), c.POINTER(w.DWORD)]
    api.WlanFreeMemory.argtypes = [c.c_void_p]
    api.WlanCloseHandle.argtypes = [w.HANDLE, c.c_void_p]
    handle, version, listing = w.HANDLE(), w.DWORD(), c.c_void_p()
    if api.WlanOpenHandle(2, None, c.byref(version), c.byref(handle)):
        raise WifiError('Windows Wi-Fi 服務不可用；可手動填寫 Wi-Fi 名稱。')
    try:
        if api.WlanEnumInterfaces(handle, None, c.byref(listing)):
            raise WifiError('無法讀取 Wi-Fi 介面；可手動填寫 Wi-Fi 名稱。')
        count = c.cast(listing, c.POINTER(w.DWORD))[0]
        if count > 64:
            raise WifiError('Wi-Fi 介面資料不符。')
        active = []
        for index in range(count):
            interface = Interface.from_address(listing.value + 8 + index * c.sizeof(Interface))
            if interface.state == 1:
                active.append(interface)
        if len(active) != 1:
            raise WifiError('請先連接一個 Wi-Fi；網線連線亦可手動填寫 EP 要加入的 Wi-Fi。')
        interface = active[0]
        data, size = c.c_void_p(), w.DWORD()
        if api.WlanQueryInterface(handle, c.byref(interface.guid), 7, None, c.byref(size), c.byref(data), None):
            raise WifiError('Windows 不允許讀取目前 Wi-Fi；請在本頁手動填寫。')
        try:
            if size.value < c.sizeof(Connection):
                raise WifiError('Wi-Fi 連線資料不符。')
            connection = c.cast(data, c.POINTER(Connection)).contents
            if not 1 <= connection.ssid.length <= 32:
                raise WifiError('Wi-Fi 名稱長度不符。')
            ssid = bytes(connection.ssid.data[:connection.ssid.length]).decode('utf-8')
            profile = connection.profile
        finally:
            api.WlanFreeMemory(data)
        result = {'ssid': ssid}
        if include_password:
            xml_ptr, flags, access = c.c_void_p(), w.DWORD(4), w.DWORD()
            if api.WlanGetProfile(handle, c.byref(interface.guid), profile, None,
                                  c.byref(xml_ptr), c.byref(flags), c.byref(access)):
                raise WifiError('Windows 未授權讀取 Wi-Fi 密碼；請在本頁隱藏欄位輸入。')
            try:
                xml = c.wstring_at(xml_ptr)
                result['password'] = profile_values(xml)
            finally:
                if xml_ptr.value:
                    c.memset(xml_ptr, 0, (len(c.wstring_at(xml_ptr)) + 1) * c.sizeof(w.WCHAR))
                    api.WlanFreeMemory(xml_ptr)
        return result
    finally:
        if listing.value:
            api.WlanFreeMemory(listing)
        api.WlanCloseHandle(handle, None)
