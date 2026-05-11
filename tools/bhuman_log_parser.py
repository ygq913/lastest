#!/usr/bin/env python3
"""
B-Human 日志解析器 (bhuman_log_parser.py)
=========================================
高性能解析 B-Human 机器人二进制日志文件(.log)，提取关键比赛数据并生成分析报告。

使用 mmap + 预计算类型尺寸 + 选择性反序列化，可处理 2-3GB 的大日志。

用法:
    python3 bhuman_log_parser.py <日志目录> [-o 输出报告.md] [--json 输出.json]
    python3 bhuman_log_parser.py <日志目录> --largest-only

示例:
    python3 bhuman_log_parser.py "../Config/Logs/5.2VS 武汉大学"
    python3 bhuman_log_parser.py "../Config/Logs/5.2VS 武汉大学" -o match2_report.md

作者: FLY Team
"""

import struct
import sys
import os
import json
import math
import glob
import mmap
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
import time as _time


# ============================================================================
# 快速 mmap 二进制读取器
# ============================================================================

class FastReader:
    """基于 mmap 的快速二进制读取器。"""

    def __init__(self, filepath):
        self._file = open(filepath, 'rb')
        self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._pos = 0
        self._size = self._mm.size()

    def close(self):
        self._mm.close()
        self._file.close()

    @property
    def pos(self):
        return self._pos

    @property
    def remaining(self):
        return self._size - self._pos

    def seek(self, pos):
        self._pos = pos

    def skip(self, n):
        self._pos += n

    def eof(self):
        return self._pos >= self._size

    def read_bytes(self, n):
        end = self._pos + n
        if end > self._size:
            raise EOFError()
        data = self._mm[self._pos:end]
        self._pos = end
        return data

    def read_u8(self):
        if self._pos >= self._size:
            raise EOFError()
        v = self._mm[self._pos]
        self._pos += 1
        return v

    def read_u32(self):
        end = self._pos + 4
        v = struct.unpack_from('<I', self._mm, self._pos)[0]
        self._pos = end
        return v

    def read_i32(self):
        v = struct.unpack_from('<i', self._mm, self._pos)[0]
        self._pos += 4
        return v

    def read_f32(self):
        v = struct.unpack_from('<f', self._mm, self._pos)[0]
        self._pos += 4
        return v

    def read_str(self):
        slen = self.read_u32()
        s = self._mm[self._pos:self._pos + slen].decode('ascii', errors='replace')
        self._pos += slen
        return s

    def read_msg_header(self):
        """读取消息头：返回 (msg_id, msg_size)。"""
        val = struct.unpack_from('<I', self._mm, self._pos)[0]
        self._pos += 4
        msg_id = val & 0xFF
        msg_size = val >> 8
        return msg_id, msg_size

    def slice_bytes(self, n):
        """返回当前位置开始的 n 字节 memoryview，不拷贝。"""
        end = self._pos + n
        if end > self._size:
            raise EOFError()
        mv = self._mm[self._pos:end]
        self._pos = end
        return mv


# ============================================================================
# 快速消息体解析（直接 struct.unpack_from，无递归）
# ============================================================================

