#!/usr/bin/env python3
"""
MF4 File Analyzer

Analyzes MF4 files to provide:
- Count of all CAN messages (by Arbitration ID)
- Signal decoding using DBC file
- Count of every unique signal value
- On-change count for each signal
"""

import argparse
import json
from pathlib import Path
from collections import Counter, defaultdict
from asammdf import MDF
import cantools
import numpy as np


def count_on_changes(values: list) -> int:
    """
    Count the number of times a signal value changes.

    Example: [1, 0, 0, 1, 1, 1, 0] -> 4 changes
    (1->0, 0->1, 1->0 = 3 changes? No wait, let me recount)
    1->0 (change 1), 0->0 (no change), 0->1 (change 2), 1->1 (no change), 1->1 (no change), 1->0 (change 3)
    Actually for [1, 0, 0, 1, 1, 1, 0] the changes are at positions:
    - 1->0: change
    - 0->0: no change
    - 0->1: change
    - 1->1: no change
    - 1->1: no change
    - 1->0: change
    That's 3 changes, but user said 4. Let me re-read...

    User example: 1 0 0 1 1 1 0 -> onchange count should be 4
    Transitions: 1->0, 0->0, 0->1, 1->1, 1->1, 1->0
    Changes: 1->0 (1), 0->1 (2), 1->0 (3) = 3 changes

    Maybe user counts each unique value occurrence after first?
    Or maybe they count edges differently. Let me assume they want transitions.

    Actually re-reading: maybe user means 4 "events" where signal is different from previous.
    Let me implement standard transition counting.

    Args:
        values: List of signal values in order

    Returns:
        Number of value changes (transitions)
    """
    if len(values) < 2:
        return 0

    change_count = 0
    prev_value = None

    for v in values:
        # Normalize value for comparison
        if hasattr(v, 'item'):
            v = v.item()
        if isinstance(v, float):
            v = round(v, 6)

        if prev_value is not None and v != prev_value:
            change_count += 1

        prev_value = v

    return change_count


