"""
G-code parser for Slice Heating Inspector.

Provides two parsing paths:
1. parse_critical_gcode_from_3mf(zip_file) — parses G-code from inside a 3MF archive
2. parse_critical_gcode_from_file(filepath) — parses a raw .gcode file on disk

Both return the same (critical_events, total_lines, file_size, stats) tuple.

Ported from compare_slices.py (OrcaSlicer H2C analysis toolkit).
"""

import os
import re


def parse_critical_gcode_from_lines(lines_iter, filament_maps_str=None, is_byte_lines=False):
    """Core parser: works with any iterable of lines (bytes or str).

    Args:
        lines_iter: iterable of lines (bytes or str)
        filament_maps_str: e.g. "2 1 2 2 2"
        is_byte_lines: if True, decode bytes to str

    Returns:
        (critical_events, total_lines, stats)
    """
    if not filament_maps_str:
        filament_maps_str = "1 1 1 1 1 2"

    extruder_map = {}
    for i, v in enumerate(filament_maps_str.split()):
        try:
            extruder_map[i] = int(v)
        except ValueError:
            pass

    # H2C physical mapping: Left (Extruder 1) -> Heater 1, Right (Extruder 2) -> Heater 0
    heater_to_ext = {1: 1, 2: 0}
    nozzle_map = {}
    for fid, ext_id in extruder_map.items():
        nozzle_map[fid] = heater_to_ext.get(ext_id, 1)

    critical_events = []
    total_lines = 0
    toolchange_count = 0
    toolchange_sequence = []
    prime_tower_blocks = 0
    prime_tower_lines = 0
    in_prime_tower = False

    m620_11_retracts = []
    temp_events = []

    active_extruder = 0
    next_filament = 0
    temp_T0 = 0
    temp_T1 = 0
    temp_track = []

    toolchange_blocks = []
    current_tc_block = []
    in_tc_block = False
    in_m620_block = False
    printing_started = False
    m73_points = []

    for line_raw in lines_iter:
        total_lines += 1
        if is_byte_lines:
            line = line_raw.decode("utf-8", errors="ignore").strip()
        else:
            line = line_raw.strip()

        if "; CHANGE_LAYER" in line:
            printing_started = True

        # Special check for H2C virtual temperature commands (e.g. ;VM104, ;VM109)
        is_virtual_temp = False
        if line.startswith(";VM104") or line.startswith(";VM109"):
            is_virtual_temp = True
            cmd_part = line[1:].split(";")[0].strip()
        else:
            cmd_part = line.split(";")[0].strip()

        if ";======== H2C filament_change ========" in line:
            in_tc_block = True
            current_tc_block = [f"Line {total_lines}: {line}"]
        elif in_tc_block:
            current_tc_block.append(f"Line {total_lines}: {line}")
            if "M1002 gcode_claim_action : 0" in cmd_part:
                in_tc_block = False
                toolchange_blocks.append("\n".join(current_tc_block))

        if not cmd_part:
            continue

        words = cmd_part.split()
        first_word = words[0]

        if first_word == "M628" and "S1" in cmd_part:
            in_prime_tower = True
            prime_tower_blocks += 1
        elif first_word == "M628" and "S0" in cmd_part:
            in_prime_tower = False

        if in_prime_tower:
            prime_tower_lines += 1

        if first_word == "M73" and not first_word.startswith("M73.2"):
            parts = cmd_part.split()
            r_val = next((p for p in parts if p.startswith("R")), None)
            p_val = next((p for p in parts if p.startswith("P")), None)
            if r_val and p_val:
                try:
                    r_min = int(r_val[1:])
                    m73_points.append((total_lines, r_min))
                except ValueError:
                    pass

        is_critical = False

        if first_word.startswith("T") and first_word[1:].isdigit():
            is_critical = True
            toolchange_count += 1
            toolchange_sequence.append(first_word)
            t_val = int(first_word[1:])
            if t_val < 60000:
                active_extruder = t_val
                next_filament = t_val
            temp_track.append((total_lines, active_extruder, temp_T0, temp_T1,
                             f"T{t_val} (Active Filament: T{t_val})", in_m620_block, printing_started))

        elif any(first_word.startswith(prefix) for prefix in ["M620", "M621", "M622", "M623", "M628", "M629", "M1002", "G29"]):
            is_critical = True
            if first_word == "M620":
                in_m620_block = True
                parts = cmd_part.split()
                s_val = next((p for p in parts if p.startswith("S")), None)
                if s_val and s_val.endswith("A") and len(s_val) > 2:
                    try:
                        next_filament = int(s_val[1:-1])
                    except ValueError:
                        pass
            elif first_word == "M621":
                in_m620_block = False
            elif first_word == "M620.11":
                parts = cmd_part.split()
                e_val = next((p for p in parts if p.startswith("E")), "E?")
                r_val = next((p for p in parts if p.startswith("R")), "R?")
                f_val = next((p for p in parts if p.startswith("F")), "F?")
                m620_11_retracts.append(f"{e_val} {r_val} {f_val}")
            elif first_word == "M620.15":
                parts = cmd_part.split()
                p_val = next((p for p in parts if p.startswith("P")), None)
                c_val = next((p for p in parts if p.startswith("C")), None)
                desc_parts = []
                target_heater = 1 if next_filament == 1 else 0
                if p_val:
                    desc_parts.append(f"Pre-cool P{p_val[1:]}°C")
                    temp_events.append((total_lines, f"M620.15 Pre-cool P{p_val[1:]}°C"))
                    try:
                        val = int(p_val[1:])
                        if target_heater == 0:
                            temp_T0 = val
                        else:
                            temp_T1 = val
                    except ValueError:
                        pass
                if c_val:
                    desc_parts.append(f"Target-cool C{c_val[1:]}°C")
                    temp_events.append((total_lines, f"M620.15 Target-cool C{c_val[1:]}°C"))
                    try:
                        val = int(c_val[1:])
                        if target_heater == 0:
                            temp_T0 = val
                        else:
                            temp_T1 = val
                    except ValueError:
                        pass
                desc = " & ".join(desc_parts)
                temp_track.append((total_lines, active_extruder, temp_T0, temp_T1,
                                 f"M620.15 {desc}", in_m620_block, printing_started))

        elif any(first_word.startswith(prefix) for prefix in ["M104", "M109", "VM104", "VM109"]):
            is_critical = True
            parts = cmd_part.split()
            s_val = next((p for p in parts if p.startswith("S")), None)
            t_val = next((p for p in parts if p.startswith("T")), "")
            if s_val:
                s_temp = int(s_val[1:])
                t_desc = f" T{t_val[1:]}" if t_val else ""
                temp_events.append((total_lines, f"{first_word}{t_desc} S{s_val[1:]}°C"))

                # Determine target heater
                if t_val:
                    if t_val == "T0":
                        targeted_heater = 0
                    elif t_val == "T1":
                        targeted_heater = 1
                    else:
                        targeted_heater = 0
                else:
                    targeted_heater = nozzle_map.get(active_extruder, 1)

                if targeted_heater == 0:
                    temp_T0 = s_temp
                else:
                    temp_T1 = s_temp

                temp_track.append((total_lines, active_extruder, temp_T0, temp_T1,
                                 f"{first_word}{t_desc} S{s_temp}°C", in_m620_block, printing_started))

        if is_critical:
            critical_events.append(f"Line {total_lines}: {cmd_part}")

        # Insert regular temperature samples every 100 lines
        if total_lines % 100 == 0:
            temp_track.append((total_lines, active_extruder, temp_T0, temp_T1,
                             "Regular Sample", in_m620_block, printing_started))

    stats = {
        "toolchange_count": toolchange_count,
        "toolchange_sequence": toolchange_sequence,
        "prime_tower_blocks": prime_tower_blocks,
        "prime_tower_lines": prime_tower_lines,
        "m620_11_retracts": sorted(list(set(m620_11_retracts))),
        "temp_events": temp_events,
        "temp_track": temp_track,
        "toolchange_blocks": toolchange_blocks,
        "m73_points": m73_points
    }
    return critical_events, total_lines, stats