class MessageParser:
    """
    预计算每个目标 representation 的类型尺寸，
    对固定大小的 representation 使用 struct.unpack_from 一次性读取。
    对变长 representation（含动态数组/字符串）使用流式解析。
    """

    def __init__(self, classes, enums, primitives):
        self.classes = classes
        self.enums = enums
        self.primitives = set(primitives)
        self._size_cache = {}
        self._enum_values = {}  # enum_name -> [str, ...]

        for ename, consts in enums.items():
            self._enum_values[ename] = consts

    def type_size(self, type_name):
        """
        计算类型的固定二进制大小。
        返回 None 表示变长（含动态数组或字符串）。
        缓存结果。
        """
        if type_name in self._size_cache:
            return self._size_cache[type_name]

        result = self._compute_size(type_name)
        self._size_cache[type_name] = result
        return result

    def _compute_size(self, type_name):
        # 动态数组
        if type_name.endswith('*'):
            return None

        # 静态数组
        if type_name.endswith(']'):
            bracket = type_name.rfind('[')
            base = type_name[:bracket]
            count = int(type_name[bracket + 1:-1])
            base_size = self.type_size(base)
            if base_size is None:
                return None
            return base_size * count

        # 基本类型
        prim_sizes = {
            'bool': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1,
            'short': 2, 'unsigned short': 2,
            'int': 4, 'unsigned int': 4,
            'float': 4, 'double': 8, 'Angle': 4,
        }
        if type_name in prim_sizes:
            return prim_sizes[type_name]

        # Eigen
        if type_name.startswith('Eigen::Matrix<'):
            inner = type_name[len('Eigen::Matrix<'):-1]
            parts = inner.split(',')
            scalar = parts[0].strip()
            rows = int(parts[1].strip())
            cols = int(parts[2].strip())
            s = prim_sizes.get(scalar)
            if s is None:
                return None
            return s * rows * cols

        # 枚举
        if type_name in self.enums:
            return 1  # unsigned char

        # std::string
        if type_name == 'std::string':
            return None

        # std::optional
        if type_name.startswith('std::optional<'):
            return None

        # 结构体
        if type_name in self.classes:
            total = 0
            for _, attr_type in self.classes[type_name]:
                s = self.type_size(attr_type)
                if s is None:
                    return None
                total += s
            return total

        return None

    def parse_type(self, buf, offset, type_name):
        """
        从 buf[offset:] 解析 type_name，返回 (value, new_offset)。
        buf 是 bytes/memoryview。
        """
        # 动态数组
        if type_name.endswith('*'):
            base = type_name[:-1]
            count = struct.unpack_from('<I', buf, offset)[0]
            offset += 4
            items = []
            for _ in range(count):
                val, offset = self.parse_type(buf, offset, base)
                items.append(val)
            return items, offset

        # 静态数组
        if type_name.endswith(']'):
            bracket = type_name.rfind('[')
            base = type_name[:bracket]
            count = int(type_name[bracket + 1:-1])
            items = []
            for _ in range(count):
                val, offset = self.parse_type(buf, offset, base)
                items.append(val)
            return items, offset

        # 基本类型
        if type_name == 'bool':
            return (buf[offset] != 0), offset + 1
        if type_name in ('char', 'signed char'):
            return struct.unpack_from('<b', buf, offset)[0], offset + 1
        if type_name == 'unsigned char':
            return buf[offset], offset + 1
        if type_name == 'short':
            return struct.unpack_from('<h', buf, offset)[0], offset + 2
        if type_name == 'unsigned short':
            return struct.unpack_from('<H', buf, offset)[0], offset + 2
        if type_name == 'int':
            return struct.unpack_from('<i', buf, offset)[0], offset + 4
        if type_name == 'unsigned int':
            return struct.unpack_from('<I', buf, offset)[0], offset + 4
        if type_name in ('float', 'Angle'):
            return struct.unpack_from('<f', buf, offset)[0], offset + 4
        if type_name == 'double':
            return struct.unpack_from('<d', buf, offset)[0], offset + 8

        # Eigen
        if type_name.startswith('Eigen::Matrix<'):
            inner = type_name[len('Eigen::Matrix<'):-1]
            parts = inner.split(',')
            scalar = parts[0].strip()
            rows = int(parts[1].strip())
            cols = int(parts[2].strip())
            n = rows * cols
            fmt_map = {'float': 'f', 'double': 'd', 'int': 'i', 'unsigned int': 'I'}
            fmt_char = fmt_map.get(scalar, 'f')
            fmt = f'<{n}{fmt_char}'
            sz = struct.calcsize(fmt)
            vals = struct.unpack_from(fmt, buf, offset)
            if cols == 1:
                return tuple(vals), offset + sz
            return list(vals), offset + sz

        # 枚举
        if type_name in self.enums:
            idx = buf[offset]
            consts = self._enum_values[type_name]
            val = consts[idx] if idx < len(consts) else f'?{idx}'
            return val, offset + 1

        # std::string
        if type_name == 'std::string':
            slen = struct.unpack_from('<I', buf, offset)[0]
            offset += 4
            s = bytes(buf[offset:offset + slen]).decode('ascii', errors='replace')
            return s, offset + slen

        # std::optional
        if type_name.startswith('std::optional<') and type_name.endswith('>'):
            inner = type_name[len('std::optional<'):-1]
            has = buf[offset] != 0
            offset += 1
            if has:
                return self.parse_type(buf, offset, inner)
            return None, offset

        # 结构体
        if type_name in self.classes:
            result = {}
            for attr_name, attr_type in self.classes[type_name]:
                val, offset = self.parse_type(buf, offset, attr_type)
                result[attr_name] = val
            return result, offset

        raise ValueError(f"未知类型: {type_name}")

    def safe_parse(self, buf, type_name):
        """安全解析，失败返回 None。"""
        try:
            val, _ = self.parse_type(buf, 0, type_name)
            return val
        except Exception:
            return None


# ============================================================================
# 日志文件解析器
# ============================================================================

CHUNK_UNCOMPRESSED = 0
CHUNK_COMPRESSED = 1
CHUNK_MESSAGE_IDS = 2
CHUNK_TYPE_INFO = 3
CHUNK_SETTINGS = 4


