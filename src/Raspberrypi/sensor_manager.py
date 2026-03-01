# sensor_manager.py — MCP23017 + VL53L4CD management
#
# Responsibilities:
#   1. Control XSHUT lines via MCP23017 port B to assign unique I2C addresses
#   2. Read GPIO1 (interrupt/fault) lines via MCP23017 port A
#   3. Expose a simple read_all() method returning distance in mm per sensor
#
# VL53L4CD I2C protocol note:
#   Default I2C address = 0x52 (8-bit) = 0x29 (7-bit, as used by Linux smbus2).
#   When WRITING a new address to register 0x0001, the sensor expects the
#   8-bit form: (new_7bit_addr << 1).  The address is VOLATILE — it resets to
#   0x29 on every power cycle or XSHUT low (no EEPROM on VL53L4CD).
#
# VL53L4CD range status codes (from ULD / UM2931):
#   0  = Valid measurement
#   1  = Sigma failure (noise too high)
#   2  = Signal failure (too little return signal)
#   4  = Out-of-bounds: target too far (wrap-around)
#   5  = Hardware failure
#   6  = Phase consistency failure
#   7  = Minimum detectable range error (target too close)
#   9  = No target detected
#   12 = Crosstalk error
#   255 = Not initialised / no data

import errno
import time
import logging
from smbus2 import SMBus, i2c_msg
from config import (
    I2C_BUS, MCP23017_ADDR, VL53L4CD_DEFAULT_ADDR, SENSOR_ADDRESSES,
    MAX_SENSORS, MCP_IODIRA, MCP_IODIRB, MCP_GPPUA, MCP_GPPUB,
    MCP_GPIOA, MCP_GPIOB, MCP_OLATA, MCP_OLATB, LOW_WATER_THRESHOLD_MM
)

log = logging.getLogger(__name__)

# ── Range status code → human-readable description ────────────────────────────
RANGE_STATUS_DESCRIPTION = {
    0:   "Valid",
    1:   "Sigma failure (noise too high)",
    2:   "Signal failure (weak return signal)",
    4:   "Out-of-bounds / wrap-around (target too far)",
    5:   "Hardware failure",
    6:   "Phase consistency failure",
    7:   "Min range failure (target too close)",
    9:   "No target detected",
    12:  "Crosstalk error",
    255: "Not initialised / no data",
}


def describe_range_status(code: int) -> str:
    return RANGE_STATUS_DESCRIPTION.get(code, f"Unknown status code {code}")


# ── Try to import ST driver, fall back to register-level implementation ───────
try:
    import vl53l4cd as _vl53_module
    USE_ST_DRIVER = True
    log.info("ST VL53L4CD driver found — using official ULD wrapper")
