"""Native Windows HID backend using ctypes — no external dependencies."""
import ctypes, ctypes.wintypes as wt

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hiddll = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
OPEN_EXISTING = 3
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD),
                ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT),
                ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
                ("InputReportByteLength", wt.USHORT), ("OutputReportByteLength", wt.USHORT),
                ("FeatureReportByteLength", wt.USHORT), ("Reserved", wt.USHORT * 17),
                ("NumberLinkCollectionNodes", wt.USHORT),
                ("NumberInputButtonCaps", wt.USHORT), ("NumberInputValueCaps", wt.USHORT),
                ("NumberInputDataIndices", wt.USHORT),
                ("NumberOutputButtonCaps", wt.USHORT), ("NumberOutputValueCaps", wt.USHORT),
                ("NumberOutputDataIndices", wt.USHORT),
                ("NumberFeatureButtonCaps", wt.USHORT), ("NumberFeatureValueCaps", wt.USHORT),
                ("NumberFeatureDataIndices", wt.USHORT)]


# --- Set up function signatures for 64-bit correctness ---

setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]

setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]

setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]

setupapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

kernel32.CreateFileW.restype = ctypes.c_void_p
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]

kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
kernel32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]

hiddll.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDD_ATTRIBUTES)]
hiddll.HidD_GetAttributes.restype = wt.BOOLEAN
hiddll.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
hiddll.HidD_GetPreparsedData.restype = wt.BOOLEAN
hiddll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hiddll.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hiddll.HidD_GetProductString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
hiddll.HidD_GetProductString.restype = wt.BOOLEAN


def _get_hid_guid():
    guid = GUID()
    hiddll.HidD_GetHidGuid(ctypes.byref(guid))
    return guid


def enumerate_hid(vendor_id=None):
    """Enumerate HID devices, returning dicts compatible with hidapi's format."""
    guid = _get_hid_guid()
    hdev_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev_info == INVALID_HANDLE_VALUE:
        return []

    devices = []
    iface_data = SP_DEVICE_INTERFACE_DATA()
    iface_data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
    idx = 0

    try:
        while setupapi.SetupDiEnumDeviceInterfaces(hdev_info, None, ctypes.byref(guid), idx, ctypes.byref(iface_data)):
            idx += 1
            # Get required buffer size
            required_size = wt.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev_info, ctypes.byref(iface_data), None, 0, ctypes.byref(required_size), None)
            # Allocate buffer with SP_DEVICE_INTERFACE_DETAIL_DATA_W header
            buf = ctypes.create_string_buffer(required_size.value)
            # cbSize = size of fixed part (DWORD + one WCHAR on x64 = 8)
            detail_size = ctypes.c_uint(8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)
            ctypes.memmove(buf, ctypes.byref(detail_size), 4)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdev_info, ctypes.byref(iface_data), buf, required_size, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)

            # Open device to get attributes and caps
            handle = kernel32.CreateFileW(
                path, GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
            if handle == INVALID_HANDLE_VALUE:
                # Try read-only for enumeration
                handle = kernel32.CreateFileW(
                    path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
            if handle == INVALID_HANDLE_VALUE:
                continue

            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
                if not hiddll.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                    continue

                if vendor_id and attrs.VendorID != vendor_id:
                    continue

                # Get usage page and usage from preparsed data
                usage_page, usage = 0, 0
                preparsed = ctypes.c_void_p()
                if hiddll.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                    try:
                        caps = HIDP_CAPS()
                        hiddll.HidP_GetCaps(preparsed, ctypes.byref(caps))
                        usage_page = caps.UsagePage
                        usage = caps.Usage
                    finally:
                        hiddll.HidD_FreePreparsedData(preparsed)

                # Get product string
                product_buf = ctypes.create_unicode_buffer(128)
                name = ""
                if hiddll.HidD_GetProductString(handle, product_buf, 256):
                    name = product_buf.value

                devices.append({
                    "path": path,
                    "vendor_id": attrs.VendorID,
                    "product_id": attrs.ProductID,
                    "product_string": name,
                    "usage_page": usage_page,
                    "usage": usage,
                })
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev_info)
    return devices


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", ctypes.c_void_p)]

FILE_FLAG_OVERLAPPED = 0x40000000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102

kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
kernel32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wt.DWORD), wt.BOOL]
kernel32.CancelIo.argtypes = [ctypes.c_void_p]
kernel32.ResetEvent.argtypes = [ctypes.c_void_p]


class HidDevice:
    """Minimal HID device wrapper using Windows HID API."""

    def __init__(self, path):
        self._handle = None
        self._event = None
        self._handle = kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if self._handle == INVALID_HANDLE_VALUE:
            raise OSError(f"Cannot open HID device: {path}")
        self._event = kernel32.CreateEventW(None, True, False, None)
        if not self._event or self._event == INVALID_HANDLE_VALUE:
            raise OSError("Cannot create event object for overlapped I/O")

    def write(self, data):
        ol = OVERLAPPED()
        ol.hEvent = self._event
        buf = (ctypes.c_ubyte * len(data))(*data)
        kernel32.ResetEvent(self._event)
        kernel32.WriteFile(self._handle, buf, len(data), None, ctypes.byref(ol))
        kernel32.WaitForSingleObject(self._event, 5000)
        written = wt.DWORD(0)
        kernel32.GetOverlappedResult(self._handle, ctypes.byref(ol), ctypes.byref(written), False)

    def read(self, size, timeout=None):
        ol = OVERLAPPED()
        ol.hEvent = self._event
        buf = (ctypes.c_ubyte * size)()
        read_bytes = wt.DWORD(0)
        kernel32.ResetEvent(self._event)
        kernel32.ReadFile(self._handle, buf, size, None, ctypes.byref(ol))
        wait_ms = timeout if timeout else 5000
        rc = kernel32.WaitForSingleObject(self._event, wait_ms)
        if rc == WAIT_TIMEOUT:
            kernel32.CancelIo(self._handle)
            return None
        kernel32.GetOverlappedResult(self._handle, ctypes.byref(ol), ctypes.byref(read_bytes), False)
        if read_bytes.value > 0:
            return list(buf[:read_bytes.value])
        return None

    def close(self):
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._event:
            kernel32.CloseHandle(self._event)
            self._event = None

    def __del__(self):
        self.close()
