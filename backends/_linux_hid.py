"""Native Linux HID backend using /dev/hidraw* — no external dependencies."""
import os, struct, glob


def _parse_report_descriptor(path):
    """Extract usage_page and usage from a HID report descriptor."""
    try:
        with open(path, "rb") as f:
            desc = f.read()
    except (OSError, PermissionError):
        return 0, 0
    usage_page, usage = 0, 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        size = prefix & 0x03
        if size == 3:
            size = 4
        tag = prefix & 0xFC
        if i + 1 + size > len(desc):
            break
        val = int.from_bytes(desc[i + 1:i + 1 + size], "little") if size else 0
        if tag == 0x04:  # Usage Page (Global)
            usage_page = val
        elif tag == 0x08:  # Usage (Local)
            usage = val
        if usage_page and usage:
            break
        i += 1 + size
    return usage_page, usage


def _read_uevent(device_path):
    """Read VID/PID and product name from sysfs uevent."""
    try:
        with open(os.path.join(device_path, "uevent")) as f:
            lines = f.read().splitlines()
    except OSError:
        return None, None, None
    vid, pid, name = None, None, ""
    for line in lines:
        if line.startswith("HID_ID="):
            parts = line.split("=")[1].split(":")
            if len(parts) >= 3:
                vid = int(parts[1], 16)
                pid = int(parts[2], 16)
        elif line.startswith("HID_NAME="):
            name = line.split("=", 1)[1]
    return vid, pid, name


def enumerate_hid(vendor_id=None):
    """Enumerate HID devices, returning dicts compatible with hidapi's format."""
    devices = []
    for hidraw in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev_node = "/dev/" + os.path.basename(hidraw)
        device_path = os.path.join(hidraw, "device")
        vid, pid, name = _read_uevent(device_path)
        if vid is None:
            continue
        if vendor_id and vid != vendor_id:
            continue
        desc_path = os.path.join(device_path, "report_descriptor")
        usage_page, usage = _parse_report_descriptor(desc_path)
        devices.append({
            "path": dev_node,
            "vendor_id": vid,
            "product_id": pid,
            "product_string": name,
            "usage_page": usage_page,
            "usage": usage,
        })
    return devices


class HidDevice:
    """Minimal HID device wrapper using /dev/hidraw*."""

    def __init__(self, path):
        self._fd = -1
        self._fd = os.open(path, os.O_RDWR)

    def write(self, data):
        os.write(self._fd, data)

    def read(self, size, timeout=None):
        import select
        timeout_s = timeout / 1000.0 if timeout else None
        r, _, _ = select.select([self._fd], [], [], timeout_s)
        if r:
            return list(os.read(self._fd, size))
        return None

    def close(self):
        if self._fd is not None and self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __del__(self):
        self.close()