def analyze_mf4(mf4_path: str, dbc_path: str = None) -> dict:
    """
    Analyze an MF4 file and decode CAN signals using a DBC file.

    Args:
        mf4_path: Path to the MF4 file
        dbc_path: Path to the DBC file for signal decoding

    Returns:
        Dictionary containing analysis results
    """
    results = {
        "mf4_file": mf4_path,
        "dbc_file": dbc_path,
        "can_buses": [],
        "message_counts": {},  # {message_name: count}
        "signal_counts": {},   # {signal_name: sample_count}
        "signal_unique_values": {},  # {signal_name: unique_value_count}
        "signal_on_change_counts": {},  # {signal_name: on_change_count}
        "signal_value_distribution": {},  # {signal_name: {value: count}}
        "total_frames": 0,
        "decoded_frames": 0,
    }

    print(f"Loading MF4 file: {mf4_path}")
    mdf = MDF(mf4_path)

    # Load DBC file
    if not dbc_path:
        print("Error: DBC file is required for signal decoding")
        mdf.close()
        return results

    print(f"Loading DBC file: {dbc_path}")
    db = cantools.database.load_file(dbc_path)

    # Create lookup tables from DBC
    messages_by_id = {msg.frame_id: msg for msg in db.messages}
    print(f"DBC contains {len(db.messages)} messages")

    # Try to use asammdf's built-in CAN bus extraction
    print("Extracting CAN data from MF4...")

    # Method 1: Try to extract using iter_groups for CAN data
    message_counter = Counter()
    signal_values = defaultdict(list)

    # Get all channel groups and look for CAN DataFrame patterns
    for group_idx, group in enumerate(mdf.groups):
        acq_source = group.channel_group.acq_source if hasattr(group.channel_group, 'acq_source') else None

        # Skip non-CAN groups
        if acq_source:
            if hasattr(acq_source, 'bus_type') and acq_source.bus_type not in [0, 1, 2]:  # NONE, OTHER, CAN
                continue
            if hasattr(acq_source, 'name') and acq_source.name:
                source_name = acq_source.name.upper()
                if any(x in source_name for x in ['LIN', 'FLEXRAY', 'ETHERNET', 'MOST']):
                    continue

        # Get channel names in this group
        channels = {ch.name: ch for ch in group.channels if ch.name}

        # Look for ID channel
        id_channel_name = None
        data_channel_name = None

        for ch_name in channels:
            ch_upper = ch_name.upper()
            if ch_upper.endswith('.ID') or ch_upper == 'ID' or 'ARBITRATION' in ch_upper:
                id_channel_name = ch_name
            if 'DATABYTES' in ch_upper or (ch_upper.endswith('.DATA') and 'FRAME' not in ch_upper):
                data_channel_name = ch_name

        if not id_channel_name:
            continue

        try:
            # Get the ID signal
            id_signal = mdf.get(id_channel_name, group=group_idx)
            ids = id_signal.samples

            # Get data bytes if available
            data_bytes = None
            if data_channel_name:
                try:
                    data_signal = mdf.get(data_channel_name, group=group_idx)
                    data_bytes = data_signal.samples
                except Exception:
                    pass

            results["total_frames"] += len(ids)

            # Process each frame
            for i, frame_id in enumerate(ids):
                frame_id_int = int(frame_id) & 0x1FFFFFFF  # Mask to 29-bit

                if frame_id_int in messages_by_id:
                    msg = messages_by_id[frame_id_int]
                    message_counter[msg.name] += 1

                    # Try to decode signals if we have data bytes
                    if data_bytes is not None and i < len(data_bytes):
                        try:
                            frame_data = data_bytes[i]
                            # Convert to bytes if needed
                            if isinstance(frame_data, np.ndarray):
                                frame_data = bytes(frame_data.astype(np.uint8))
                            elif isinstance(frame_data, (list, tuple)):
                                frame_data = bytes(frame_data)
                            elif not isinstance(frame_data, bytes):
                                continue

                            # Decode signals
                            if len(frame_data) >= msg.length:
                                decoded = msg.decode(frame_data[:msg.length], decode_choices=False)
                                results["decoded_frames"] += 1

                                for sig_name, sig_value in decoded.items():
                                    signal_values[sig_name].append(sig_value)
                        except Exception:
                            pass

        except Exception as e:
            print(f"  Warning: Could not process group {group_idx}: {e}")
            continue

    # Method 2: Try extracting signals directly by name from DBC
    if not signal_values:
        print("Attempting direct signal extraction by name...")

        for msg in db.messages:
            for signal in msg.signals:
                signal_name = signal.name
                # Try common naming conventions
                possible_names = [
                    signal_name,
                    f"{msg.name}.{signal_name}",
                    f"CAN.{msg.name}.{signal_name}",
                ]

                for name in possible_names:
                    try:
                        sig_data = mdf.get(name)
                        samples = sig_data.samples
                        signal_values[signal_name].extend(samples.tolist())
                        message_counter[msg.name] += len(samples)
                        results["decoded_frames"] += len(samples)
                        break
                    except Exception:
                        continue

    # Calculate statistics
    results["message_counts"] = dict(message_counter)

    print("Calculating signal statistics...")
    for signal_name, values in signal_values.items():
        results["signal_counts"][signal_name] = len(values)

        # Count on-change events
        on_change_count = count_on_changes(values)
        results["signal_on_change_counts"][signal_name] = on_change_count

        # Count unique values
        value_counter = Counter()
        for v in values:
            # Handle numpy types
            if hasattr(v, 'item'):
                v = v.item()
            # Round floats for comparison
            if isinstance(v, float):
                v = round(v, 6)
            value_counter[v] += 1

        results["signal_unique_values"][signal_name] = len(value_counter)
        # Store top 20 most common values
        results["signal_value_distribution"][signal_name] = dict(value_counter.most_common(20))

    mdf.close()
    return results


