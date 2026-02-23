# sensor_manager.py — MCP23017 + VL53L4CD management
#
# Responsibilities:
#   1. Control XSHUT lines via MCP23017 port A to assign unique I2C addresses
#   2. Read GPIO1 (interrupt/fault) lines via MCP23017 port B
#   3. Expose a simple read_all() method returning distance in mm per sensor
#
# VL53L4CD I2C protocol note:
#   The official Python driver from ST (vl53l4cd pip package) wraps the C
#   ULD driver. If it is not available, a lightweight pure-Python fallback
#   using direct register writes is included below.

import time
import logging
from smbus2 import SMBus, i2c_msg
from config import (
    I2C_BUS, MCP23017_ADDR, VL53L4CD_DEFAULT_ADDR, SENSOR_ADDRESSES,
    MAX_SENSORS, MCP_IODIRA, MCP_IODIRB, MCP_GPPUA, MCP_GPPUB,
    MCP_GPIOA, MCP_GPIOB, MCP_OLATA, LOW_WATER_THRESHOLD_MM
)

log = logging.getLogger(__name__)

# ── Try to import ST driver, fall back to register-level implementation ───────
try:
    import vl53l4cd as _vl53_module
    USE_ST_DRIVER = True
    log.info("ST VL53L4CD driver found")
except ImportError:
    USE_ST_DRIVER = False
    log.warning("ST vl53l4cd package not found – using register fallback")


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight pure-Python VL53L4CD driver (fallback)
# Based on ST ULD register map (UM2931)
# ─────────────────────────────────────────────────────────────────────────────
class VL53L4CD_Raw:
    """Minimal VL53L4CD driver using direct I2C register access via smbus2."""

    # Key registers
    _REG_I2C_SLAVE_ADDR   = 0x0001
    _REG_VHV_CONFIG_INIT  = 0x000B
    _REG_ALGO_PHASECAL    = 0x0014
    _REG_RANGE_CONFIG_A   = 0x0096
    _REG_RANGE_CONFIG_B   = 0x0097
    _REG_INTERMEASUREMENT = 0x006C  # 4 bytes
    _REG_SYSTEM_START     = 0x0087
    _REG_RESULT_STATUS    = 0x0089  # range status
    _REG_RESULT_DISTANCE  = 0x0096  # 2 bytes, mm  (result block offset)
    _REG_RESULT_FINAL_CROSSTALK = 0x008E

    # Result block
    _REG_RESULT_RANGE     = 0x0096

    def __init__(self, bus: SMBus, address: int):
        self.bus = bus
        self.addr = address

    def _write_byte(self, reg16: int, value: int):
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo = reg16 & 0xFF
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo, value])

    def _write_word(self, reg16: int, value: int):
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo = reg16 & 0xFF
        hi = (value >> 8) & 0xFF
        lo = value & 0xFF
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo, hi, lo])

    def _write_dword(self, reg16: int, value: int):
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo = reg16 & 0xFF
        b = [(value >> (8 * (3 - i))) & 0xFF for i in range(4)]
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo] + b)

    def _read_bytes(self, reg16: int, length: int) -> list:
        reg_hi = (reg16 >> 8) & 0xFF
        reg_lo = reg16 & 0xFF
        self.bus.write_i2c_block_data(self.addr, reg_hi, [reg_lo])
        return self.bus.read_i2c_block_data(self.addr, 0x00, length)

    def change_address(self, new_addr: int):
        """Permanently change the I2C address until next power cycle."""
        self._write_byte(self._REG_I2C_SLAVE_ADDR, new_addr)
        self.addr = new_addr

    def init(self):
        """Send initialisation sequence as per ST ULD reference."""
        # Software reset
        self._write_byte(0x0000, 0x00)
        time.sleep(0.01)
        # Write default configuration blob (abbreviated — covers VHV + timing)
        # Full config from ST Application Note AN5714
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
        time.sleep(0.01)
        # Set timing budget 50 ms
        self.set_timing_budget(50)

    def set_timing_budget(self, budget_ms: int):
        """Set measurement timing budget in milliseconds (10–200 ms)."""
        budget_ms = max(10, min(200, budget_ms))
        self._write_word(0x0021, budget_ms)

    def start_ranging(self):
        self._write_byte(self._REG_SYSTEM_START, 0x40)

    def stop_ranging(self):
        self._write_byte(self._REG_SYSTEM_START, 0x00)

    def data_ready(self) -> bool:
        status = self._read_bytes(0x00E5, 1)
        return bool(status[0] & 0x01)

    def get_distance(self) -> tuple[int, int]:
        """
        Returns (distance_mm, range_status).
        range_status == 0 means valid.
        """
        # Wait up to 200 ms for data
        for _ in range(200):
            if self.data_ready():
                break
            time.sleep(0.001)
        result = self._read_bytes(0x0089, 17)
        status = result[0]
        distance = (result[13] << 8) | result[14]
        # Clear interrupt
        self._write_byte(0x0086, 0x01)
        return distance, status


