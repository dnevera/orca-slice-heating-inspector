#!/usr/bin/env python3
"""
Slice Heating Inspector — Temperature Timeline Plotter.

Generates interactive HTML Canvas-based temperature profiles for G-code analysis.
Supports single file analysis and comparison mode (e.g. OrcaSlicer vs BambuStudio).

Works with both 3MF archives and raw .gcode files.
"""
import sys
import os
import zipfile
import json
import xml.etree.ElementTree as ET
import re as _re_module

try:
    from .gcode_parser import (
        parse_critical_gcode_from_3mf,
        parse_critical_gcode_from_file,
        get_nozzle_map,
        analyze_preheat_cooldown_events,
    )
except ImportError:
    from gcode_parser import (
        parse_critical_gcode_from_3mf,
        parse_critical_gcode_from_file,
        get_nozzle_map,
        analyze_preheat_cooldown_events,
    )


def parse_filaments_and_colors(zip_file):
    """Parse filament colors and types from Metadata/slice_info.config inside 3MF."""
    filaments = {}
    try:
        xml_data = zip_file.read("Metadata/slice_info.config")
        root = ET.fromstring(xml_data)
        plate = root.find("plate")
        if plate is not None:
            for fil in plate.findall("filament"):
                fid = int(fil.attrib.get("id"))  # 1-based in XML
                color = fil.attrib.get("color")
                ftype = fil.attrib.get("type", "PLA")
                filaments[fid - 1] = {"color": color, "type": ftype}
    except Exception as e:
        print(f"Error parsing filaments: {e}")
    return filaments


def parse_nozzle_groups(zip_file):
    """
    Parse filament-to-extruder mapping from filament_maps in slice_info.config.
    
    filament_maps = "2 1 2 2 2" → {0: 2, 1: 1, 2: 2, 3: 2, 4: 2}
    
    Returns:
        extruder_map: {filament_id_0based: extruder_id}
        extruder_groups: {extruder_id: [list of filament IDs 0-based]}
    """
    extruder_map = {}
    
    try:
        xml_data = zip_file.read("Metadata/slice_info.config").decode("utf-8", errors="replace")
        root = ET.fromstring(xml_data)
        plate = root.find("plate")
        if plate is not None:
            for meta in plate.findall("metadata"):
                if meta.attrib.get("key") == "filament_maps":
                    raw = meta.attrib.get("value", "").strip()
                    if raw:
                        for i, v in enumerate(raw.split()):
                            extruder_map[i] = int(v)
                    break
    except Exception as e:
        print(f"  Warning: could not parse filament_maps: {e}")
    
    extruder_groups = {}
    for fid, eid in extruder_map.items():
        extruder_groups.setdefault(eid, []).append(fid)
    
    return extruder_map, extruder_groups


def determine_heater_to_extruder(track, extruder_map):
    # H2C physical mapping: Left (Extruder 1) -> Heater 1, Right (Extruder 2) -> Heater 0
    return {1: 1, 2: 0}


