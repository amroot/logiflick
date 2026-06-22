#!/usr/bin/env python3
"""logiflick - Set DPI on Logitech mice without Logi Options+

Requires: pip install hidapi

Usage:
    logiflick                       # show current DPI
    logiflick 1600                  # set DPI persistently (writes to onboard profile)
    logiflick -t 1600               # set DPI for this session only (lost on power cycle)
    logiflick --list                # list supported DPI values
"""
import sys, struct, time

try:
    import hid
except ImportError:
    if sys.platform == "linux":
        from backends._linux_hid import HidDevice, enumerate_hid
    elif sys.platform == "win32":
        from backends._win_hid import HidDevice, enumerate_hid
    else:
        sys.exit(
            "hidapi is required on macOS (no built-in HID backend available).\n"
            "Install it with: pip install hidapi\n"
            "Or: brew install hidapi && pip install hidapi"
        )
    hid = None

LOGITECH_VID = 0x046D
HIDPP_LONG = 0x11
MSG_LEN = 20
FEATURE_DPI = 0x2201
FEATURE_DPI_EXT = 0x2202
FEATURE_ONBOARD_PROFILES = 0x8100


def find_hidpp_device():
    """Find the HID++ control interface (not the mouse input interface)."""
    if hid:
        devs = hid.enumerate(LOGITECH_VID)
    else:
        devs = enumerate_hid(LOGITECH_VID)
    for dev in devs:
        if dev.get("usage_page") == 0xFF00 and dev.get("usage") == 0x0001:
            return dev
        if dev.get("usage_page") == 0xFF43:
            return dev
    for dev in devs:
        if dev.get("usage_page", 0) >= 0xFF00:
            return dev
    return None


def hidpp_request(device, dev_idx, feat_idx, func, *params):
    """Send HID++ 2.0 long message, return response payload."""
    sw_id = 0x0A
    msg = struct.pack("BBBB", HIDPP_LONG, dev_idx, feat_idx, (func << 4) | sw_id)
    msg += bytes(params)
    msg = msg.ljust(MSG_LEN, b"\x00")
    device.write(msg)
    for _ in range(10):
        resp = device.read(MSG_LEN, timeout=2000)
        if not resp:
            continue
        if len(resp) < MSG_LEN:
            continue
        if resp[2] == feat_idx and (resp[3] & 0x0F) == sw_id:
            return resp[4:]
        if resp[2] == 0xFF:
            raise RuntimeError(f"HID++ error: feat={feat_idx:#x} func={func} err={resp[4]:#x}")
    raise TimeoutError("No response from device")


def get_feature_index(device, dev_idx, feature_id):
    """Ask IRoot (index 0) for the index of a feature."""
    resp = hidpp_request(device, dev_idx, 0x00, 0x00, (feature_id >> 8) & 0xFF, feature_id & 0xFF)
    return resp[0] if resp[0] != 0 else None


def get_dpi(device, dev_idx, dpi_idx, extended=False):
    func = 0x05 if extended else 0x02
    resp = hidpp_request(device, dev_idx, dpi_idx, func, 0x00)
    val = (resp[1] << 8) | resp[2]
    return val if val != 0 else (resp[3] << 8) | resp[4]


def set_dpi(device, dev_idx, dpi_idx, dpi_value, extended=False):
    func = 0x06 if extended else 0x03
    hidpp_request(device, dev_idx, dpi_idx, func, 0x00, (dpi_value >> 8) & 0xFF, dpi_value & 0xFF)