# ─────────────────────────────────────────────────────────────────────────────
# ST driver wrapper (when vl53l4cd package IS installed)
# ─────────────────────────────────────────────────────────────────────────────
class VL53L4CD_ST:
    """Thin wrapper around the official ST Python driver."""

    def __init__(self, bus: SMBus, address: int):
        self.address = address
        # ST driver opens its own I2C handle
        self._dev = _vl53_module.VL53L4CD(bus, address)

    def init(self):
        self._dev.open()
        self._dev.start_ranging()

    def stop_ranging(self):
        self._dev.stop_ranging()

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

    Usage:
        mgr = SensorManager(num_sensors=3)
        mgr.initialise()            # assigns addresses, inits sensors
        distances = mgr.read_all()  # {sensor_idx: {...}} for active sensors
        mgr.shutdown()
    """

    def __init__(self, num_sensors: int = MAX_SENSORS):
        self._num_sensors = max(1, min(num_sensors, MAX_SENSORS))
        self.bus = SMBus(I2C_BUS)
        self.sensors: list = [None] * self._num_sensors
        self._xshut_state: int = 0x00   # current MCP port A output latch

    # ── MCP23017 helpers ──────────────────────────────────────────────────────

    def _mcp_write(self, reg: int, value: int):
        self.bus.write_byte_data(MCP23017_ADDR, reg, value)

    def _mcp_read(self, reg: int) -> int:
        return self.bus.read_byte_data(MCP23017_ADDR, reg)

    def _setup_mcp(self):
        """Configure MCP23017: port A = outputs (XSHUT), port B = inputs (GPIO1)."""
        self._mcp_write(MCP_IODIRA, 0x00)   # all port A = output
        self._mcp_write(MCP_IODIRB, 0xFF)   # all port B = input
        self._mcp_write(MCP_GPPUA,  0x00)   # no pull-ups on XSHUT (10k pull-downs externally)
        self._mcp_write(MCP_GPPUB,  0xFF)   # pull-ups on GPIO1 inputs
        self._set_xshut(0x00)               # all sensors OFF at start
        log.info("MCP23017 configured")

    def _set_xshut(self, mask: int):
        """Set MCP port A output to mask (bit n = XSHUT for sensor n)."""
        self._xshut_state = mask & 0xFF
        self._mcp_write(MCP_OLATA, self._xshut_state)

    def _enable_sensor(self, idx: int):
        """Pull XSHUT high for sensor idx."""
        self._set_xshut(self._xshut_state | (1 << idx))

    def _disable_sensor(self, idx: int):
        """Pull XSHUT low (reset) for sensor idx."""
        self._set_xshut(self._xshut_state & ~(1 << idx))

    # ── GPIO1 / fault reading ─────────────────────────────────────────────────

    def read_gpio_faults(self) -> list[bool]:
        """
        Read GPIO1 lines from MCP port B.
        Returns list of bool per sensor: True = fault/interrupt asserted (line LOW).
        GPIO1 on VL53L4CD is open-drain, active low, pulled up on MCP.
        """
        raw = self._mcp_read(MCP_GPIOB)
        return [not bool(raw & (1 << i)) for i in range(self._num_sensors)]

    # ── Initialisation ────────────────────────────────────────────────────────

    def initialise(self, num_sensors: int | None = None) -> list[bool]:
        """
        Full initialisation sequence.
        Returns list[bool] indicating which sensors initialised successfully.

        Args:
            num_sensors: override the instance's active sensor count.
        """
        if num_sensors is not None:
            self._num_sensors = max(1, min(num_sensors, MAX_SENSORS))
            self.sensors = [None] * self._num_sensors

        log.info(f"Starting sensor initialisation ({self._num_sensors} sensors)")
        self._setup_mcp()
        time.sleep(0.05)

        success = []
        for idx in range(self._num_sensors):
            ok = self._init_single_sensor(idx)
            success.append(ok)

        online = sum(success)
        log.info(f"Initialisation complete: {online}/{self._num_sensors} sensors online")
        return success

    def _init_single_sensor(self, idx: int) -> bool:
        """
        Enable sensor idx, assign unique address, init ranging.
        All other sensors remain at their already-assigned addresses.
        """
        target_addr = SENSOR_ADDRESSES[idx]
        log.info(f"Init sensor {idx} → address 0x{target_addr:02X}")

        try:
            # Enable this sensor (others are already at unique addresses)
            self._enable_sensor(idx)
            time.sleep(0.010)  # boot time

            # The sensor will come up at 0x29 (default)
            if USE_ST_DRIVER:
                sensor = VL53L4CD_ST(self.bus, VL53L4CD_DEFAULT_ADDR)
            else:
                sensor = VL53L4CD_Raw(self.bus, VL53L4CD_DEFAULT_ADDR)

            # Change to unique address
            if USE_ST_DRIVER:
                # ST driver exposes address change
                sensor._dev.change_address(target_addr)
                sensor.address = target_addr
                sensor._dev = _vl53_module.VL53L4CD(self.bus, target_addr)
            else:
                sensor.change_address(target_addr)

            time.sleep(0.005)

            # Initialise and start ranging at new address
            sensor.init()
            self.sensors[idx] = sensor
            log.info(f"  Sensor {idx} OK at 0x{target_addr:02X}")
            return True

        except Exception as e:
            log.error(f"  Sensor {idx} FAILED: {e}")
            self._disable_sensor(idx)
            self.sensors[idx] = None
            return False

    # ── Reading ───────────────────────────────────────────────────────────────

    def read_all(self) -> dict:
        """
        Read distance from all active sensors.

        Returns dict keyed by sensor index (0 … num_sensors-1):
            {
              'distance_mm': int or None,
              'status': int,           # 0 = valid, other = error code
              'low_water': bool,
              'fault': bool,           # from GPIO1 pin
            }
        """
        faults = self.read_gpio_faults()
        results = {}

        for idx in range(self._num_sensors):
            sensor = self.sensors[idx] if idx < len(self.sensors) else None
            if sensor is None:
                results[idx] = {
                    'distance_mm': None,
                    'status': -1,
                    'low_water': False,
                    'fault': faults[idx],
                }
                continue
            try:
                dist, status = sensor.get_distance()
                low = (status == 0) and (dist < LOW_WATER_THRESHOLD_MM)
                results[idx] = {
                    'distance_mm': dist if status == 0 else None,
                    'status': status,
                    'low_water': low,
                    'fault': faults[idx],
                }
            except Exception as e:
                log.warning(f"Read error sensor {idx}: {e}")
                results[idx] = {
                    'distance_mm': None,
                    'status': -2,
                    'low_water': False,
                    'fault': faults[idx],
                }

        return results

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self):
        """Stop all sensors and pull XSHUT low."""
        for idx, sensor in enumerate(self.sensors):
            if sensor:
                try:
                    sensor.stop_ranging()
                except Exception:
                    pass
        self._set_xshut(0x00)
        self.bus.close()
        log.info("SensorManager shut down")
