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
import json
import board
import busio
import struct
import adafruit_vl53l4cd
from smbus2 import SMBus
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


# ─────────────────────────────────────────────────────────────────────────────
# Adafruit VL53L4CD Wrapper
# Wraps the official CircuitPython driver to expose calibration methods identical
# to what the GUI expects.
# ─────────────────────────────────────────────────────────────────────────────

class VL53L4CD_Wrapper:
    """Wrapper around adafruit_vl53l4cd.VL53L4CD that adds simple calibration."""

    def __init__(self, i2c_bus, address: int):
        self._dev = adafruit_vl53l4cd.VL53L4CD(i2c_bus, address=address)
        self.address = address

    def init(self):
        # The __init__ of Adafruit already runs the 300+ byte payload.
        # We just set timing budget.
        self._dev.timing_budget = 50

    def start_ranging(self):
        self._dev.start_ranging()

    def stop_ranging(self):
        self._dev.stop_ranging()

    def get_distance(self):
        # Wait up to 500ms for data
        for _ in range(500):
            if self._dev.data_ready:
                break
            time.sleep(0.001)

        dist_cm = self._dev.distance
        status = self._dev.range_status
        self._dev.clear_interrupt()

        dist_mm = int(dist_cm * 10) if dist_cm is not None else 0
        return dist_mm, status

    def _write_word(self, reg16: int, value: int):
        self._dev._write_register(reg16, struct.pack(">H", value))

    def get_full_result(self) -> tuple[int, float, float, int]:
        """Returns distance_mm, spad_nb, signal_kcps, status for calibration use."""
        for _ in range(500):
            if self._dev.data_ready:
                break
            time.sleep(0.001)

        # Result block starts at 0x0089 in VL53L4CD
        result = self._dev._read_register(0x0089, 17)
        status = result[0]
        spad_nb = ((result[3] << 8) | result[4]) / 256.0
        signal = ((result[5] << 8) | result[6]) * 8.0
        dist_mm = (result[13] << 8) | result[14]

        self._dev.clear_interrupt()
        return dist_mm, max(0.01, spad_nb), signal, status

    def calibrate_offset(self, target_dist_mm: int, nb_samples: int = 50) -> int:
        """Calculates and applies offset. Returns the offset in mm."""
        self._write_word(0x001E, 0x0000) # _VL53L4CD_RANGE_OFFSET_MM
        self._write_word(0x0020, 0x0000)
        self._write_word(0x0022, 0x0000)

        self.start_ranging()
        for _ in range(10):  # Heat loop
            self.get_full_result()
        self.stop_ranging()

        self.start_ranging()
        avg_dist = 0.0
        for _ in range(nb_samples):
            dist, _, _, _ = self.get_full_result()
            avg_dist += dist
        self.stop_ranging()

        avg_dist /= nb_samples
        offset_mm = target_dist_mm - avg_dist
        offset_reg_val = int(offset_mm * 4) & 0xFFFF

        self._write_word(0x001E, offset_reg_val)
        return int(offset_mm)

    def calibrate_xtalk(self, target_dist_mm: int, nb_samples: int = 50) -> int:
        """Calculates and applies crosstalk. Returns measured xtalk in kcps."""
        self.start_ranging()
        for _ in range(10):  # Heat loop
            self.get_full_result()
        self.stop_ranging()

        self.start_ranging()
        avg_dist = 0.0
        avg_spad = 0.0
        avg_signal = 0.0
        for _ in range(nb_samples):
            dist, spad, signal, _ = self.get_full_result()
            avg_dist += dist
            avg_spad += spad
            avg_signal += signal
        self.stop_ranging()

        avg_dist /= nb_samples
        avg_spad /= nb_samples
        avg_signal /= nb_samples

        tmp_xtalk = 512.0 * (avg_signal * (1.0 - (avg_dist / target_dist_mm))) / avg_spad
        cal_xtalk = int(tmp_xtalk) & 0xFFFF

        self._write_word(0x0016, cal_xtalk) # _VL53L4CD_XTALK_PLANE_OFFSET_KCPS
        return (cal_xtalk * 1000) >> 9


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
        self.i2c_bus = busio.I2C(board.SCL, board.SDA)
        self.sensors: list = [None] * self._num_sensors
        self._xshut_state: int = 0x00
        self._mcp_available: bool = False   # set True in initialise() if MCP found
        
        self._calibration_file = "/home/pi/infiltrometer/calibration.json"
        self._calibrations = self._load_calibrations()

    def _load_calibrations(self) -> dict:
        import json, os
        if os.path.exists(self._calibration_file):
            try:
                with open(self._calibration_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Failed to load calibrations: {e}")
        return {}

    def _save_calibrations(self):
        import json
        try:
            with open(self._calibration_file, "w") as f:
                json.dump(self._calibrations, f, indent=4)
        except Exception as e:
            log.error(f"Failed to save calibrations: {e}")

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
        """Set MCP port B output latch. Bit n = XSHUT for sensor n."""
        if not self._mcp_available:
            return
        self._xshut_state = mask & 0xFF
        try:
            self._mcp_write(MCP_OLATB, self._xshut_state)
            log.debug(f"  [MCP] XSHUT latch → 0b{self._xshut_state:08b}")
        except OSError as e:
            log.error(f"  [MCP] Failed to set XSHUT latch (I2C error): {e}")

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
        Read GPIO1 lines from MCP port A.
        Returns list[bool] per sensor: True = GPIO1 asserted low (interrupt/fault).
        GPIO1 is open-drain active low; MCP pull-ups keep it high when idle.
        Returns all-False when MCP is not available.
        """
        if not self._mcp_available:
            return [False] * self._num_sensors
        try:
            raw = self._mcp_read(MCP_GPIOA)
            faults = [not bool(raw & (1 << i)) for i in range(self._num_sensors)]
            return faults
        except OSError as e:
            # Don't spam errors on every loop if the bus is dead, but don't crash either
            return [False] * self._num_sensors

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
            cb(f"  [S{idx}] Creating Adafruit driver instance at 0x{VL53L4CD_DEFAULT_ADDR:02X}")
            try:
                sensor = VL53L4CD_Wrapper(self.i2c_bus, VL53L4CD_DEFAULT_ADDR)
            except Exception as e:
                cb(f"  [S{idx}] ✗ Failed to initialize driver: {e}")
                sensor = None

            if not sensor:
                self._disable_sensor(idx)
                return False

            # Re-address to unique slot — only when MCP is available (we can control XSHUT)
            if self._mcp_available:
                cb(
                    f"  [S{idx}] Remapping 0x{VL53L4CD_DEFAULT_ADDR:02X} → 0x{target_addr:02X} ..."
                )
                sensor._dev.set_address(target_addr)
                sensor.address = target_addr

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

            # Run init sequence (timing budget)
            cb(f"  [S{idx}] Running init sequence at 0x{target_addr:02X} …")
            sensor.init()

            # Apply calibration if available
            calib = self._calibrations.get(str(idx))
            if calib:
                cb(f"  [S{idx}] Applying saved calibration (Offset={calib['result_offset_mm']}mm, Xtalk={calib['result_xtalk_kcps']/1000.0:.1f}kcps)")
                sensor._write_word(0x001E, calib["offset_reg"])
                sensor._write_word(0x0016, calib["xtalk_reg"])

            time.sleep(self._POST_INIT_WAIT_S)

            cb(f"  [S{idx}] Starting ranging …")
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

    def run_calibration(self, sensor_idx: int, target_dist_mm: int, nb_samples: int = 50) -> dict:
        """Runs calibration for a single sensor and saves to file."""
        if sensor_idx < 0 or sensor_idx >= len(self.sensors) or self.sensors[sensor_idx] is None:
            raise ValueError(f"Sensor {sensor_idx + 1} is not active")
        if USE_ST_DRIVER:
            raise RuntimeError("Calibration protocol not available in ST driver wrapper.")
            
        sensor = self.sensors[sensor_idx]
        
        log.info(f"  [S{sensor_idx}] Running OFFSET calibration ({nb_samples} samples) at {target_dist_mm} mm...")
        offset_mm = sensor.calibrate_offset(target_dist_mm, nb_samples)
        
        log.info(f"  [S{sensor_idx}] Running XTALK calibration ({nb_samples} samples) at {target_dist_mm} mm...")
        xtalk_kcps = sensor.calibrate_xtalk(target_dist_mm, nb_samples)
        
        # Read exact register values to save
        offset_reg = sensor._read_bytes(0x001E, 2)
        offset_val = (offset_reg[0] << 8) | offset_reg[1]
        
        xtalk_reg = sensor._read_bytes(0x0016, 2)
        xtalk_val = (xtalk_reg[0] << 8) | xtalk_reg[1]
        
        # Save to dict
        self._calibrations[str(sensor_idx)] = {
            "offset_reg": offset_val,
            "xtalk_reg": xtalk_val,
            "target_mm": target_dist_mm,
            "result_offset_mm": offset_mm,
            "result_xtalk_kcps": xtalk_kcps
        }
        self._save_calibrations()
        log.info(f"  [S{sensor_idx}] Calibration saved! Offset: {offset_mm}mm, Xtalk: {xtalk_kcps/1000.0:.1f}kcps")
        
        # Restart ranging after calibration
        sensor.start_ranging()
        return self._calibrations[str(sensor_idx)]

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
