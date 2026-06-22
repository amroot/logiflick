# logiflick

**Simple, lightweight DPI control for Logitech mice. No bloatware required.**

A single-file Python library and CLI that talks directly to your mouse over HID++ 2.0. No background services, no 500MB desktop apps, no GUI. Just set your DPI and move on.

## Features

- **One thing** -- DPI control only. No button remapping, no LED sync, no telemetry.
- **Lightweight** -- ~15KB core, zero required dependencies on Windows and Linux.
- **Cross-platform** -- Windows, macOS, and Linux.
- **Persistent by default** -- Writes to onboard mouse memory. Survives power cycles, OS reinstalls, and switching computers.
- **Library-friendly** -- Import it in your own scripts for programmatic DPI control.

## Supported Devices

Any Logitech mouse that supports HID++ 2.0 with Adjustable DPI (feature `0x2201` or `0x2202`), including:

- MX Master 3S, MX Master 3, MX Master 2S
- MX Anywhere 3 / 3S
- MX Ergo
- G502, G Pro, and most Logitech G mice
- Most Logitech mice from ~2015 onward

Connection methods: Bolt USB receiver, Unifying receiver, or direct Bluetooth.

## Installation

```bash
git clone <repo-url> && cd logiflick
```

**That's it on Windows and Linux** -- no `pip install` needed. Native HID backends are included.

### Optional: hidapi

If the native backend doesn't work for your setup, or you're on macOS:

```bash
pip install hidapi
```

When `hidapi` is installed, logiflick uses it automatically. Otherwise it falls back to the native backend for your platform.

### Platform Notes

**Windows:**
- May require running as Administrator for HID device access, but that wasn't the case during testing.

**Linux:**
- Add a udev rule for non-root access:
  ```bash
  echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0666"' | sudo tee /etc/udev/rules.d/99-logitech.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```
- Install system library if using hidapi: `sudo apt install libhidapi-dev` (Debian/Ubuntu) or `sudo pacman -S hidapi` (Arch).

**macOS:**
- Requires `hidapi`: `brew install hidapi && pip install hidapi`
- macOS may block access to some HID interfaces. Works best with the Bolt USB receiver.

## Usage

### CLI

```bash
# Show current DPI
python logiflick.py

# Set DPI -- persists across power cycles (written to mouse memory)
python logiflick.py 1600

# Set DPI for this session only (reverts on power cycle)
python logiflick.py -t 1600

# List supported DPI values for your mouse
python logiflick.py --list

# Debug: list all HID devices visible to the system
python logiflick.py --debug
```

### Library

```python
from logiflick import LogiFlick

with LogiFlick() as mouse:
    print(mouse.current_dpi)        # 1000
    print(mouse.supported_dpi)      # [200, 250, 300, ..., 8000]
    mouse.set(1600)                 # persistent (writes to onboard memory)
    mouse.set(2400, persist=False)  # session only
```

## Configuration

logiflick has no config file. All settings are passed as CLI flags or library parameters. DPI is stored in onboard mouse memory, not on disk.

### CLI Flags

| Flag | Argument | Description |
|------|----------|-------------|
| *(none)* | -- | Print current DPI and exit |
| *(positional)* | `<dpi>` | Set DPI persistently |
| `-t`, `--test` | `<dpi>` | Set DPI for this session only; reverts on power cycle |
| `--list` | -- | List all DPI steps supported by your mouse |
| `--debug` | -- | List all HID devices visible to the system |

## API Reference

`LogiFlick()` is a context manager that discovers and connects to the first compatible Logitech mouse.

```python
from logiflick import LogiFlick

with LogiFlick() as mouse:
    mouse.current_dpi              # int -- current DPI
    mouse.supported_dpi            # list[int] -- all supported DPI steps
    mouse.set(dpi)                 # write DPI to onboard memory (persistent)
    mouse.set(dpi, persist=False)  # set DPI for active session only
```

| Member | Type | Description |
|--------|------|-------------|
| `current_dpi` | `int` | Current active DPI |
| `supported_dpi` | `list[int]` | All DPI values the mouse supports |
| `set(dpi, persist=True)` | `None` | Write DPI persistently or for session only |

## How It Works