class BHumanLogFile:
    """高性能解析单个 B-Human 二进制日志文件。"""

    def __init__(self, filepath):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.settings = {}
        self.id_names = []
        self.id_map = {}
        self.type_info = {'primitives': [], 'classes': {}, 'enums': {}}
        self._parser = None

    def parse(self):
        """解析日志文件并返回统计结果。"""
        file_size = os.path.getsize(self.filepath)
        print(f"解析: {self.filename} ({file_size / 1024 / 1024:.1f} MB)")

        reader = FastReader(self.filepath)
        try:
            self._parse_header(reader)
            print(f"  {self.settings['headName']} P{self.settings['playerNumber']} "
                  f"({self.settings['location']}/{self.settings['scenario']})")
            print(f"  MessageIDs: {len(self.id_names)}, "
                  f"Classes: {len(self.type_info['classes'])}, "
                  f"Enums: {len(self.type_info['enums'])}")

            # 读取数据块类型
            chunk = reader.read_u8()
            if chunk == CHUNK_UNCOMPRESSED:
                reader.skip(8)  # QueueHeader
                stats = self._scan_messages(reader)
                return stats
            elif chunk == CHUNK_COMPRESSED:
                print("  ⚠️ 压缩日志暂不支持")
                return None
            else:
                print(f"  ⚠️ 未知数据块类型: {chunk}")
                return None
        finally:
            reader.close()

    def _parse_header(self, reader):
        """解析 settings + messageIDs + typeInfo。"""
        # Settings
        chunk = reader.read_u8()
        assert chunk == CHUNK_SETTINGS
        ver = reader.read_u32()
        self.settings = {
            'headName': reader.read_str(),
            'bodyName': reader.read_str(),
            'playerNumber': reader.read_i32(),
            'location': reader.read_str(),
            'scenario': reader.read_str(),
        }

        # MessageIDs
        chunk = reader.read_u8()
        assert chunk == CHUNK_MESSAGE_IDS
        num_ids = reader.read_u8()
        self.id_names = [reader.read_str() for _ in range(num_ids)]
        self.id_map = {name: i for i, name in enumerate(self.id_names)}

        # TypeInfo
        chunk = reader.read_u8()
        assert chunk == CHUNK_TYPE_INFO
        size = reader.read_u32() & 0x7FFFFFFF
        primitives = [reader.read_str() for _ in range(size)]
        self.type_info['primitives'] = primitives

        num_classes = reader.read_u32()
        classes = {}
        for _ in range(num_classes):
            cname = reader.read_str()
            num_attrs = reader.read_u32()
            attrs = [(reader.read_str(), reader.read_str()) for _ in range(num_attrs)]
            classes[cname] = attrs
        self.type_info['classes'] = classes

        num_enums = reader.read_u32()
        enums = {}
        for _ in range(num_enums):
            ename = reader.read_str()
            num_const = reader.read_u32()
            consts = [reader.read_str() for _ in range(num_const)]
            enums[ename] = consts
        self.type_info['enums'] = enums

        self._parser = MessageParser(classes, enums, primitives)

    def _scan_messages(self, reader):
        """
        快速扫描所有消息，提取关键统计信息。
        不存储每帧数据到内存——边扫描边统计。
        """
        parser = self._parser
        id_map = self.id_map

        # 目标消息 ID 映射
        targets = {}
        target_list = [
            'idFrameBegin', 'idFrameFinished',
            'idActivationGraph', 'idSkillRequest', 'idBallModel',
            'idTeamBallModel', 'idRobotPose', 'idObstacleModel',
            'idTeamData', 'idMotionInfo', 'idFallDownState',
            'idFrameInfo', 'idGlobalOpponentsModel', 'idBehaviorStatus',
            'idStrategyStatus', 'idGameState', 'idGroundContactState',
            'idReceivedTeamMessages',
        ]
        for name in target_list:
            if name in id_map:
                targets[id_map[name]] = name

        # 统计计数器
        skill_counts = Counter()
        behavior_counts = Counter()
        role_counts = Counter()
        position_counts = Counter()
        tactic_counts = Counter()
        fall_state_counts = Counter()
        motion_phase_counts = Counter()
        game_state_counts = Counter()
        game_phase_counts = Counter()
        obs_type_counts = Counter()
        unknown_opp_counts = Counter()

        team_ball_valid = 0
        team_ball_invalid = 0
        local_ball_seen = 0
        facing_ball = 0
        back_to_ball = 0
        total_obstacles = 0
        total_opp_estimates = 0
        total_received_msgs = 0
        total_unsync = 0
        teammate_counts = Counter()
        ground_contact_lost = 0
        ground_contact_total = 0

        cognition_frames = 0
        motion_frames = 0
        msg_count = 0

        # 当前帧的临时存储（只保留当前帧的关键值）
        cur_thread = None
        cur_team_ball = None  # (x, y, is_valid)
        cur_robot_pose = None  # (tx, ty, rot)
        cur_frame_time = 0

        t_start = _time.time()

        while not reader.eof():
            try:
                msg_id, msg_size = reader.read_msg_header()
            except EOFError:
                break

            if msg_size > reader.remaining:
                break

            id_name = targets.get(msg_id)

            if id_name is None:
                # 不关心的消息，跳过
                reader.skip(msg_size)
                msg_count += 1
                continue

            if id_name == 'idFrameBegin':
                buf = reader.slice_bytes(msg_size)
                try:
                    slen = struct.unpack_from('<I', buf, 0)[0]
                    cur_thread = bytes(buf[4:4 + slen]).decode('ascii', errors='replace')
                except:
                    cur_thread = None
                # 重置当前帧数据
                cur_team_ball = None
                cur_robot_pose = None
                msg_count += 1
                continue

            if id_name == 'idFrameFinished':
                reader.skip(msg_size)
                if cur_thread == 'Cognition':
                    cognition_frames += 1
                    # 帧结束时计算面朝球/背对球
                    if cur_team_ball and cur_team_ball[2] and cur_robot_pose:
                        bx, by = cur_team_ball[0], cur_team_ball[1]
                        tx, ty, rot = cur_robot_pose
                        dx = bx - tx
                        dy = by - ty
                        angle_to_ball = math.atan2(dy, dx)
                        angle_diff = abs(angle_to_ball - rot)
                        while angle_diff > math.pi:
                            angle_diff = abs(angle_diff - 2 * math.pi)
                        if angle_diff < math.pi / 2:
                            facing_ball += 1
                        if angle_diff > 2 * math.pi / 3:
                            back_to_ball += 1
                elif cur_thread == 'Motion':
                    motion_frames += 1
                msg_count += 1
                continue

            # 读取消息体
            buf = reader.slice_bytes(msg_size)
            msg_count += 1

            try:
                if id_name == 'idFrameInfo':
                    # FrameInfo: time(u32)
                    cur_frame_time = struct.unpack_from('<I', buf, 0)[0]

                elif id_name == 'idSkillRequest':
                    # SkillRequest: skill(enum u8), target(Pose2f=12B), passTarget(i32)
                    parsed = parser.safe_parse(buf, 'SkillRequest')
                    if parsed:
                        skill_counts[parsed.get('skill', '?')] += 1

                elif id_name == 'idActivationGraph':
                    parsed = parser.safe_parse(buf, 'ActivationGraph')
                    if parsed and 'graph' in parsed:
                        for node in parsed['graph']:
                            if isinstance(node, dict):
                                opt = node.get('option', '')
                                if opt:
                                    behavior_counts[opt] += 1

                elif id_name == 'idStrategyStatus':
                    parsed = parser.safe_parse(buf, 'StrategyStatus')
                    if parsed:
                        role_counts[parsed.get('role', '?')] += 1
                        position_counts[parsed.get('position', '?')] += 1
                        tactic_counts[parsed.get('acceptedTactic', '?')] += 1

                elif id_name == 'idTeamBallModel':
                    # TeamBallModel: position(2f), velocity(2f), isValid(bool), newerThanOwnBall(bool)
                    px, py = struct.unpack_from('<ff', buf, 0)
                    # skip velocity (8B)
                    is_valid = buf[16] != 0
                    cur_team_ball = (px, py, is_valid)
                    if is_valid:
                        team_ball_valid += 1
                    else:
                        team_ball_invalid += 1

                elif id_name == 'idRobotPose':
                    # RobotPose: rotation(f32), translation(2f), ...
                    rot = struct.unpack_from('<f', buf, 0)[0]
                    tx, ty = struct.unpack_from('<ff', buf, 4)
                    cur_robot_pose = (tx, ty, rot)

                elif id_name == 'idBallModel':
                    # BallModel: lastPerception(2f=8B), estimate(BallState=...), timeWhenLastSeen(u32), ...
                    # BallState: position(2f=8B), velocity(2f=8B), radius(f=4B), covariance(4f=16B) = 36B
                    # offset to timeWhenLastSeen: 8 + 36 = 44
                    if len(buf) >= 48:
                        twls = struct.unpack_from('<I', buf, 44)[0]
                        if twls > 0 and cur_frame_time > 0:
                            if cur_frame_time - twls < 3000:
                                local_ball_seen += 1

                elif id_name == 'idObstacleModel':
                    parsed = parser.safe_parse(buf, 'ObstacleModel')
                    if parsed and 'obstacles' in parsed:
                        for obs in parsed['obstacles']:
                            if isinstance(obs, dict):
                                otype = obs.get('type', '?')
                                obs_type_counts[otype] += 1
                                total_obstacles += 1

                elif id_name == 'idTeamData':
                    parsed = parser.safe_parse(buf, 'TeamData')
                    if parsed:
                        total_received_msgs += parsed.get('receivedMessages', 0)
                        total_unsync += parsed.get('receivedUnsynchronizedMessages', 0)
                        teammates = parsed.get('teammates', [])
                        if isinstance(teammates, list):
                            for t in teammates:
                                if isinstance(t, dict):
                                    tnum = t.get('number', 0)
                                    if tnum > 0:
                                        teammate_counts[tnum] += 1

                elif id_name == 'idGlobalOpponentsModel':
                    parsed = parser.safe_parse(buf, 'GlobalOpponentsModel')
                    if parsed:
                        nu = parsed.get('numOfUnknownOpponents', 0)
                        unknown_opp_counts[nu] += 1
                        opps = parsed.get('opponents', [])
                        if isinstance(opps, list):
                            total_opp_estimates += len(opps)

                elif id_name == 'idFallDownState':
                    parsed = parser.safe_parse(buf, 'FallDownState')
                    if parsed:
                        fall_state_counts[parsed.get('state', '?')] += 1

                elif id_name == 'idMotionInfo':
                    parsed = parser.safe_parse(buf, 'MotionInfo')
                    if parsed:
                        motion_phase_counts[parsed.get('executedPhase', '?')] += 1

                elif id_name == 'idGroundContactState':
                    # GroundContactState: contact(bool), lastGroundContactTimestamp(u32)
                    ground_contact_total += 1
                    if not (buf[0] != 0):
                        ground_contact_lost += 1

                elif id_name == 'idGameState':
                    parsed = parser.safe_parse(buf, 'GameState')
                    if parsed:
                        game_state_counts[parsed.get('state', '?')] += 1
                        game_phase_counts[parsed.get('phase', '?')] += 1

                elif id_name == 'idBehaviorStatus':
                    # 不需要完全解析，但保留给传球目标分析
                    pass

                elif id_name == 'idReceivedTeamMessages':
                    parsed = parser.safe_parse(buf, 'ReceivedTeamMessages')
                    if parsed:
                        total_unsync += parsed.get('unsynchronizedMessages', 0)

            except Exception:
                pass

            # 进度
            if msg_count % 200000 == 0:
                elapsed = _time.time() - t_start
                mb_done = reader.pos / 1024 / 1024
                total_mb = reader._size / 1024 / 1024
                speed = mb_done / max(elapsed, 0.001)
                print(f"  进度: {mb_done:.0f}/{total_mb:.0f} MB "
                      f"({speed:.0f} MB/s), "
                      f"{msg_count} msgs, "
                      f"{cognition_frames} cog frames...", end='\r')

        elapsed = _time.time() - t_start
        mb = reader._size / 1024 / 1024
        print(f"  完成: {msg_count} 消息, {cognition_frames} Cognition帧, "
              f"{motion_frames} Motion帧, 耗时 {elapsed:.1f}s "
              f"({mb / max(elapsed, 0.001):.0f} MB/s)          ")

        # 汇总统计
        stats = {
            'robot': self.settings.get('headName', '?'),
            'player': self.settings.get('playerNumber', 0),
            'log_file': self.filename,
            'log_size_mb': round(mb, 1),
            'total_messages': msg_count,
            'cognition_frames': cognition_frames,
            'motion_frames': motion_frames,
            'skill_counts': dict(skill_counts.most_common(20)),
            'behavior_counts': dict(behavior_counts.most_common(50)),
            'role_counts': dict(role_counts.most_common()),
            'position_counts': dict(position_counts.most_common()),
            'tactics': dict(tactic_counts.most_common()),
            'ball': {
                'team_ball_valid': team_ball_valid,
                'team_ball_invalid': team_ball_invalid,
                'local_ball_seen': local_ball_seen,
                'facing_ball': facing_ball,
                'back_to_ball': back_to_ball,
                'facing_rate': f"{facing_ball / max(team_ball_valid, 1) * 100:.1f}%",
                'back_rate': f"{back_to_ball / max(team_ball_valid, 1) * 100:.1f}%",
            },
            'obstacles': {
                'total': total_obstacles,
                'type_counts': dict(obs_type_counts.most_common()),
            },
            'communication': {
                'total_received': total_received_msgs,
                'total_unsync': total_unsync,
                'teammate_visibility': dict(teammate_counts.most_common()),
            },
            'opponents': {
                'unknown_distribution': dict(sorted(unknown_opp_counts.items())),
                'total_estimates': total_opp_estimates,
            },
            'stability': {
                'fall_state': dict(fall_state_counts.most_common()),
                'motion_phase': dict(motion_phase_counts.most_common()),
                'ground_contact_lost': ground_contact_lost,
                'ground_contact_total': ground_contact_total,
                'ground_contact_rate': f"{(1 - ground_contact_lost / max(ground_contact_total, 1)) * 100:.1f}%",
            },
            'game_state': {
                'state_counts': dict(game_state_counts.most_common()),
                'phase_counts': dict(game_phase_counts.most_common()),
            },
        }
        return stats