def build_timeline_and_interpolate(track, tool_changes, m73_points, total_lines, m400_weights=None,
                                    gcode_lines=None):
    """Build a line→time mapping from physical G1 motion time estimation.

    When *gcode_lines* is provided (list of raw gcode strings, 0-indexed),
    the timeline is computed from actual feedrates + M400 delays, giving a
    physically accurate time axis independent of M73 granularity.
    Falls back to M73 interpolation when gcode_lines is not available.
    """
    import re as _re
    import math as _math

    if m400_weights is None:
        m400_weights = {}

    # ── Physical timeline from G1 moves ──────────────────────────────────
    if gcode_lines is not None:
        cumulative = [0.0] * (len(gcode_lines) + 2)  # 1-indexed
        cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
        cur_f = 1800.0  # mm/min default
        t = 0.0

        for i, raw in enumerate(gcode_lines):
            line_num = i + 1
            gl = raw.strip()

            # M400 S/P delays
            ms = _re.match(r'^M400\s+S([\d.]+)', gl)
            mp = _re.match(r'^M400\s+P([\d.]+)', gl)
            if ms:
                t += float(ms.group(1))
            elif mp:
                t += float(mp.group(1)) / 1000.0

            # G1 moves
            if gl.startswith('G1 '):
                fm = _re.search(r'F([\d.]+)', gl)
                if fm:
                    cur_f = float(fm.group(1))

                xm = _re.search(r'X([-\d.]+)', gl)
                ym = _re.search(r'Y([-\d.]+)', gl)
                zm = _re.search(r'Z([-\d.]+)', gl)

                nx = float(xm.group(1)) if xm else cur_x
                ny = float(ym.group(1)) if ym else cur_y
                nz = float(zm.group(1)) if zm else cur_z

                dist = _math.sqrt((nx - cur_x)**2 + (ny - cur_y)**2 + (nz - cur_z)**2)
                if dist > 0.001 and cur_f > 0:
                    t += dist / (cur_f / 60.0)  # F is mm/min → mm/s

                cur_x, cur_y, cur_z = nx, ny, nz

            if line_num < len(cumulative):
                cumulative[line_num] = t

        # Fill any remaining slots
        for j in range(line_num + 1, len(cumulative)):
            cumulative[j] = t

        total_duration = t

        # ── Scale physical timeline to match M73 trapezoid estimate ──────
        # Physical dist/speed ignores acceleration/deceleration, giving an
        # underestimated total (e.g. 29 min vs real 48 min).  M73 from the
        # trapezoid planner accounts for accel/decel and is closer to reality.
        # We scale only the G1 motion component; M400 delays are physical
        # waits and must not be inflated.
        if m73_points and total_duration > 0:
            m73_total_sec = max(p[1] for p in m73_points) * 60

            # Compute total M400 delay time
            m400_total = 0.0
            for raw in gcode_lines:
                gl = raw.strip()
                ms = _re.match(r'^M400\s+S([\d.]+)', gl)
                mp = _re.match(r'^M400\s+P([\d.]+)', gl)
                if ms:
                    m400_total += float(ms.group(1))
                elif mp:
                    m400_total += float(mp.group(1)) / 1000.0

            g1_time = total_duration - m400_total
            m73_g1_time = m73_total_sec - m400_total

            if g1_time > 0 and m73_g1_time > g1_time:
                scale = m73_g1_time / g1_time
                # Re-scale: for each line, separate M400-contributed time
                # from G1-contributed time, scale only G1 part.
                # Since M400 delays are sparse and cumulative is monotonic,
                # we rebuild by scaling the G1 increments.
                m400_lines = set()
                for i, raw in enumerate(gcode_lines):
                    gl = raw.strip()
                    if _re.match(r'^M400\s+[SP]', gl):
                        m400_lines.add(i + 1)  # 1-indexed

                prev = 0.0
                new_t = 0.0
                for j in range(1, len(cumulative)):
                    delta = cumulative[j] - prev
                    prev = cumulative[j]
                    if j in m400_lines:
                        new_t += delta  # M400: no scale
                    else:
                        new_t += delta * scale  # G1: scale
                    cumulative[j] = new_t

                total_duration = cumulative[-1]

        def get_time(line):
            idx = max(1, min(int(round(line)), len(cumulative) - 1))
            return cumulative[idx]

        for tr in track:
            tr["time"] = get_time(tr["line"])
        for tc in tool_changes:
            tc["time"] = get_time(tc["line"])

        return total_duration, get_time

    # ── Fallback: M73-based interpolation (original logic) ───────────────
    m73_points = sorted(list(set([(p[0], p[1]) for p in m73_points])))
    filtered_m73 = []
    seen_times = set()
    for line, r_val in m73_points:
        if r_val not in seen_times:
            filtered_m73.append((line, r_val))
            seen_times.add(r_val)
    m73_points = filtered_m73
    timeline = []
    if m73_points:
        max_R = m73_points[0][1]
        for _, r in m73_points[:5]:
            if r > max_R:
                max_R = r
        for line, r in m73_points:
            elapsed_sec = (max_R - r) * 60
            timeline.append((line, elapsed_sec))
        if timeline[0][0] > 1:
            timeline.insert(0, (1, 0))
        if timeline[-1][0] < total_lines:
            timeline.append((total_lines, max_R * 60))
    else:
        timeline = [(1, 0), (total_lines, total_lines * 0.02)]

    line_to_time = {}
    # Build continuous M620 ranges from sparse track samples.
    m620_ranges = []
    m620_start = None
    for t in track:
        if t.get("in_m620", False):
            if m620_start is None:
                m620_start = t["line"]
        else:
            if m620_start is not None:
                m620_ranges.append((m620_start, t["line"]))
                m620_start = None
    if m620_start is not None:
        m620_ranges.append((m620_start, track[-1]["line"] if track else m620_start))

    def is_in_m620(l):
        for rs, re_ in m620_ranges:
            if rs <= l <= re_:
                return True
        return False
    
    for k in range(len(timeline) - 1):
        line1, time1 = timeline[k]
        line2, time2 = timeline[k + 1]
        
        dT = time2 - time1
        dL = line2 - line1
        if dL <= 0:
            continue
            
        weights = []
        total_w = 0.0
        for l in range(line1, line2 + 1):
            is_tc = is_in_m620(l)
            w = 500.0 if is_tc else 1.0
            if l in m400_weights:
                w += m400_weights[l] * 50.0
            weights.append((l, w))
            total_w += w
            
        current_t = time1
        if total_w == 0:
            total_w = 1.0
            
        for l, w in weights:
            line_to_time[l] = current_t
            current_t += (w / total_w) * dT

    def get_time(line):
        l_round = int(round(line))
        if l_round in line_to_time:
            return line_to_time[l_round]
            
        if line <= timeline[0][0]:
            return timeline[0][1]
        if line >= timeline[-1][0]:
            return timeline[-1][1]
        for k in range(len(timeline) - 1):
            pt1 = timeline[k]
            pt2 = timeline[k + 1]
            if pt1[0] <= line <= pt2[0]:
                if pt2[0] == pt1[0]:
                    return pt1[1]
                return pt1[1] + (line - pt1[0]) / (pt2[0] - pt1[0]) * (pt2[1] - pt1[1])
        return 0

    for t in track:
        t["time"] = get_time(t["line"])
    for tc in tool_changes:
        tc["time"] = get_time(tc["line"])

    total_duration = timeline[-1][1]
    return total_duration, get_time