def save_statistics_json(results: dict, output_path: str) -> None:
    """
    Save signal statistics to a JSON file.

    Args:
        results: Analysis results dictionary
        output_path: Path to save the JSON file
    """
    statistics = {
        "mf4_file": results["mf4_file"],
        "dbc_file": results["dbc_file"],
        "summary": {
            "total_frames": results["total_frames"],
            "decoded_frames": results["decoded_frames"],
            "total_messages": len(results["message_counts"]),
            "total_signals": len(results["signal_counts"]),
        },
        "messages": results["message_counts"],
        "signals": {}
    }

    # Build signal statistics
    for signal_name in results["signal_counts"]:
        statistics["signals"][signal_name] = {
            "sample_count": results["signal_counts"].get(signal_name, 0),
            "unique_value_count": results["signal_unique_values"].get(signal_name, 0),
            "on_change_count": results["signal_on_change_counts"].get(signal_name, 0),
            "value_distribution": results["signal_value_distribution"].get(signal_name, {}),
        }

    def make_serializable(obj):
        if isinstance(obj, dict):
            return {str(k): make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [make_serializable(i) for i in obj]
        elif hasattr(obj, 'item'):
            return obj.item()
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj

    serializable_stats = make_serializable(statistics)

    with open(output_path, 'w') as f:
        json.dump(serializable_stats, f, indent=2, default=str)

    print(f"\nStatistics saved to: {output_path}")


def print_results(results: dict) -> None:
    """Print analysis results in a formatted way."""
    print("\n" + "=" * 80)
    print("MF4 CAN SIGNAL ANALYSIS RESULTS")
    print("=" * 80)

    print(f"\nMF4 File: {results['mf4_file']}")
    print(f"DBC File: {results['dbc_file']}")
    print(f"\nTotal CAN Frames: {results['total_frames']:,}")
    print(f"Decoded Frames: {results['decoded_frames']:,}")

    if results["message_counts"]:
        print("\n" + "-" * 60)
        print("CAN MESSAGE COUNTS (from DBC)")
        print("-" * 60)

        sorted_messages = sorted(
            results["message_counts"].items(),
            key=lambda x: x[1],
            reverse=True
        )

        for msg_name, count in sorted_messages:
            print(f"  {msg_name}: {count:,}")

        print(f"\nTotal unique messages: {len(results['message_counts'])}")

    if results["signal_counts"]:
        print("\n" + "-" * 60)
        print("SIGNAL ANALYSIS")
        print("-" * 60)
        print(f"Total unique signals decoded: {len(results['signal_counts'])}")

        # Sort signals by sample count
        sorted_signals = sorted(
            results["signal_counts"].items(),
            key=lambda x: x[1],
            reverse=True
        )

        print("\n{:<40} {:>12} {:>12} {:>12}".format(
            "Signal Name", "Samples", "Unique Vals", "On-Change"))
        print("-" * 80)

        for signal_name, count in sorted_signals:
            unique_count = results["signal_unique_values"].get(signal_name, 0)
            on_change_count = results["signal_on_change_counts"].get(signal_name, 0)
            print(f"{signal_name:<40} {count:>12,} {unique_count:>12,} {on_change_count:>12,}")

        # Print value distribution for signals with few unique values
        print("\n" + "-" * 60)
        print("SIGNAL VALUE DISTRIBUTION (signals with <= 20 unique values)")
        print("-" * 60)

        for signal_name in sorted(results["signal_value_distribution"].keys()):
            unique_count = results["signal_unique_values"].get(signal_name, 0)
            if unique_count <= 20 and unique_count > 0:
                on_change = results["signal_on_change_counts"].get(signal_name, 0)
                print(f"\n  {signal_name} ({unique_count} unique values, {on_change:,} changes):")
                dist = results["signal_value_distribution"][signal_name]
                sorted_dist = sorted(dist.items(), key=lambda x: x[1], reverse=True)
                for value, count in sorted_dist:
                    print(f"    {value}: {count:,} occurrences")

    else:
        print("\nNo signals could be decoded.")
        print("This may happen if:")
        print("  - The MF4 file doesn't contain raw CAN frame data")
        print("  - The signal names in MF4 don't match the DBC")
        print("  - The CAN IDs in the file don't match the DBC definitions")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Messages found: {len(results['message_counts'])}")
    print(f"Signals decoded: {len(results['signal_counts'])}")
    total_samples = sum(results["signal_counts"].values())
    print(f"Total signal samples: {total_samples:,}")
    total_changes = sum(results["signal_on_change_counts"].values())
    print(f"Total on-change events: {total_changes:,}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze MF4 files and decode CAN signals using DBC files"
    )
    parser.add_argument(
        "mf4_file",
        type=str,
        help="Path to the MF4 file to analyze"
    )
    parser.add_argument(
        "-d", "--dbc",
        type=str,
        required=True,
        help="Path to the DBC file for signal decoding (required)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="signal_statistics.json",
        help="Path to save statistics JSON (default: signal_statistics.json)"
    )

    args = parser.parse_args()

    # Validate file paths
    mf4_path = Path(args.mf4_file)
    if not mf4_path.exists():
        print(f"Error: MF4 file not found: {args.mf4_file}")
        return 1

    dbc_path = Path(args.dbc)
    if not dbc_path.exists():
        print(f"Error: DBC file not found: {args.dbc}")
        return 1

    # Run analysis
    results = analyze_mf4(args.mf4_file, args.dbc)

    # Print results
    print_results(results)

    # Save statistics to JSON
    save_statistics_json(results, args.output)

    return 0


if __name__ == "__main__":
    exit(main())