# ============================================================================
# 日志目录扫描
# ============================================================================

def find_log_files(log_dir):
    """
    查找日志目录中的二进制日志和文本日志。
    支持两种目录结构:
      1) log_dir/<date_dir>/<robot_dir>/*.log
      2) log_dir/<robot_dir>/*.log
    返回 dict: robot_name -> {'binary': [...], 'text': [...]}
    """
    result = {}
    log_dir = Path(log_dir)

    # 递归查找所有 .log 文件
    all_logs = sorted(log_dir.rglob('*.log'))

    for log_path in all_logs:
        fname = log_path.name
        robot_dir = log_path.parent.name
        is_text = 'bhumand' in fname

        if robot_dir not in result:
            result[robot_dir] = {'binary': [], 'text': []}

        if is_text:
            result[robot_dir]['text'].append(str(log_path))
        else:
            result[robot_dir]['binary'].append(str(log_path))

    return result


def parse_bhumand_log(filepath):
    """解析 bhumand 文本日志。"""
    events = []
    try:
        with open(filepath, 'r', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(line)
    except Exception as e:
        events.append(f"[读取错误: {e}]")
    return events


# ============================================================================
# Markdown 报告生成
# ============================================================================

def generate_report(all_stats, log_dir, text_logs_info, output_path):
    """生成 Markdown 分析报告。"""
    lines = []
    lines.append("# B-Human 比赛日志分析报告")
    lines.append("")
    lines.append(f"**日志目录**: `{log_dir}`")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**机器人数量**: {len(all_stats)}")
    lines.append("")

    # === 概览 ===
    lines.append("## 1. 概览")
    lines.append("")
    lines.append("| 机器人 | 球员号 | 日志文件 | 大小(MB) | Cognition帧 | Motion帧 | 主要角色 | 主要战术 |")
    lines.append("|--------|--------|----------|----------|-------------|----------|----------|----------|")
    for s in all_stats:
        role = max(s.get('role_counts', {'?': 0}), key=s.get('role_counts', {'?': 0}).get, default='?')
        tac = max(s.get('tactics', {'?': 0}), key=s.get('tactics', {'?': 0}).get, default='?')
        lines.append(f"| {s['robot']} | P{s['player']} | {s.get('log_file','')} | "
                     f"{s.get('log_size_mb',0)} | {s['cognition_frames']} | "
                     f"{s['motion_frames']} | {role} | {tac} |")
    lines.append("")

    # === 各机器人详细分析 ===
    for i, s in enumerate(all_stats):
        lines.append(f"## 2.{i+1} {s['robot']} (P{s['player']})")
        lines.append("")

        # -- 行为分析 --
        lines.append("### 行为分析")
        lines.append("")
        if s.get('skill_counts'):
            lines.append("**SkillRequest 分布:**")
            lines.append("")
            lines.append("| 技能 | 帧数 | 占比 |")
            lines.append("|------|------|------|")
            total_skill = sum(s['skill_counts'].values())
            for skill, cnt in s['skill_counts'].items():
                lines.append(f"| {skill} | {cnt} | {cnt/max(total_skill,1)*100:.1f}% |")
            lines.append("")

        if s.get('behavior_counts'):
            key_behaviors = [
                'PlayBall', 'Zweikampf', 'GoToBallAndKick', 'PassToTeammate',
                'ClearBall', 'KickAtGoal', 'HandleGoalkeeperCatchBall',
                'InterceptBall', 'ReceivePass', 'DribbleToGoal',
                'HandleBallAtOwnGoalPost', 'WalkToPoint', 'WalkToPose',
                'Stand', 'LookAtBall', 'PublishMotion',
            ]
            lines.append("**关键行为选项:**")
            lines.append("")
            lines.append("| 行为选项 | 帧数 |")
            lines.append("|----------|------|")
            for beh in key_behaviors:
                if beh in s['behavior_counts']:
                    lines.append(f"| {beh} | {s['behavior_counts'][beh]} |")
            for beh, cnt in list(s['behavior_counts'].items())[:20]:
                if beh not in key_behaviors:
                    lines.append(f"| {beh} | {cnt} |")
            lines.append("")

        # -- 角色与战术 --
        if s.get('role_counts'):
            lines.append("**角色分布:**")
            lines.append("")
            for role, cnt in s['role_counts'].items():
                lines.append(f"- **{role}**: {cnt} 帧")
            lines.append("")

        if s.get('tactics'):
            lines.append("**战术分布:**")
            lines.append("")
            for tac, cnt in s['tactics'].items():
                lines.append(f"- **{tac}**: {cnt} 帧")
            lines.append("")

        # -- 球感知 --
        ball = s.get('ball', {})
        if ball:
            lines.append("### 球感知")
            lines.append("")
            lines.append(f"- **TeamBall 有效帧**: {ball.get('team_ball_valid', 0)}")
            lines.append(f"- **TeamBall 无效帧**: {ball.get('team_ball_invalid', 0)}")
            lines.append(f"- **本机近期看到球**: {ball.get('local_ball_seen', 0)} 帧")
            lines.append(f"- **面朝球 (<90°)**: {ball.get('facing_ball', 0)} ({ball.get('facing_rate', '?')})")
            lines.append(f"- **背对球 (>120°)**: {ball.get('back_to_ball', 0)} ({ball.get('back_rate', '?')})")
            lines.append("")

        # -- 障碍物 --
        obs = s.get('obstacles', {})
        if obs and obs.get('total', 0) > 0:
            lines.append("### 障碍物识别（队友/对手分类）")
            lines.append("")
            lines.append(f"- **总检测次数**: {obs['total']}")
            tc = obs.get('type_counts', {})
            if tc:
                lines.append("")
                lines.append("| 类型 | 次数 | 占比 |")
                lines.append("|------|------|------|")
                total_obs = sum(tc.values())
                for otype, cnt in tc.items():
                    lines.append(f"| {otype} | {cnt} | {cnt/max(total_obs,1)*100:.1f}% |")
            lines.append("")

        # -- 通信 --
        comm = s.get('communication', {})
        if comm:
            lines.append("### 通信")
            lines.append("")
            lines.append(f"- **收到消息总数**: {comm.get('total_received', 0)}")
            lines.append(f"- **未同步消息**: {comm.get('total_unsync', 0)}")
            tv = comm.get('teammate_visibility', {})
            if tv:
                lines.append(f"- **队友可见性** (队友编号: 出现帧数): {tv}")
            lines.append("")

        # -- 对手 --
        opp = s.get('opponents', {})
        if opp:
            lines.append("### 对手追踪 (GlobalOpponentsModel)")
            lines.append("")
            ud = opp.get('unknown_distribution', {})
            if ud:
                lines.append("**未识别对手数分布:**")
                lines.append("")
                lines.append("| 未识别数 | 帧数 |")
                lines.append("|----------|------|")
                for k, v in sorted(ud.items()):
                    lines.append(f"| {k} | {v} |")
                lines.append("")
            lines.append(f"- **对手估计总数**: {opp.get('total_estimates', 0)}")
            lines.append("")

        # -- 稳定性 --
        stab = s.get('stability', {})
        if stab:
            lines.append("### 稳定性")
            lines.append("")
            fs = stab.get('fall_state', {})
            if fs:
                lines.append("**FallDownState 分布:**")
                lines.append("")
                for state, cnt in fs.items():
                    lines.append(f"- **{state}**: {cnt} 帧")
                lines.append("")
            mp = stab.get('motion_phase', {})
            if mp:
                lines.append("**MotionPhase 分布:**")
                lines.append("")
                for phase, cnt in mp.items():
                    lines.append(f"- **{phase}**: {cnt} 帧")
                lines.append("")
            lines.append(f"- **地面接触率**: {stab.get('ground_contact_rate', '?')} "
                        f"({stab.get('ground_contact_lost', 0)} 帧失联 / "
                        f"{stab.get('ground_contact_total', 0)} 总帧)")
            lines.append("")

        # -- 比赛状态 --
        gs = s.get('game_state', {})
        if gs and gs.get('state_counts'):
            lines.append("### 比赛状态")
            lines.append("")
            lines.append("| 状态 | 帧数 |")
            lines.append("|------|------|")
            for state, cnt in gs['state_counts'].items():
                lines.append(f"| {state} | {cnt} |")
            lines.append("")

    # === bhumand 文本日志 ===
    if text_logs_info:
        lines.append("## 3. bhumand 文本日志摘要")
        lines.append("")
        for robot, events in sorted(text_logs_info.items()):
            lines.append(f"### {robot}")
            lines.append("")
            key_events = [e for e in events if any(kw in e.lower() for kw in
                ['error', 'warning', 'logging', 'start', 'stop',
                 'caught', 'shutdown', 'camera', 'fallen', 'kick', 'goal'])]
            if key_events:
                for e in key_events[:30]:
                    lines.append(f"- `{e}`")
            else:
                lines.append(f"- 共 {len(events)} 条日志，无关键事件")
            lines.append("")

    # === 综合总结 ===
    lines.append("## 4. 综合总结")
    lines.append("")

    # 通信
    lines.append("### 通信状况")
    for s in all_stats:
        comm = s.get('communication', {})
        unsync = comm.get('total_unsync', 0)
        recv = comm.get('total_received', 0)
        status = "⚠️" if unsync > 100 else "✅"
        lines.append(f"- {status} **{s['robot']}(P{s['player']})**: "
                     f"收到 {recv} 条, 未同步 {unsync} 条")
    lines.append("")

    # 对手识别
    lines.append("### 对手识别")
    for s in all_stats:
        ud = s.get('opponents', {}).get('unknown_distribution', {})
        high_unknown = sum(v for k, v in ud.items() if isinstance(k, int) and k >= 4)
        total = sum(ud.values()) if ud else 1
        pct = high_unknown / max(total, 1) * 100
        status = "⚠️" if pct > 50 else "✅"
        lines.append(f"- {status} **{s['robot']}(P{s['player']})**: "
                     f"{pct:.0f}% 帧有 4+ 未识别对手")
    lines.append("")

    # 稳定性
    lines.append("### 稳定性")
    for s in all_stats:
        fs = s.get('stability', {}).get('fall_state', {})
        fallen = fs.get('fallen', 0) + fs.get('falling', 0)
        stagger = fs.get('staggering', 0)
        total = sum(fs.values()) if fs else 1
        pct = fallen / max(total, 1) * 100
        status = "⚠️" if pct > 2 else "✅"
        lines.append(f"- {status} **{s['robot']}(P{s['player']})**: "
                     f"跌倒 {fallen} 帧 ({pct:.1f}%), 踉跄 {stagger} 帧, "
                     f"地面接触率 {s.get('stability',{}).get('ground_contact_rate','?')}")
    lines.append("")

    # 守门员
    lines.append("### 守门员分析")
    for s in all_stats:
        if 'goalkeeper' in s.get('role_counts', {}) or 'goalkeeper' in s.get('position_counts', {}):
            beh = s.get('behavior_counts', {})
            ball = s.get('ball', {})
            lines.append(f"- **{s['robot']}(P{s['player']})** 为守门员:")
            lines.append(f"  - HandleGoalkeeperCatchBall: {beh.get('HandleGoalkeeperCatchBall', 0)} 帧")
            lines.append(f"  - InterceptBall: {beh.get('InterceptBall', 0)} 帧")
            lines.append(f"  - PlayBall: {beh.get('PlayBall', 0)} 帧")
            lines.append(f"  - 面朝球率: {ball.get('facing_rate', '?')}")
            lines.append(f"  - 背对球率: {ball.get('back_rate', '?')}")
    lines.append("")

    # 传球
    lines.append("### 传球分析")
    has_pass = False
    for s in all_stats:
        beh = s.get('behavior_counts', {})
        pass_frames = beh.get('PassToTeammate', 0)
        recv_pass = beh.get('ReceivePass', 0)
        if pass_frames > 0 or recv_pass > 0:
            has_pass = True
            lines.append(f"- **{s['robot']}(P{s['player']})**: "
                        f"发起传球 {pass_frames} 帧, 接收传球 {recv_pass} 帧")
    if not has_pass:
        lines.append("- 未检测到传球行为")
    lines.append("")

    # 写入
    report = '\n'.join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已保存: {output_path}")
    return report


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='B-Human 日志解析器')
    parser.add_argument('log_dir', help='日志目录路径')
    parser.add_argument('-o', '--output', default=None, help='输出 Markdown 报告路径')
    parser.add_argument('--json', default=None, help='输出 JSON 数据路径')
    parser.add_argument('--largest-only', action='store_true',
                       help='每个机器人只解析最大的日志文件')
    args = parser.parse_args()

    log_dir = os.path.abspath(args.log_dir)
    if not os.path.isdir(log_dir):
        print(f"错误: 目录不存在: {log_dir}")
        sys.exit(1)

    print(f"扫描日志目录: {log_dir}")
    robot_logs = find_log_files(log_dir)
    if not robot_logs:
        print("未找到日志文件!")
        sys.exit(1)

    print(f"找到 {len(robot_logs)} 个机器人的日志:")
    for robot, logs in sorted(robot_logs.items()):
        binary_sizes = [os.path.getsize(f) for f in logs['binary']]
        print(f"  {robot}: {len(logs['binary'])} 个二进制日志 "
              f"({sum(binary_sizes)/1024/1024:.0f} MB), "
              f"{len(logs['text'])} 个文本日志")

    all_stats = []
    text_logs_info = {}

    for robot, logs in sorted(robot_logs.items()):
        print(f"\n{'='*60}")
        print(f"机器人: {robot}")
        print(f"{'='*60}")

        binary_logs = logs['binary']
        if args.largest_only and binary_logs:
            binary_logs = [max(binary_logs, key=os.path.getsize)]
            print(f"  只解析最大日志: {os.path.basename(binary_logs[0])}")

        for log_path in binary_logs:
            try:
                log_file = BHumanLogFile(log_path)
                stats = log_file.parse()
                if stats:
                    all_stats.append(stats)
            except Exception as e:
                print(f"  解析失败: {os.path.basename(log_path)}: {e}")
                import traceback
                traceback.print_exc()

        all_events = []
        for text_path in logs['text']:
            events = parse_bhumand_log(text_path)
            all_events.extend(events)
        if all_events:
            text_logs_info[robot] = all_events

    if not all_stats:
        print("\n没有成功解析任何日志!")
        sys.exit(1)

    # 确定输出路径
    if args.output:
        output_path = args.output
    else:
        dir_name = os.path.basename(log_dir.rstrip('/'))
        output_path = os.path.join(log_dir, f'{dir_name}_analysis.md')

    generate_report(all_stats, log_dir, text_logs_info, output_path)

    if args.json:
        def make_serializable(obj):
            if isinstance(obj, dict):
                return {str(k): make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [make_serializable(i) for i in obj]
            elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                return str(obj)
            return obj

        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(make_serializable(all_stats), f, ensure_ascii=False, indent=2)
        print(f"JSON 数据已保存: {args.json}")

    print(f"\n分析完成! 共解析 {len(all_stats)} 个日志文件")


if __name__ == '__main__':
    main()