except ImportError:
    USE_ST_DRIVER = False
    log.warning("ST vl53l4cd package not found — using pure-Python register fallback")


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight pure-Python VL53L4CD driver (fallback)
# Based on ST ULD register map (UM2931)
# ─────────────────────────────────────────────────────────────────────────────
class VL53L4CD_Raw:
    """Minimal VL53L4CD driver using direct I2C register access via smbus2.

    Addressing note
    ---------------
    smbus2 uses 7-bit addresses (e.g. 0x29).
    The VL53L4CD I2C_SLAVE_DEVICE_ADDRESS register (0x0001) expects the
    8-bit I2C address, i.e. (7bit_addr << 1).  change_address() handles this.
    """

    # Key registers (16-bit indices)
    _REG_I2C_SLAVE_ADDR       = 0x0001   # write (7bit_addr<<1) here
    _REG_SYSTEM_START         = 0x0087
    _REG_RESULT_INTERRUPT     = 0x00E5   # bit0: data ready flag
    _REG_RESULT_CLEAR         = 0x0086   # write 0x01 to clear interrupt
    _REG_RESULT_BLOCK_START   = 0x0089   # 17-byte result block
    _RESULT_DISTANCE_OFFSET   = 13       # bytes 13-14 in result block = distance

    def __init__(self, bus: SMBus, address: int):
        self.bus  = bus
        self.addr = address              # 7-bit address for smbus2

    # ── Low-level register helpers ────────────────────────────────────────────

    def _write_byte(self, reg16: int, value: int):
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo =  reg16       & 0xFF
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo, value])

    def _write_word(self, reg16: int, value: int):
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo =  reg16       & 0xFF
        hi = (value >> 8) & 0xFF
        lo =  value       & 0xFF
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo, hi, lo])

    def _write_dword(self, reg16: int, value: int):
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo =  reg16       & 0xFF
        b = [(value >> (8 * (3 - i))) & 0xFF for i in range(4)]
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo] + b)

    def _read_bytes(self, reg16: int, length: int) -> list:
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo =  reg16       & 0xFF
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo])
        return self.bus.read_i2c_block_data(self.addr, 0x00, length)

    # ── Address management ────────────────────────────────────────────────────

    def change_address(self, new_addr_7bit: int):
        """Change the I2C address until next power cycle or XSHUT low.

        Per ST ULD source (VL53L4CD_SetI2CAddress), register 0x0001 stores the
        7-bit address directly.  The ST C API receives the 8-bit form and shifts
        right before writing; we receive the 7-bit smbus form and write it as-is.
        After writing, update self.addr so subsequent calls use the new address.
        """
        log.debug(
            f"    change_address: writing 7-bit 0x{new_addr_7bit:02X} to register "
            f"0x{self._REG_I2C_SLAVE_ADDR:04X}  (smbus addr will be 0x{new_addr_7bit:02X})"
        )
        self._write_byte(self._REG_I2C_SLAVE_ADDR, new_addr_7bit)
        self.addr = new_addr_7bit      # update for all future calls

    # ── Initialisation ────────────────────────────────────────────────────────

    def init(self):
        """Send initialisation sequence as per ST ULD reference."""
        # Note: We do NOT send a software reset here (0x0000 = 0x00) 
        # because the sensor was already hardware-reset via XSHUT.
        # A software reset would revert its I2C address back to 0x29!
        
        log.debug("    [init] Writing default configuration blob …")
        defaults = [
            (0x002D, 0x12), (0x002E, 0x01), (0x002F, 0x12),
            (0x0031, 0x00), (0x0032, 0xFF), (0x0033, 0x00),
            (0x0034, 0x09), (0x0035, 0x08), (0x0036, 0x10),
            (0x0037, 0x01), (0x0038, 0x01), (0x0039, 0x00),
            (0x003A, 0x00), (0x003B, 0x00), (0x003C, 0x00),
            (0x003D, 0x00), (0x003E, 0xFF), (0x003F, 0x11),
        ]
        for reg, val in defaults:
            self._write_byte(reg, val)
        time.sleep(0.010)

        log.debug("    [init] Setting timing budget 50 ms …")
        self.set_timing_budget(50)
        log.debug("    [init] Init complete")

    def set_timing_budget(self, budget_ms: int):
        """Set measurement timing budget in milliseconds (10–200 ms)."""
        budget_ms = max(10, min(200, budget_ms))
        self._write_word(0x0021, budget_ms)

    def start_ranging(self):
        log.debug("    [ranging] start_ranging")
        self._write_byte(self._REG_SYSTEM_START, 0x40)

    def stop_ranging(self):
        log.debug("    [ranging] stop_ranging")
        self._write_byte(self._REG_SYSTEM_START, 0x00)

    def data_ready(self) -> bool:
        status = self._read_bytes(self._REG_RESULT_INTERRUPT, 1)
        return bool(status[0] & 0x01)

    def get_distance(self) -> tuple[int, int]:
        """Returns (distance_mm, range_status).  range_status 0 = valid."""
        # Poll up to 500 ms for data (was 200 ms — safer for 50 ms budget)
        for _ in range(500):
            if self.data_ready():
                break
            time.sleep(0.001)

        result   = self._read_bytes(self._REG_RESULT_BLOCK_START, 17)
        status   = result[0]
        distance = (result[self._RESULT_DISTANCE_OFFSET] << 8) | result[self._RESULT_DISTANCE_OFFSET + 1]

        # Clear interrupt so next measurement can proceed
        self._write_byte(self._REG_RESULT_CLEAR, 0x01)

        return distance, status