def list_dpi(device, dev_idx, dpi_idx, extended=False):
    """Query the supported DPI range from the device."""
    func = 0x02 if extended else 0x01
    ignore = 3 if extended else 1
    dpi_bytes = b""
    max_dpi_bytes = 512
    for i in range(0x100):
        params = (0x00, 0x00, i) if extended else (0x00, i)
        resp = hidpp_request(device, dev_idx, dpi_idx, func, *params)
        dpi_bytes += bytes(resp[ignore:])
        if dpi_bytes[-2:] == b"\x00\x00":
            break
        if len(dpi_bytes) >= max_dpi_bytes:
            break
    result, i = [], 0
    while i + 1 < len(dpi_bytes):
        val = (dpi_bytes[i] << 8) | dpi_bytes[i + 1]
        if val == 0:
            break
        if val >> 13 == 0b111:
            if i + 3 >= len(dpi_bytes):
                break
            step = val & 0x1FFF
            last = (dpi_bytes[i + 2] << 8) | dpi_bytes[i + 3]
            if result and step > 0:
                result += list(range(result[-1] + step, last + 1, step))
            i += 4
        else:
            result.append(val)
            i += 2
    return result


# --- Onboard Profile persistence ---

def crc16(data):
    """CRC-CCITT used by Logitech onboard profiles."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def read_profile_sector(device, dev_idx, prof_idx, sector, size):
    """Read a full profile sector from device memory."""
    data = b""
    o = 0
    while o < size:
        chunk = hidpp_request(device, dev_idx, prof_idx, 0x05,
                              sector >> 8, sector & 0xFF, o >> 8, o & 0xFF)
        data += bytes(chunk[:16])
        o += 16
    return data[:size]


def write_profile_sector(device, dev_idx, prof_idx, sector, data):
    """Write a full profile sector to device memory."""
    size = len(data)
    hidpp_request(device, dev_idx, prof_idx, 0x06,
                  sector >> 8, sector & 0xFF, 0, 0, size >> 8, size & 0xFF)
    o = 0
    while o < size:
        chunk = data[o:o + 16].ljust(16, b"\xff")
        hidpp_request(device, dev_idx, prof_idx, 0x07, *chunk)
        o += 16
    hidpp_request(device, dev_idx, prof_idx, 0x08)


def get_active_profile_sector(device, dev_idx, prof_idx):
    """Get the sector of the currently active profile."""
    resp = hidpp_request(device, dev_idx, prof_idx, 0x04)
    return (resp[0] << 8) | resp[1]


def get_profile_info(device, dev_idx, prof_idx):
    """Get profile memory layout info."""
    resp = hidpp_request(device, dev_idx, prof_idx, 0x00)
    size = (resp[7] << 8) | resp[8]
    return {"size": size, "count": resp[3]}


def persist_dpi(device, dev_idx, prof_idx, dpi_value):
    """Write DPI to the active onboard profile for persistence across power cycles."""
    info = get_profile_info(device, dev_idx, prof_idx)
    sector = get_active_profile_sector(device, dev_idx, prof_idx)
    size = info["size"]

    print(f"  Reading profile sector {sector:#x} ({size} bytes)...")
    profile_data = bytearray(read_profile_sector(device, dev_idx, prof_idx, sector, size))

    default_idx = profile_data[1]
    slot_offset = 3 + (default_idx * 2)
    if slot_offset + 2 > size - 2:
        raise RuntimeError(f"Profile slot index {default_idx} out of bounds (sector size {size})")

    existing_dpi = struct.unpack_from("<H", profile_data, slot_offset)[0]
    if existing_dpi > 32000:
        raise RuntimeError(
            f"Profile slot {default_idx} contains unexpected value {existing_dpi} "
            f"(expected a DPI 0–32000) — refusing to overwrite potentially corrupt data")

    # DPI is stored little-endian in Logitech onboard profiles
    struct.pack_into("<H", profile_data, slot_offset, dpi_value)

    crc = crc16(profile_data[:-2])
    # CRC-CCITT is stored big-endian
    struct.pack_into(">H", profile_data, size - 2, crc)

    print(f"  Writing DPI {dpi_value} to profile slot {default_idx}...")
    write_profile_sector(device, dev_idx, prof_idx, sector, bytes(profile_data))
    print("  ✓ Saved to onboard memory. Persists across power cycles.")


# --- Public API ---

class LogiFlick:
    """Lightweight interface to Logitech mouse DPI over HID++ 2.0.

    Usage as a library:
        from logiflick import LogiFlick
        mouse = LogiFlick()
        print(mouse.current_dpi)
        mouse.set(1600)
        mouse.set(1600, persist=False)  # session only
    """

    def __init__(self):
        dev_info = find_hidpp_device()
        if not dev_info:
            raise RuntimeError("No Logitech HID++ device found")
        if hid:
            self._device = hid.Device(path=dev_info["path"])
        else:
            self._device = HidDevice(dev_info["path"])
        self.name = dev_info.get("product_string", "Unknown")
        self._dev_idx = None
        self._dpi_idx = None
        self._extended = False
        self._discover()

    def _discover(self):
        for idx in (0xFF, 0x01, 0x02):
            try:
                dpi_idx = get_feature_index(self._device, idx, FEATURE_DPI_EXT)
                extended = True
                if not dpi_idx:
                    dpi_idx = get_feature_index(self._device, idx, FEATURE_DPI)
                    extended = False
                if dpi_idx:
                    self._dev_idx, self._dpi_idx, self._extended = idx, dpi_idx, extended
                    return
            except (TimeoutError, RuntimeError):
                continue
        raise RuntimeError("DPI feature not found on device")

    @property
    def current_dpi(self) -> int:
        return get_dpi(self._device, self._dev_idx, self._dpi_idx, self._extended)

    @property
    def supported_dpi(self) -> list:
        return list_dpi(self._device, self._dev_idx, self._dpi_idx, self._extended)

    def set(self, dpi: int, persist: bool = True):
        """Set DPI. Writes to onboard memory by default."""
        if not isinstance(dpi, int) or not (0 < dpi <= 0xFFFF):
            raise ValueError(f"DPI must be an integer between 1 and 65535, got {dpi!r}")
        set_dpi(self._device, self._dev_idx, self._dpi_idx, dpi, self._extended)
        time.sleep(0.1)
        if persist:
            prof_idx = get_feature_index(self._device, self._dev_idx, FEATURE_ONBOARD_PROFILES)
            if prof_idx:
                persist_dpi(self._device, self._dev_idx, prof_idx, dpi)
        return self.current_dpi

    def close(self):
        self._device.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# --- CLI ---

def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="logiflick",
        description="Simple, lightweight DPI control for Logitech mice")
    parser.add_argument("dpi", nargs="?", type=int, help="Target DPI value")
    parser.add_argument("-t", "--test", action="store_true",
                        help="Session only — don't write to onboard profile")
    parser.add_argument("--list", action="store_true", help="List supported DPI values")
    parser.add_argument("--get", action="store_true", help="Show current DPI")
    parser.add_argument("--debug", action="store_true", help="List all HID devices found")
    args = parser.parse_args()

    if args.debug:
        if hid:
            devs = hid.enumerate()
        else:
            devs = enumerate_hid()
        for d in devs:
            print(f"  VID={d.get('vendor_id', 0):#06x} PID={d.get('product_id', 0):#06x} "
                  f"usage_page={d.get('usage_page', 0):#06x} usage={d.get('usage', 0):#04x} "
                  f"name={d.get('product_string', '')!r}")
        if not devs:
            print("  No HID devices found.")
        return

    with LogiFlick() as mouse:
        print(f"logiflick — {mouse.name}")

        if args.list:
            values = mouse.supported_dpi
            if not values:
                print("No supported DPI values reported by the device.")
            elif len(values) == 1:
                print(f"Supported: {values[0]} DPI (1 level)")
            else:
                print(f"Supported: {min(values)}-{max(values)} DPI (step {values[1]-values[0]}, {len(values)} levels)")
        elif args.get or args.dpi is None:
            print(f"Current DPI: {mouse.current_dpi}")
        else:
            actual = mouse.set(args.dpi, persist=not args.test)
            print(f"DPI set to: {actual}")
            if args.test:
                print("  (session only — will revert on power cycle)")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