def parse_file_data(filepath):
    if not filepath or not os.path.exists(filepath):
        return None
    try:
        with zipfile.ZipFile(filepath) as z:
            filaments = parse_filaments_and_colors(z)
            extruder_map, extruder_groups = parse_nozzle_groups(z)
            _, total_lines, _, stats = parse_critical_gcode_from_3mf(z)
            track_raw = stats["temp_track"]
            m73_points = stats.get("m73_points", [])

            # Find the start of machine end gcode to cut off non-printing trailing commands (e.g. air filtration wait)
            end_gcode_line = total_lines
            raw_gcode_lines = None
            for name in z.namelist():
                if name.endswith('.gcode'):
                    gcode_text = z.read(name).decode('utf-8', errors='replace')
                    gcode_lines = gcode_text.split('\n')
                    for i in range(len(gcode_lines) - 1, -1, -1):
                        gl = gcode_lines[i]
                        line_num = i + 1
                        if ';' in gl and '=' not in gl:
                            if 'MACHINE_END_GCODE_START' in gl or 'filament end gcode' in gl or 'machine: H2C end' in gl:
                                end_gcode_line = line_num
                                break
                    raw_gcode_lines = gcode_lines
                    break

            # Keep end_gcode_line but do not trim data arrays to preserve full time duration
            pass

            # Parse TC, Wipe Tower, Toolchange zones and M400 weights from raw gcode
            tc_zones_raw = []  # list of (start_line, end_line)
            wipe_zones_raw = []  # list of (start_line, end_line)
            toolchange_zones_raw = []  # list of (start_line, end_line)
            m400_weights = {}
            for name in z.namelist():
                if name.endswith('.gcode'):
                    gcode_text = z.read(name).decode('utf-8', errors='replace')
                    gcode_lines = gcode_text.split('\n')
                    nc_start = None
                    wipe_start = None
                    tc_block_start = None
                    for i, gl in enumerate(gcode_lines):
                        line_num = i + 1
                        # Parse M400 delay commands
                        if 'M400' in gl:
                            import re
                            m_s = re.search(r'M400\s+S(\d+)', gl)
                            if m_s:
                                m400_weights[line_num] = float(m_s.group(1))
                            else:
                                m_p = re.search(r'M400\s+P(\d+)', gl)
                                if m_p:
                                    m400_weights[line_num] = float(m_p.group(1)) * 0.001
                        # Match both Orca and BBS toolchange start comments
                        if 'CP TOOLCHANGE START' in gl:
                            tc_block_start = line_num
                        elif 'CP TOOLCHANGE END' in gl:
                            if tc_block_start is not None:
                                toolchange_zones_raw.append((tc_block_start, line_num))
                                tc_block_start = None

                        # Match BBS (; NOZZLE_CHANGE_START) and Orca (; Nozzle change start/end)
                        if 'NOZZLE_CHANGE_START' in gl or 'Nozzle change start' in gl:
                            nc_start = line_num
                        elif 'NOZZLE_CHANGE_END' in gl or 'Nozzle change end' in gl:
                            if nc_start is not None:
                                tc_zones_raw.append((nc_start, line_num))
                                nc_start = None

                        # Fallback: detect M632 M N / M633 as carousel nozzle change zones
                        # (Orca doesn't always emit ; Nozzle change start/end around M632/M633)
                        if gl.startswith('M632') and ' M ' in gl and nc_start is None:
                            nc_start = line_num
                        elif gl.startswith('M633') and nc_start is not None:
                            tc_zones_raw.append((nc_start, line_num))
                            nc_start = None
                        # Match both Orca (; CP TOOLCHANGE WIPE) and BBS (; CP_TOOLCHANGE_WIPE)
                        elif 'CP TOOLCHANGE WIPE' in gl or 'CP_TOOLCHANGE_WIPE' in gl:
                            wipe_start = line_num
                        elif '; CP TOOLCHANGE END' in gl:
                            if wipe_start is not None:
                                wipe_zones_raw.append((wipe_start, line_num))
                                wipe_start = None
                    break

        # Extract preheat events in raw G-code lines format using dynamic nozzle_map
        filament_maps_str = " ".join([str(extruder_map[i]) for i in sorted(extruder_map.keys())])
        nozzle_map_for_preheat = get_nozzle_map(filament_maps_str, track_raw)
        raw_preheats = analyze_preheat_cooldown_events(track_raw, nozzle_map_for_preheat)

        track = []
        tool_changes = []
        current_tool = 0
        for line, active_ext, t0, t1, desc, in_m620_block, printing_started in track_raw:
            if desc.startswith("T") and "Active Filament" in desc:
                parts = desc.split()
                t_name = parts[0]
                if t_name[1:].isdigit():
                    t_val = int(t_name[1:])
                    if t_val < 60000:
                        current_tool = t_val

            track.append({
                "line": line,
                "active": current_tool,
                "t0": t0,
                "t1": t1,
                "desc": desc,
                "in_m620": in_m620_block,
                "printing_started": printing_started
            })
            if desc.startswith("T") and "Active Filament" in desc:
                parts = desc.split()
                t_name = parts[0]
                t_idx = -1
                if t_name[1:].isdigit():
                    t_idx = int(t_name[1:])
                tool_changes.append({
                    "line": line,
                    "name": t_name,
                    "idx": t_idx,
                    "desc": desc,
                })

        total_duration, get_time = build_timeline_and_interpolate(track, tool_changes, m73_points, total_lines, m400_weights,
                                                                    gcode_lines=raw_gcode_lines)
        end_gcode_time = get_time(end_gcode_line)
        
        # Convert preheat lines to time (seconds)
        preheats = []
        for ev in raw_preheats:
            if ev["preheat_line"] is not None and ev["tc_line"] is not None:
                start_t = get_time(ev["preheat_line"])
                end_t = get_time(ev["tc_line"])
                preheats.append({
                    "start_time": start_t,
                    "end_time": end_t,
                    "heater": ev["target_ext"],  # 0 or 1
                    "target_temp": ev["preheat_temp"],
                    "nozzle_num": ev["nozzle_num"]
                })

        # Convert precool (cooldown) lines to time (seconds)
        # Precool = M104 S<low_temp> on the DEPARTING nozzle before tool change
        # Filter: skip S0 (heater off), negative durations, and very short zones (<2s)
        precools = []
        for ev in raw_preheats:
            if ev.get("cooldown_line") is not None and ev["tc_line"] is not None and ev.get("cooldown_temp") is not None:
                if ev["cooldown_temp"] <= 0:  # S0 = heater off, not a real precool
                    continue
                start_t = get_time(ev["cooldown_line"])
                end_t = get_time(ev["tc_line"])
                dur = end_t - start_t
                if dur < 2.0:  # Too short or negative — not a visible precool zone
                    continue
                # source_ext = the extruder that is LEAVING (opposite of target_ext)
                source_heater = 1 - ev["target_ext"] if ev["target_ext"] in (0, 1) else 0
                precools.append({
                    "start_time": start_t,
                    "end_time": end_t,
                    "heater": source_heater,
                    "target_temp": ev["cooldown_temp"],
                    "nozzle_num": ev.get("nozzle_num", -1)
                })
        
        heater_to_ext = determine_heater_to_extruder(track, extruder_map)
        
        nozzle_map = {}
        for fid, ext_id in extruder_map.items():
            nozzle_map[fid] = heater_to_ext.get(ext_id, 0)

        # Convert TC/Wipe zones to time coordinates.
        # M73 has 1-minute resolution, so TC zones (which last ~20-30s) often map
        # to identical times. When that happens, estimate width from line count ratio.
        def zone_to_time(start_line, end_line, min_dur=8.0):
            t_start = get_time(start_line)
            t_end = get_time(end_line)
            actual_dur = t_end - t_start
            if actual_dur < min_dur:
                # M73 has 1-minute resolution and BBS TC is only ~7 lines,
                # so interpolated duration can be <1s. Use line-based estimate.
                estimated_dur = max(min_dur, (end_line - start_line) * 0.15)
                t_end = t_start + estimated_dur
            return {"start_time": t_start, "end_time": t_end}

        # Sequence nozzle changes (tc_zones) and wipe tower blocks (wipe_zones) sequentially
        # to prevent visual overlaps caused by artificial duration extension.
        all_sub_zones = []
        for s, e in tc_zones_raw:
            all_sub_zones.append({"type": "nc", "start_line": s, "end_line": e})
        for s, e in wipe_zones_raw:
            all_sub_zones.append({"type": "wipe", "start_line": s, "end_line": e})
            
        all_sub_zones.sort(key=lambda z: z["start_line"])
        
        tc_zones = []
        wipe_zones = []
        prev_end_time = -1.0
        min_dur = 8.0
        
        for zone in all_sub_zones:
            s_line = zone["start_line"]
            e_line = zone["end_line"]
            t_start = get_time(s_line)
            t_end = get_time(e_line)
            
            actual_dur = t_end - t_start
            dur = actual_dur
            if actual_dur < min_dur:
                dur = max(min_dur, (e_line - s_line) * 0.15)
                
            if t_start < prev_end_time:
                t_start = prev_end_time
                
            t_end = t_start + dur
            prev_end_time = t_end
            
            formatted_zone = {"start_time": t_start, "end_time": t_end}
            if zone["type"] == "nc":
                tc_zones.append(formatted_zone)
            else:
                wipe_zones.append(formatted_zone)
                
        toolchange_zones = [zone_to_time(s, e) for s, e in toolchange_zones_raw]


        slicer_name = "OrcaSlicer" if "orca" in os.path.basename(filepath).lower() else (
            "BambuStudio" if "bbl" in os.path.basename(filepath).lower() else "Slicer"
        )

        print(f"  Extruder groups: {extruder_groups}")
        print(f"  Heater→Extruder: {heater_to_ext}")
        for fid, heater in sorted(nozzle_map.items()):
            ext_id = extruder_map.get(fid, "?")
            fil_info = filaments.get(fid, {})
            print(f"    T{fid} ({fil_info.get('type','?')} {fil_info.get('color','?')}) → Extruder {ext_id} → Heater {heater}")

        cooldown_count = sum(1 for ev in raw_preheats if ev.get("cooldown_temp") is not None)

        return {
            "filename": os.path.basename(filepath),
            "slicer": slicer_name,
            "total_lines": total_lines,
            "total_duration": total_duration,
            "end_gcode_time": end_gcode_time,
            "filaments": filaments,
            "nozzle_map": nozzle_map,
            "extruder_groups": extruder_groups,
            "heater_to_ext": heater_to_ext,
            "tool_changes": tool_changes,
            "preheats": preheats,
            "precools": precools,
            "preheat_count": len(preheats),
            "cooldown_count": cooldown_count,
            "tc_zones": tc_zones,
            "wipe_zones": wipe_zones,
            "toolchange_zones": toolchange_zones,
            "track": track,
        }
    except Exception as e:
        import traceback
        print(f"Error parsing {filepath}: {e}")
        traceback.print_exc()
        return None