def parse_critical_gcode_from_3mf(zip_file, filament_maps_str=None):
    """Parse G-code from inside a 3MF archive.

    Returns: (critical_events, total_lines, file_size, stats)
    """
    # Try to parse filament_maps from Metadata/slice_info.config if not provided
    if not filament_maps_str:
        try:
            import xml.etree.ElementTree as ET
            xml_data = zip_file.read("Metadata/slice_info.config")
            root = ET.fromstring(xml_data)
            plate = root.find("plate")
            if plate is not None:
                for meta in plate.findall("metadata"):
                    if meta.attrib.get("key") == "filament_maps":
                        filament_maps_str = meta.attrib.get("value", "").strip()
                        break
        except Exception:
            pass

    gcode_names = [name for name in zip_file.namelist() if name.endswith('.gcode')]
    if not gcode_names:
        raise KeyError("No .gcode file found in 3mf")
    gcode_name = gcode_names[0]
    info = zip_file.getinfo(gcode_name)
    file_size = info.file_size

    with zip_file.open(gcode_name) as f:
        critical_events, total_lines, stats = parse_critical_gcode_from_lines(
            f, filament_maps_str, is_byte_lines=True)

    return critical_events, total_lines, file_size, stats


def parse_critical_gcode_from_file(filepath, filament_maps_str=None):
    """Parse a raw .gcode file on disk.

    Returns: (critical_events, total_lines, file_size, stats)
    """
    file_size = os.path.getsize(filepath)
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        critical_events, total_lines, stats = parse_critical_gcode_from_lines(
            f, filament_maps_str, is_byte_lines=False)

    return critical_events, total_lines, file_size, stats


