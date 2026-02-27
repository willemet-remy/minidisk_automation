# config.py — Infiltrometer system configuration

# ── I2C ──────────────────────────────────────────────────────────────────────
I2C_BUS = 1                        # /dev/i2c-1 on all modern RPi

# MCP23017 I2C address (A0=A1=A2=GND → 0x20)
MCP23017_ADDR = 0x20

# VL53L4CD base address (factory default)
VL53L4CD_DEFAULT_ADDR = 0x29

# Assigned addresses for each sensor (0x2A – 0x31 avoids PiJuice at 0x14)
SENSOR_ADDRESSES = [0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31]

MAX_SENSORS = 8          # hard hardware limit (8 XSHUT lines on MCP23017)
NUM_SENSORS = 8          # Default to 6 sensors for field conditions

# ── MCP23017 registers ────────────────────────────────────────────────────────
# BANK=0 (default): registers interleaved
MCP_IODIRA   = 0x00   # Direction register port A (GPIO1 inputs)
MCP_IODIRB   = 0x01   # Direction register port B (XSHUT outputs)
MCP_GPPUA    = 0x0C   # Pull-up port A
MCP_GPPUB    = 0x0D   # Pull-up port B
MCP_GPIOA    = 0x12   # Read/write port A (GPIO1 interrupt lines)
MCP_GPIOB    = 0x13   # Read/write port B
MCP_OLATA    = 0x14   # Output latch port A
MCP_OLATB    = 0x15   # Output latch port B (XSHUT outputs)

# ── Measurement ───────────────────────────────────────────────────────────────
# Available intervals in seconds (shown in GUI dropdown)
MEASUREMENT_INTERVALS = [1, 2, 5, 10, 30, 60]
DEFAULT_INTERVAL = 5   # seconds

# Distance threshold (mm) below which a sensor raises a "low water" warning
LOW_WATER_THRESHOLD_MM = 400

# ── Data logging ──────────────────────────────────────────────────────────────
USB_MOUNT_PATH = "/media/remy"       # RPi OS auto-mounts USB sticks here
FALLBACK_DATA_DIR = "/home/remy/infiltrometer_data"
CSV_DELIMITER = ","
CSV_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── GUI ───────────────────────────────────────────────────────────────────────
WINDOW_TITLE = "Infiltrometer Controller"
SCREEN_WIDTH  = 800
SCREEN_HEIGHT = 480
FONT_FAMILY = "DejaVu Sans"

# Colour scheme
COLOR_BG        = "#1E2A3A"
COLOR_PANEL     = "#263545"
COLOR_ACCENT    = "#2ECC71"
COLOR_WARNING   = "#F39C12"
COLOR_ERROR     = "#E74C3C"
COLOR_TEXT      = "#ECF0F1"
COLOR_TEXT_DIM  = "#95A5A6"
COLOR_OK        = "#27AE60"

# How many historic readings to show in the live graph
GRAPH_HISTORY = 120   # points