def parse_file_data_from_gcode(gcode_path, config=None):
    """Parse a raw .gcode file with optional config dict for metadata.

    Args:
        gcode_path: path to the .gcode file
        config: dict with keys like 'filament_maps', 'filament_colour',
                'filament_type'. Typically from ctx.config_value() in OrcaSlicer plugin.

    Returns: data dict compatible with HTML_TEMPLATE, or None on error.
    """
    if not gcode_path or not os.path.exists(gcode_path):
        return None

    if config is None:
        config = {}

    try:
        # Get filament_maps from config
        filament_maps_str = config.get("filament_maps", "1 1 1 1 1 2")
        if isinstance(filament_maps_str, list):
            filament_maps_str = " ".join(str(x) for x in filament_maps_str)

        # Parse G-code
        _, total_lines, _, stats = parse_critical_gcode_from_file(gcode_path, filament_maps_str)
        track_raw = stats["temp_track"]
        m73_points = stats.get("m73_points", [])

        # Build filaments from config
        filaments = {}
        colours = config.get("filament_colour", [])
        types = config.get("filament_type", [])
        if isinstance(colours, str):
            colours = colours.split(";")
        if isinstance(types, str):
            types = types.split(";")
        for i in range(max(len(colours), len(types))):
            filaments[i] = {
                "color": colours[i] if i < len(colours) else "#FFFFFF",
                "type": types[i] if i < len(types) else "PLA"
            }

        # Build extruder map from filament_maps
        extruder_map = {}
        for i, v in enumerate(filament_maps_str.split()):
            try:
                extruder_map[i] = int(v)
            except ValueError:
                pass

        extruder_groups = {}
        for fid, eid in extruder_map.items():
            extruder_groups.setdefault(eid, []).append(fid)

        # Read gcode lines for timeline builder
        with open(gcode_path, 'r', encoding='utf-8', errors='replace') as f:
            raw_gcode_lines = f.read().split('\n')

        # Find end gcode marker
        end_gcode_line = total_lines
        for i in range(len(raw_gcode_lines) - 1, -1, -1):
            gl = raw_gcode_lines[i]
            if ';' in gl and '=' not in gl:
                if 'MACHINE_END_GCODE_START' in gl or 'filament end gcode' in gl or 'machine: H2C end' in gl:
                    end_gcode_line = i + 1
                    break

        # Parse TC, Wipe Tower, Toolchange zones and M400 weights
        tc_zones_raw = []
        wipe_zones_raw = []
        toolchange_zones_raw = []
        m400_weights = {}
        nc_start = None
        wipe_start = None
        tc_block_start = None

        for i, gl in enumerate(raw_gcode_lines):
            line_num = i + 1
            if 'M400' in gl:
                m_s = _re_module.search(r'M400\s+S(\d+)', gl)
                if m_s:
                    m400_weights[line_num] = float(m_s.group(1))
                else:
                    m_p = _re_module.search(r'M400\s+P(\d+)', gl)
                    if m_p:
                        m400_weights[line_num] = float(m_p.group(1)) * 0.001

            if 'CP TOOLCHANGE START' in gl:
                tc_block_start = line_num
            elif 'CP TOOLCHANGE END' in gl:
                if tc_block_start is not None:
                    toolchange_zones_raw.append((tc_block_start, line_num))
                    tc_block_start = None

            if 'NOZZLE_CHANGE_START' in gl or 'Nozzle change start' in gl:
                nc_start = line_num
            elif 'NOZZLE_CHANGE_END' in gl or 'Nozzle change end' in gl:
                if nc_start is not None:
                    tc_zones_raw.append((nc_start, line_num))
                    nc_start = None

            if gl.startswith('M632') and ' M ' in gl and nc_start is None:
                nc_start = line_num
            elif gl.startswith('M633') and nc_start is not None:
                tc_zones_raw.append((nc_start, line_num))
                nc_start = None
            elif 'CP TOOLCHANGE WIPE' in gl or 'CP_TOOLCHANGE_WIPE' in gl:
                wipe_start = line_num
            elif '; CP TOOLCHANGE END' in gl:
                if wipe_start is not None:
                    wipe_zones_raw.append((wipe_start, line_num))
                    wipe_start = None

        # Extract preheat events
        nozzle_map_for_preheat = get_nozzle_map(filament_maps_str, track_raw)
        raw_preheats = analyze_preheat_cooldown_events(track_raw, nozzle_map_for_preheat)

        # Build track and tool_changes dicts
        track = []
        tool_changes = []
        current_tool = 0
        for line, active_ext, t0, t1, desc, in_m620_block, printing_started in track_raw:
            if desc.startswith("T") and "Active Filament" in desc:
                parts = desc.split()
                t_name = parts[0]
                if t_name[1:].isdigit():
                    t_val = int(t_name[1:])
                    if t_val < 60000:
                        current_tool = t_val

            track.append({
                "line": line,
                "active": current_tool,
                "t0": t0,
                "t1": t1,
                "desc": desc,
                "in_m620": in_m620_block,
                "printing_started": printing_started
            })
            if desc.startswith("T") and "Active Filament" in desc:
                parts = desc.split()
                t_name = parts[0]
                t_idx = -1
                if t_name[1:].isdigit():
                    t_idx = int(t_name[1:])
                tool_changes.append({
                    "line": line,
                    "name": t_name,
                    "idx": t_idx,
                    "desc": desc,
                })

        total_duration, get_time = build_timeline_and_interpolate(
            track, tool_changes, m73_points, total_lines, m400_weights,
            gcode_lines=raw_gcode_lines)
        end_gcode_time = get_time(end_gcode_line)

        # Convert preheat/precool lines to time
        preheats = []
        for ev in raw_preheats:
            if ev["preheat_line"] is not None and ev["tc_line"] is not None:
                start_t = get_time(ev["preheat_line"])
                end_t = get_time(ev["tc_line"])
                preheats.append({
                    "start_time": start_t,
                    "end_time": end_t,
                    "heater": ev["target_ext"],
                    "target_temp": ev["preheat_temp"],
                    "nozzle_num": ev["nozzle_num"]
                })

        precools = []
        for ev in raw_preheats:
            if ev.get("cooldown_line") is not None and ev["tc_line"] is not None and ev.get("cooldown_temp") is not None:
                if ev["cooldown_temp"] <= 0:
                    continue
                start_t = get_time(ev["cooldown_line"])
                end_t = get_time(ev["tc_line"])
                dur = end_t - start_t
                if dur < 2.0:
                    continue
                source_heater = 1 - ev["target_ext"] if ev["target_ext"] in (0, 1) else 0
                precools.append({
                    "start_time": start_t,
                    "end_time": end_t,
                    "heater": source_heater,
                    "target_temp": ev["cooldown_temp"],
                    "nozzle_num": ev.get("nozzle_num", -1)
                })

        heater_to_ext = determine_heater_to_extruder(track, extruder_map)

        nozzle_map = {}
        for fid, ext_id in extruder_map.items():
            nozzle_map[fid] = heater_to_ext.get(ext_id, 0)

        # Zone time conversion (reuse same logic as 3MF path)
        def zone_to_time(start_line, end_line, min_dur=8.0):
            t_start = get_time(start_line)
            t_end = get_time(end_line)
            actual_dur = t_end - t_start
            if actual_dur < min_dur:
                estimated_dur = max(min_dur, (end_line - start_line) * 0.15)
                t_end = t_start + estimated_dur
            return {"start_time": t_start, "end_time": t_end}

        all_sub_zones = []
        for s, e in tc_zones_raw:
            all_sub_zones.append({"type": "nc", "start_line": s, "end_line": e})
        for s, e in wipe_zones_raw:
            all_sub_zones.append({"type": "wipe", "start_line": s, "end_line": e})
        all_sub_zones.sort(key=lambda z: z["start_line"])

        tc_zones = []
        wipe_zones = []
        prev_end_time = -1.0
        min_dur = 8.0
        for zone in all_sub_zones:
            s_line = zone["start_line"]
            e_line = zone["end_line"]
            t_start = get_time(s_line)
            t_end = get_time(e_line)
            actual_dur = t_end - t_start
            dur = actual_dur
            if actual_dur < min_dur:
                dur = max(min_dur, (e_line - s_line) * 0.15)
            if t_start < prev_end_time:
                t_start = prev_end_time
            t_end = t_start + dur
            prev_end_time = t_end
            formatted_zone = {"start_time": t_start, "end_time": t_end}
            if zone["type"] == "nc":
                tc_zones.append(formatted_zone)
            else:
                wipe_zones.append(formatted_zone)

        toolchange_zones = [zone_to_time(s, e) for s, e in toolchange_zones_raw]

        slicer_name = "OrcaSlicer"  # Raw gcode from Orca plugin is always OrcaSlicer

        cooldown_count = sum(1 for ev in raw_preheats if ev.get("cooldown_temp") is not None)

        return {
            "filename": os.path.basename(gcode_path),
            "slicer": slicer_name,
            "total_lines": total_lines,
            "total_duration": total_duration,
            "end_gcode_time": end_gcode_time,
            "filaments": filaments,
            "nozzle_map": nozzle_map,
            "extruder_groups": extruder_groups,
            "heater_to_ext": heater_to_ext,
            "tool_changes": tool_changes,
            "preheats": preheats,
            "precools": precools,
            "preheat_count": len(preheats),
            "cooldown_count": cooldown_count,
            "tc_zones": tc_zones,
            "wipe_zones": wipe_zones,
            "toolchange_zones": toolchange_zones,
            "track": track,
        }
    except Exception as e:
        import traceback
        print(f"Error parsing {gcode_path}: {e}")
        traceback.print_exc()
        return None


# Alias for clarity
parse_file_data_from_3mf = parse_file_data


def generate_html(f1_data, f2_data=None):
    """Generate HTML string from parsed data dict(s).

    Args:
        f1_data: primary file data dict (from parse_file_data or parse_file_data_from_gcode)
        f2_data: optional comparison file data dict

    Returns: HTML string ready for rendering
    """
    js_data = {
        "is_comparison": f2_data is not None,
        "file1": f1_data,
        "file2": f2_data,
        "total_duration": max(f1_data["total_duration"], f2_data["total_duration"]) if f2_data else f1_data["total_duration"],
    }
    return _load_html_template().replace("%DATA_JSON%", json.dumps(js_data))


def _load_html_template():
    """Load HTML template from the package's template.html file."""
    template_path = os.path.join(os.path.dirname(__file__), "template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