def get_nozzle_map(filament_maps_str, track):
    """Build filament -> heater mapping.

    Returns: {filament_id: heater_index}
    """
    if not filament_maps_str:
        filament_maps_str = "1 1 1 1 1 2"

    extruder_map = {}
    for i, v in enumerate(filament_maps_str.split()):
        try:
            extruder_map[i] = int(v)
        except ValueError:
            pass

    # H2C physical mapping: Left (Extruder 1) -> Heater 1, Right (Extruder 2) -> Heater 0
    heater_to_ext = {1: 1, 2: 0}
    nozzle_map = {}
    for fid, ext_id in extruder_map.items():
        nozzle_map[fid] = heater_to_ext.get(ext_id, 1)

    return nozzle_map


def analyze_preheat_cooldown_events(track, nozzle_map=None):
    """Detect preheat and cooldown events from temperature track.

    Args:
        track: list of (line, active_ext, t0, t1, desc, in_m620, printing_started)
        nozzle_map: {filament_id: heater_index}

    Returns: list of event dicts with keys:
        tc_line, target_ext, nozzle_num, preheat_line, preheat_temp,
        cooldown_line, cooldown_temp
    """
    if nozzle_map is None:
        nozzle_map = {1: 1}

    events = []
    tc_indices = []

    prev_nozzle = None
    for idx, item in enumerate(track):
        desc = item[4]
        if desc.startswith("T") and "Active Filament" in desc:
            first_part = desc.split()[0]
            t_num_str = first_part[1:]
            if t_num_str.isdigit():
                t_num = int(t_num_str)
                if t_num >= 60000:
                    continue

                norm_nozzle = t_num
                if t_num == 1000:
                    norm_nozzle = 0
                elif t_num == 1001:
                    norm_nozzle = 1

                if prev_nozzle is not None and norm_nozzle != prev_nozzle:
                    target_ext = nozzle_map.get(norm_nozzle, 0)
                    source_ext = nozzle_map.get(prev_nozzle, 0)
                    if target_ext != source_ext:
                        tc_indices.append((idx, item[0], target_ext, source_ext, norm_nozzle))
                prev_nozzle = norm_nozzle

    for i, (tc_idx, tc_line, target_ext, source_ext, nozzle_num) in enumerate(tc_indices):
        # Look for preheat command for target_ext before the toolchange
        preheat_line = None
        preheat_temp = None

        prev_tc_idx = tc_indices[i - 1][0] if i > 0 else 0
        for k in range(tc_idx - 1, prev_tc_idx - 1, -1):
            desc_k = track[k][4]
            active_ext_k = track[k][1]

            if "M104" in desc_k or "M109" in desc_k:
                words = desc_k.split()
                s_temp_str = next((w[1:].replace("°C", "") for w in words if w.startswith("S")), None)
                t_val = next((w for w in words if w.startswith("T")), None)

                targeted = None
                if t_val == "T0":
                    targeted = 0
                elif t_val == "T1":
                    targeted = 1
                elif t_val is None:
                    targeted = nozzle_map.get(active_ext_k, 0)

                if targeted is not None and targeted == target_ext and s_temp_str and s_temp_str.isdigit():
                    temp_val = int(s_temp_str)
                    if temp_val >= 150:
                        preheat_line = track[k][0]
                        preheat_temp = temp_val
                        break

            elif "M620.15" in desc_k and target_ext == 1:
                words = desc_k.split()
                p_temp_str = next((w[1:].replace("°C", "") for w in words
                                  if w.startswith("P") and len(w) > 1 and w[1].isdigit()), None)
                c_temp_str = next((w[1:].replace("°C", "") for w in words
                                  if w.startswith("C") and len(w) > 1 and w[1].isdigit()), None)

                temp_val = None
                if p_temp_str and p_temp_str.isdigit():
                    temp_val = int(p_temp_str)
                elif c_temp_str and c_temp_str.isdigit():
                    temp_val = int(c_temp_str)

                if temp_val and temp_val >= 150:
                    preheat_line = track[k][0]
                    preheat_temp = temp_val

        # Look for cooldown command around the toolchange
        cooldown_line = None
        cooldown_temp = None
        start_look = max(0, tc_idx - 15)
        end_look = min(len(track), tc_idx + 40)

        for k in range(start_look, end_look):
            desc_k = track[k][4]
            active_ext_k = track[k][1]

            if "M104" in desc_k or "M109" in desc_k:
                words = desc_k.split()
                s_temp_str = next((w[1:].replace("°C", "") for w in words if w.startswith("S")), None)
                t_val = next((w for w in words if w.startswith("T")), None)

                targeted = None
                if t_val == "T0":
                    targeted = 0
                elif t_val == "T1":
                    targeted = 1
                elif t_val is None:
                    targeted = nozzle_map.get(active_ext_k, 0)

                if targeted == source_ext and s_temp_str and s_temp_str.isdigit():
                    temp_val = int(s_temp_str)
                    if temp_val < 200:
                        cooldown_line = track[k][0]
                        cooldown_temp = temp_val
                        break

            elif "M620.15" in desc_k and source_ext == 1:
                words = desc_k.split()
                p_temp_str = next((w[1:].replace("°C", "") for w in words
                                  if w.startswith("P") and len(w) > 1 and w[1].isdigit()), None)
                c_temp_str = next((w[1:].replace("°C", "") for w in words
                                  if w.startswith("C") and len(w) > 1 and w[1].isdigit()), None)

                temp_val = None
                if p_temp_str and p_temp_str.isdigit():
                    temp_val = int(p_temp_str)
                elif c_temp_str and c_temp_str.isdigit():
                    temp_val = int(c_temp_str)

                if temp_val and temp_val < 200:
                    cooldown_line = track[k][0]
                    cooldown_temp = temp_val
                    break

        events.append({
            "tc_line": tc_line,
            "target_ext": target_ext,
            "nozzle_num": nozzle_num,
            "preheat_line": preheat_line,
            "preheat_temp": preheat_temp,
            "cooldown_line": cooldown_line,
            "cooldown_temp": cooldown_temp
        })
    return events