# ─────────────────────────────────────────────────────────────────────────────
# ST driver wrapper (when vl53l4cd package IS installed)
# ─────────────────────────────────────────────────────────────────────────────
class VL53L4CD_ST:
    """Thin wrapper around the official ST Python driver."""

    def __init__(self, bus: SMBus, address: int):
        self.address = address
        self._dev = _vl53_module.VL53L4CD(bus, address)

    def init(self):
        self._dev.open()
        self._dev.start_ranging()

    def stop_ranging(self):
        self._dev.stop_ranging()

    def change_address(self, new_addr_7bit: int):
        """ST driver change_address — uses the driver's own method."""
        self._dev.change_address(new_addr_7bit)
        self.address = new_addr_7bit

    def get_distance(self) -> tuple[int, int]:
        """Returns (distance_mm, status). Status 0 = valid."""
        result = self._dev.get_result()
        return result.distance_mm, result.range_status


# ─────────────────────────────────────────────────────────────────────────────
# SensorManager
# ─────────────────────────────────────────────────────────────────────────────
class SensorManager:
    """
    Manages up to MAX_SENSORS VL53L4CD sensors via MCP23017 XSHUT control.

    Address assignment strategy (required because VL53L4CD address is volatile):
      - All sensors start powered off (XSHUT low = hardware standby).
      - Enable sensors one at a time; each comes up at the default 0x29.
      - Immediately re-address it to a unique slot (0x2A … 0x31).
      - Leave it running at the new address; enable the next sensor.

    Usage:
        mgr = SensorManager(num_sensors=3)
        ok  = mgr.initialise()          # list[bool] per sensor
        data = mgr.read_all()           # {idx: {...}} for active sensors
        mgr.shutdown()
    """

    # Boot timing constants (based on datasheet: tBOOT ≤ 1.2 ms)
    _XSHUT_BOOT_WAIT_S     = 0.050   # 50 ms after XSHUT high — generous margin
    _ADDR_CHANGE_WAIT_S    = 0.030   # 30 ms after address register write
    _POST_INIT_WAIT_S      = 0.010   # 10 ms after init sequence
    _XSHUT_DISABLE_WAIT_S  = 0.050   # 50 ms after XSHUT low — let bus settle

    def __init__(self, num_sensors: int = MAX_SENSORS):
        self._num_sensors = max(1, min(num_sensors, MAX_SENSORS))
        self.bus = SMBus(I2C_BUS)
        self.sensors: list = [None] * self._num_sensors
        self._xshut_state: int = 0x00
        self._mcp_available: bool = False   # set True in initialise() if MCP found

    # ── MCP23017 helpers ──────────────────────────────────────────────────────

    def _mcp_write(self, reg: int, value: int):
        self.bus.write_byte_data(MCP23017_ADDR, reg, value)

    def _mcp_read(self, reg: int) -> int:
        return self.bus.read_byte_data(MCP23017_ADDR, reg)

    def _setup_mcp(self):
        """Configure MCP23017, but only if it was found during the I2C scan."""
        if not self._mcp_available:
            log.warning("  [MCP] MCP23017 not available — skipping XSHUT setup.")
            log.warning("  [MCP] Sensors must have XSHUT tied high (pull-up). Only 1 sensor supported in this mode.")
            return
        log.debug("  [MCP] Setting IODIRA=0xFF (all port A = input) …")
        self._mcp_write(MCP_IODIRA, 0xFF)   # port A = inputs (GPIO1 lines)
        log.debug("  [MCP] Setting IODIRB=0x00 (all port B = output) …")
        self._mcp_write(MCP_IODIRB, 0x00)   # port B = outputs (XSHUT lines)
        log.debug("  [MCP] Enabling pull-ups on port A (GPIO1 open-drain) …")
        self._mcp_write(MCP_GPPUA,  0xFF)   # pull-ups on GPIO1 inputs
        log.debug("  [MCP] Disabling pull-ups on port B (XSHUT driven) …")
        self._mcp_write(MCP_GPPUB,  0x00)   # no pull-ups on XSHUT
        self._set_xshut(0x00)               # all XSHUT lines low = all sensors off
        log.info("  [MCP] MCP23017 configured (port B=XSHUT outputs, port A=GPIO1 inputs)")

    def _set_xshut(self, mask: int):
        """Set MCP port A output latch. Bit n = XSHUT for sensor n."""
        if not self._mcp_available:
            return
        self._xshut_state = mask & 0xFF
        self._mcp_write(MCP_OLATB, self._xshut_state)
        log.debug(f"  [MCP] XSHUT latch → 0b{self._xshut_state:08b}")

    def _enable_sensor(self, idx: int):
        """Pull XSHUT high for sensor idx (sensor leaves HW standby)."""
        if not self._mcp_available:
            log.debug(f"  [MCP] XSHUT enable skipped for sensor {idx} (no MCP)")
            return
        self._set_xshut(self._xshut_state | (1 << idx))

    def _disable_sensor(self, idx: int):
        """Pull XSHUT low for sensor idx (sensor enters HW standby, address resets)."""
        if not self._mcp_available:
            log.debug(f"  [MCP] XSHUT disable skipped for sensor {idx} (no MCP)")
            return
        self._set_xshut(self._xshut_state & ~(1 << idx))

    # ── GPIO1 / fault reading ─────────────────────────────────────────────────

    def read_gpio_faults(self) -> list[bool]:
        """
        Read GPIO1 lines from MCP port B.
        Returns list[bool] per sensor: True = GPIO1 asserted low (interrupt/fault).
        GPIO1 is open-drain active low; MCP pull-ups keep it high when idle.
        Returns all-False when MCP is not available.
        """
        if not self._mcp_available:
            return [False] * self._num_sensors
        raw = self._mcp_read(MCP_GPIOA)
        faults = [not bool(raw & (1 << i)) for i in range(self._num_sensors)]
        # removed spammy log.debug here
        return faults

    # ── I2C scan ──────────────────────────────────────────────────────────────

    def scan_i2c(self) -> list[int]:
        """Scan I2C bus 0x03–0x77 and return list of responding addresses."""
        found = []
        log.info(f"[SCAN] Scanning I2C bus {I2C_BUS} (0x03–0x77) …")
        for addr in range(0x03, 0x78):
            try:
                self.bus.read_byte(addr)
                found.append(addr)
                log.info(f"[SCAN]   0x{addr:02X} ✓")
            except OSError:
                pass
        if not found:
            log.warning("[SCAN] No I2C devices found — check wiring and power!")
        else:
            log.info(
                f"[SCAN] Found {len(found)} device(s): "
                + ", ".join(f"0x{a:02X}" for a in found)
            )
        return found

    def _check_i2c_present(self, addr: int, retries: int = 3, retry_delay_s: float = 0.020) -> bool:
        """Return True if a device ACKs at addr. Retries to tolerate brief bus glitches."""
        for attempt in range(1, retries + 1):
            try:
                self.bus.read_byte(addr)
                log.debug(f"  [I2C CHECK] 0x{addr:02X} → ACK ✓ (attempt {attempt})")
                return True
            except OSError as e:
                err_desc = errno.errorcode.get(e.errno, "?") if e.errno else "?"
                log.debug(
                    f"  [I2C CHECK] 0x{addr:02X} → no ACK attempt {attempt}/{retries} "
                    f"(errno={e.errno} {err_desc})"
                )
                if attempt < retries:
                    time.sleep(retry_delay_s)
        log.warning(f"  [I2C CHECK] 0x{addr:02X} → not found after {retries} attempts")
        return False

    # ── Initialisation ────────────────────────────────────────────────────────

    def initialise(self, num_sensors: int | None = None,
                   progress_cb=None) -> list[bool]:
        """
        Full initialisation sequence. Returns list[bool] — True for each sensor
        that came online successfully.

        Args:
            num_sensors:  override the instance's active sensor count.
            progress_cb:  optional callable(msg: str) for live GUI feedback.
        """
        def _cb(msg: str):
            log.info(msg)
            if progress_cb:
                progress_cb(msg)

        if num_sensors is not None:
            self._num_sensors = max(1, min(num_sensors, MAX_SENSORS))
            self.sensors = [None] * self._num_sensors

        _cb(f"=== Starting initialisation for {self._num_sensors} sensor(s) ===")
        _cb(f"  Driver mode: {'ST official ULD' if USE_ST_DRIVER else 'pure-Python register fallback'}")

        # I2C scan to see what is already on the bus
        found = self.scan_i2c()
        self._mcp_available = MCP23017_ADDR in found
        _cb(f"  MCP23017 at 0x{MCP23017_ADDR:02X}: {'FOUND ✓' if self._mcp_available else 'NOT FOUND ✗'}")
        if not self._mcp_available:
            _cb("  WARNING: MCP23017 missing — XSHUT control unavailable.")
            _cb("  Falling back to direct mode: sensor must be powered with XSHUT tied high.")
            if self._num_sensors > 1:
                _cb("  WARNING: Only 1 sensor can be addressed without MCP23017. Reduced to 1.")
                self._num_sensors = 1
                self.sensors = [None]

        self._setup_mcp()
        if self._mcp_available:
            _cb("  MCP23017 configured — all XSHUT lines LOW (sensors in HW standby)")
        time.sleep(0.050)  # let bus settle after reconfiguring MCP

        success = []
        for idx in range(self._num_sensors):
            _cb(f"--- Sensor {idx + 1}/{self._num_sensors} ---")
            ok = self._init_single_sensor(idx, _cb)
            success.append(ok)
            status_str = "✓ OK" if ok else "✗ FAILED"
            _cb(f"  Sensor {idx + 1} → {status_str}")

        online = sum(success)
        _cb(f"=== Init complete: {online}/{self._num_sensors} sensor(s) online ===")
        return success

    def _init_single_sensor(self, idx: int, _cb=None) -> bool:
        """
        Enable sensor idx, assign unique I2C address, run init + start ranging.
        All sensors already initialised remain at their new addresses undisturbed.

        Address note: VL53L4CD address is VOLATILE.  It resets to 0x29 every time
        XSHUT goes low or power is removed.  Do not lower XSHUT after assignment.
        """
        target_addr = SENSOR_ADDRESSES[idx]

        def cb(msg):
            log.debug(msg)
            if _cb:
                _cb(msg)

        try:
            if self._mcp_available:
                cb(f"  [S{idx}] XSHUT high → sensor leaves HW standby")
                self._enable_sensor(idx)
                cb(f"  [S{idx}] Waiting {int(self._XSHUT_BOOT_WAIT_S*1000)} ms for firmware boot "
                   f"(datasheet tBOOT ≤ 1.2 ms) …")
                time.sleep(self._XSHUT_BOOT_WAIT_S)
            else:
                cb(f"  [S{idx}] No MCP — assuming sensor already powered (XSHUT tied high)")

            # Verify sensor is present at the default address before proceeding
            cb(f"  [S{idx}] Checking sensor ACK at default addr 0x{VL53L4CD_DEFAULT_ADDR:02X} …")
            if not self._check_i2c_present(VL53L4CD_DEFAULT_ADDR):
                cb(f"  [S{idx}] ✗ Sensor not found at 0x{VL53L4CD_DEFAULT_ADDR:02X}. "
                   f"Check wiring / power / XSHUT pull-up.")
                self._disable_sensor(idx)
                return False

            cb(f"  [S{idx}] Sensor found at default addr 0x{VL53L4CD_DEFAULT_ADDR:02X} ✓")

            # Instantiate driver at default address
            if USE_ST_DRIVER:
                cb(f"  [S{idx}] Creating ST driver instance at 0x{VL53L4CD_DEFAULT_ADDR:02X}")
                sensor = VL53L4CD_ST(self.bus, VL53L4CD_DEFAULT_ADDR)
            else:
                cb(f"  [S{idx}] Creating register-fallback driver at 0x{VL53L4CD_DEFAULT_ADDR:02X}")
                sensor = VL53L4CD_Raw(self.bus, VL53L4CD_DEFAULT_ADDR)


            # Re-address to unique slot — only when MCP is available (we can control XSHUT)
            if self._mcp_available:
                cb(
                    f"  [S{idx}] Remapping 0x{VL53L4CD_DEFAULT_ADDR:02X} → 0x{target_addr:02X} "
                    f"(writing 7-bit addr 0x{target_addr:02X} to register 0x0001) …"
                )
                if USE_ST_DRIVER:
                    sensor._dev.change_address(target_addr)
                    sensor.address = target_addr
                    sensor._dev = _vl53_module.VL53L4CD(self.bus, target_addr)
                else:
                    sensor.change_address(target_addr)   # writes 7-bit addr to reg 0x0001

                cb(f"  [S{idx}] Waiting {int(self._ADDR_CHANGE_WAIT_S*1000)} ms for address change to register …")
                time.sleep(self._ADDR_CHANGE_WAIT_S)

                # Verify sensor responds at new address
                cb(f"  [S{idx}] Verifying ACK at new addr 0x{target_addr:02X} …")
                if not self._check_i2c_present(target_addr, retries=5, retry_delay_s=0.020):
                    cb(f"  [S{idx}] ✗ Sensor NOT found at 0x{target_addr:02X} after address change! "
                       f"Address write may have failed.")
                    self._disable_sensor(idx)
                    time.sleep(self._XSHUT_DISABLE_WAIT_S)
                    return False
                cb(f"  [S{idx}] Sensor confirmed at 0x{target_addr:02X} ✓")
            else:
                cb(f"  [S{idx}] No MCP — skipping address change, using default 0x{VL53L4CD_DEFAULT_ADDR:02X}")
                # Sensor stays at 0x29; point target_addr at it so init/logging is consistent
                target_addr = VL53L4CD_DEFAULT_ADDR

            # Run init sequence and start ranging
            cb(f"  [S{idx}] Running init sequence at 0x{target_addr:02X} …")
            sensor.init()
            time.sleep(self._POST_INIT_WAIT_S)

            cb(f"  [S{idx}] Starting ranging …")
            if not USE_ST_DRIVER:
                sensor.start_ranging()

            self.sensors[idx] = sensor
            log.info(f"  [S{idx}] Sensor {idx + 1} ONLINE at 0x{target_addr:02X} ✓")
            return True

        except OSError as e:
            err_name = errno.errorcode.get(e.errno, "?") if e.errno else "?"
            log.error(
                f"  [S{idx}] OSError during init: errno={e.errno} ({err_name}): {e}"
            )
            self._disable_sensor(idx)
            time.sleep(self._XSHUT_DISABLE_WAIT_S)
            self.sensors[idx] = None
            return False
        except Exception as e:
            log.error(f"  [S{idx}] Unexpected error during init: {type(e).__name__}: {e}")
            self._disable_sensor(idx)
            time.sleep(self._XSHUT_DISABLE_WAIT_S)
            self.sensors[idx] = None
            return False

    # ── Reading ───────────────────────────────────────────────────────────────

    def read_all(self) -> dict:
        """
        Read distance from all active sensors.

        Returns dict keyed by sensor index (0 … num_sensors-1):
            {
              'distance_mm' : int or None,
              'status'      : int,   # 0=valid; see RANGE_STATUS_DESCRIPTION
              'status_text' : str,   # human-readable status description
              'low_water'   : bool,
              'fault'       : bool,  # GPIO1 line asserted low
            }
        """
        faults  = self.read_gpio_faults()
        results = {}

        for idx in range(self._num_sensors):
            sensor = self.sensors[idx] if idx < len(self.sensors) else None
            if sensor is None:
                results[idx] = {
                    'distance_mm': None,
                    'status':      -1,
                    'status_text': "Sensor not initialised",
                    'low_water':   False,
                    'fault':       faults[idx],
                }
                continue
            try:
                dist, status = sensor.get_distance()
                valid   = (status == 0)
                low     = valid and (dist < LOW_WATER_THRESHOLD_MM)
                status_text = describe_range_status(status)
                results[idx] = {
                    'distance_mm': dist if valid else None,
                    'status':      status,
                    'status_text': status_text,
                    'low_water':   low,
                    'fault':       faults[idx],
                }
            except OSError as e:
                err_name = errno.errorcode.get(e.errno, "?") if e.errno else "?"
                log.warning(
                    f"[READ] Sensor {idx} OSError: errno={e.errno} ({err_name}): {e}"
                )
                results[idx] = {
                    'distance_mm': None,
                    'status':      -2,
                    'status_text': f"I/O error (errno={e.errno} {err_name})",
                    'low_water':   False,
                    'fault':       faults[idx],
                }
            except Exception as e:
                log.warning(f"[READ] Sensor {idx} error: {type(e).__name__}: {e}")
                results[idx] = {
                    'distance_mm': None,
                    'status':      -3,
                    'status_text': f"Read error: {e}",
                    'low_water':   False,
                    'fault':       faults[idx],
                }

        return results

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self):
        """Stop all sensors and pull all XSHUT lines low."""
        log.info("[SHUTDOWN] Stopping all sensors …")
        for idx, sensor in enumerate(self.sensors):
            if sensor is not None:
                try:
                    sensor.stop_ranging()
                    log.debug(f"  [SHUTDOWN] Sensor {idx} ranging stopped")
                except Exception as e:
                    log.debug(f"  [SHUTDOWN] Sensor {idx} stop_ranging failed: {e}")
        self._set_xshut(0x00)
        log.debug("  [SHUTDOWN] All XSHUT lines LOW (sensors in HW standby)")
        self.bus.close()
        log.info("[SHUTDOWN] SensorManager shut down cleanly")