1. **Discovers** the Logitech HID++ control interface (a separate HID endpoint from the mouse input -- the OS does not lock it exclusively).
2. **Queries IRoot** (HID++ feature index 0) to find the DPI feature on the device.
3. **Reads/writes DPI** via Adjustable DPI (`0x2201`) or Extended Adjustable DPI (`0x2202`).
4. **For persistence** (default): reads the active onboard profile sector from flash, patches the DPI slot, recalculates CRC-CCITT, and writes it back.

With `-t` / `--test`, step 4 is skipped -- DPI takes effect immediately but reverts on the next power cycle.

## Protocol Reference

Based on reverse engineering from the [Solaar](https://github.com/pwr-Solaar/Solaar) project (Linux HID++ manager).

### HID++ 2.0 Packet Format (Long Message)

```
Byte 0:     Report ID    (0x11 = long, 20 bytes total)
Byte 1:     Device Index (0xFF = direct USB, 0x01-0x0F = via receiver)
Byte 2:     Feature Index (looked up via IRoot)
Byte 3:     Function ID (high nibble) | Software ID (low nibble)
Bytes 4-19: Parameters / payload
```

### Key Features Used

| Feature | ID | Purpose |
|---------|----|---------|
| IRoot | `0x0000` | Discover feature indices |
| Adjustable DPI | `0x2201` | Read/write mouse sensitivity |
| Extended Adjustable DPI | `0x2202` | Read/write with X/Y separation |
| Onboard Profiles | `0x8100` | Persistent storage in mouse flash |

## Compared to Alternatives

| Tool | Size | Background Process | Platforms | Dependencies |
|------|------|--------------------|-----------|--------------|
| Logi Options+ | ~500MB | Yes (always running) | Win/Mac | -- |
| Solaar | ~15MB | Optional | Linux only | Many |
| Onboard Memory Manager | ~50MB | No | Windows only | -- |
| **logiflick** | **~12KB** | **No** | **Win/Mac/Linux** | **None (Win/Linux)** |

## Troubleshooting

**"No Logitech HID++ device found"**
- Is the mouse powered on?
- Run `python logiflick.py --debug` to see what HID devices are visible.
- Linux: check `ls -la /dev/hidraw*` -- you need read/write access.
- Windows: try running as Administrator.
- macOS: try the Bolt USB receiver instead of Bluetooth.

**"DPI feature not found"**
- Your mouse may be HID++ 1.0 only, or may not support on-the-fly DPI changes.
- Try power-cycling the mouse and running again.

**"HID++ error: err=0x5"**
- Error `0x5` = Not Allowed. The mouse may have onboard profiles locked in read-only mode.
- Use Logitech Onboard Memory Manager once to initialize a writable profile, then logiflick can modify it.

**DPI reverts after power cycle (even without `-t`)**
- The onboard profile write may have failed silently.
- Some mice have ROM-only profiles that cannot be overwritten.
- Use `-t` and re-run on startup, or add the command to a login/startup script.

## Project Structure

```
logiflick/
├── logiflick.py          # Main script and library (CLI + public API)
├── backends/
│   ├── _linux_hid.py     # Native Linux backend (hidraw, zero deps)
│   └── _win_hid.py       # Native Windows backend (ctypes, zero deps)
└── README.md
```

## Status

logiflick is stable for its stated scope. Planned improvements:

- [ ] macOS native backend (eliminate the `hidapi` requirement)
- [ ] Per-axis DPI (X/Y independent) via `0x2202`
- [ ] Multiple-profile support
- [ ] Auto-selection when multiple Logitech mice are connected

## Contributing

Contributions are welcome. Keep pull requests scoped -- logiflick is intentionally minimal.

1. Fork the repo and create a feature branch.
2. Make your changes. Keep the zero-dependency constraint for the core file.
3. Test on the platform(s) your change affects.
4. Open a pull request with a clear description of what changed and why.

Bug reports via GitHub Issues are appreciated. Include the output of `python logiflick.py --debug`.

## Support

- **Bugs and feature requests:** Open a [GitHub Issue](<repo-url>/issues).
- **Debug output:** Always include `python logiflick.py --debug` output in bug reports.

## License

MIT -- do whatever you want with it.

## Credits

Protocol knowledge derived from the [Solaar](https://github.com/pwr-Solaar/Solaar) project's reverse engineering of Logitech's HID++ protocol.
