# MF4 CAN Signal Analyzer

A Python tool for analyzing MF4 files and decoding CAN signals using DBC files.

## What It Does

1. **Extracts CAN frames** from MF4 files (ignores LIN, FlexRay, etc.)
2. **Matches CAN IDs** to messages defined in the DBC file
3. **Decodes signals** from raw CAN data bytes using DBC definitions
4. **Counts unique values** for each decoded signal
5. **Counts on-change events** - how many times each signal value changed
6. **Exports statistics** to a JSON file

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Basic usage (DBC is required)
python mf4_analyzer.py your_file.mf4 -d your_database.dbc

# Specify output JSON file
python mf4_analyzer.py your_file.mf4 -d your_database.dbc -o my_statistics.json
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `mf4_file` | Path to the MF4 file to analyze (required) |
| `-d, --dbc` | Path to the DBC file for signal decoding (required) |
| `-o, --output` | Path to save statistics JSON (default: signal_statistics.json) |

## On-Change Count

The on-change count tracks how many times a signal's value changed during the recording.

**Example:** If a signal has values `[1, 0, 0, 1, 1, 1, 0]` in sequence:
- `1 → 0` (change 1)
- `0 → 0` (no change)
- `0 → 1` (change 2)
- `1 → 1` (no change)
- `1 → 1` (no change)
- `1 → 0` (change 3)

**On-change count = 3**

## Output JSON Structure

The `signal_statistics.json` file contains:

```json
{
  "mf4_file": "data.mf4",
  "dbc_file": "vehicle.dbc",
  "summary": {
    "total_frames": 1500000,
    "decoded_frames": 1200000,
    "total_messages": 45,
    "total_signals": 180
  },
  "messages": {
    "EngineStatus": 450000,
    "VehicleSpeed": 380000
  },
  "signals": {
    "EngineRPM": {
      "sample_count": 450000,
      "unique_value_count": 3200,
      "on_change_count": 125000,
      "value_distribution": {
        "850": 45000,
        "900": 42000
      }
    },
    "BrakePedalPressed": {
      "sample_count": 370000,
      "unique_value_count": 2,
      "on_change_count": 1500,
      "value_distribution": {
        "0": 320000,
        "1": 50000
      }
    }
  }
}
```

## Console Output

```
================================================================================
MF4 CAN SIGNAL ANALYSIS RESULTS
================================================================================

MF4 File: data.mf4
DBC File: vehicle.dbc

Total CAN Frames: 1,500,000
Decoded Frames: 1,200,000

------------------------------------------------------------
SIGNAL ANALYSIS
------------------------------------------------------------
Total unique signals decoded: 180

Signal Name                              Samples   Unique Vals    On-Change
--------------------------------------------------------------------------------
EngineRPM                                450,000         3,200      125,000
VehicleSpeedKMH                          380,000         1,150       98,000
BrakePedalPressed                        370,000             2        1,500
```

## Dependencies

- `asammdf` - For reading MF4 files
- `cantools` - For parsing DBC files and decoding CAN signals
- `numpy` - For numerical operations
