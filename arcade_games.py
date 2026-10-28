import math
import random
import re
from collections import deque

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}

_DIR_WORDS = {
    "up": {"上", "往上", "向上", "上边", "上面", "up", "w", "u"},
    "down": {"下", "往下", "向下", "下边", "下面", "down", "s"},
    "left": {"左", "往左", "向左", "左边", "左面", "left", "a"},
    "right": {"右", "往右", "向右", "右边", "右面", "right", "d"},
}
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _clean(text):
    return re.sub(r"[^\u4e00-\u9fffa-z0-9]", "", (text or "").lower())


def parse_direction(text):
    t = _clean(text)
    if not t or len(t) > 6:
        return None
    for direction, words in _DIR_WORDS.items():
        if t in words:
            return direction
    return None


def parse_cell(text):
    """把观众发的坐标转成 0 为基础的 (行,列)，只接受 9x9 范围。"""
    s = (text or "").strip()
    if not s:
        return None
    s = re.sub(r"^(请|帮我|帮忙|给我)?(翻开|翻|点开|点|开)\s*", "", s).strip()
    m = re.search(r"第?\s*([0-9一二三四五六七八九])\s*行\s*第?\s*([0-9一二三四五六七八九])\s*列", s)
    if m:
        r = int(m.group(1)) if m.group(1).isdigit() else _CN_NUM[m.group(1)]
        c = int(m.group(2)) if m.group(2).isdigit() else _CN_NUM[m.group(2)]
        return (r - 1, c - 1) if 1 <= r <= 9 and 1 <= c <= 9 else None
    m = re.fullmatch(r"\s*([A-Ia-i])\s*[,，:：\-\s]?\s*([1-9])\s*", s)
    if m:
        return (ord(m.group(1).upper()) - ord("A"), int(m.group(2)) - 1)
    m = re.fullmatch(r"\s*([1-9])\s*[,，:：\-\s]?\s*([A-Ia-i])\s*", s)
    if m:
        return (int(m.group(1)) - 1, ord(m.group(2).upper()) - ord("A"))
    m = re.fullmatch(r"\s*([1-9])\s*[,，:：\-/、\s]\s*([1-9])\s*", s)
    if m:
        return (int(m.group(1)) - 1, int(m.group(2)) - 1)
    m = re.fullmatch(r"\s*([1-9])([1-9])\s*", s)
    if m:
        return (int(m.group(1)) - 1, int(m.group(2)) - 1)
    return None


def _flood_area(start, blocked, w, h):
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in DIRS.values():
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in blocked and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    return len(seen)


class SnakeGame:
    def __init__(self, w=20, h=20, seed=None):
        self.w, self.h = w, h
        self.rng = random.Random(seed)
        cx, cy = w // 2, h // 2
        self.snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.direction = "right"
        self.score = 0
        self.dead = False
        self.food = self._spawn()

    def _spawn(self):
        free = [(x, y) for y in range(self.h) for x in range(self.w) if (x, y) not in self.snake]
        return self.rng.choice(free) if free else None

    def step(self, direction=None):
        if self.dead:
            return {"dead": True, "eat": False}
        if direction in DIRS and direction != OPPOSITE[self.direction]:
            self.direction = direction
        dx, dy = DIRS[self.direction]
        head = (self.snake[0][0] + dx, self.snake[0][1] + dy)
        eat = head == self.food
        body = set(self.snake) if eat else set(self.snake[:-1])
        if not (0 <= head[0] < self.w and 0 <= head[1] < self.h) or head in body:
            self.dead = True
            return {"dead": True, "eat": False}
        self.snake.insert(0, head)
        if eat:
            self.score += 1
            self.food = self._spawn()
            return {"dead": False, "eat": True}
        self.snake.pop()
        return {"dead": False, "eat": False}

    def state(self):
        return {"type": "snake", "w": self.w, "h": self.h,
                "snake": [[x, y] for x, y in self.snake],
                "food": list(self.food) if self.food else None,
                "direction": self.direction, "score": self.score, "dead": self.dead}


def _bfs_direction(head, target, blocked, w, h):
    if target is None:
        return None
    prev = {head: None}
    q = deque([head])
    while q:
        cur = q.popleft()
        if cur == target:
            step = cur
            while prev[step] is not None and prev[step] != head:
                step = prev[step]
            for d, (dx, dy) in DIRS.items():
                if (head[0] + dx, head[1] + dy) == step:
                    return d
            return None
        for d, (dx, dy) in DIRS.items():
            nxt = (cur[0] + dx, cur[1] + dy)
            if 0 <= nxt[0] < w and 0 <= nxt[1] < h and nxt not in blocked and nxt not in prev:
                prev[nxt] = cur
                q.append(nxt)
    return None


def choose_snake_direction(game):
    if game.dead or not game.food:
        return game.direction
    blocked = set(game.snake[:-1])
    path_dir = _bfs_direction(game.snake[0], game.food, blocked, game.w, game.h)
    best = None
    for d, (dx, dy) in DIRS.items():
        if d == OPPOSITE[game.direction]:
            continue
        head = (game.snake[0][0] + dx, game.snake[0][1] + dy)
        if not (0 <= head[0] < game.w and 0 <= head[1] < game.h) or head in blocked:
            continue
        eat = head == game.food
        future = set(game.snake) if eat else set(game.snake[:-1])
        future.add(head)
        area = _flood_area(head, future, game.w, game.h)
        score = area * 10 + (100000 if d == path_dir else 0)
        if area >= len(game.snake) + 2:
            score += 500
        if best is None or score > best[0]:
            best = (score, d)
    return best[1] if best else game.direction


class MinesweeperGame:
    def __init__(self, size=9, mines=10, seed=None):
        self.size = size
        self.mines = max(5, min(int(mines), size * size - 10))
        self.rng = random.Random(seed)
        self.mine_set = set()
        self.revealed = set()
        self.nums = {}
        self.placed = False
        self.dead = False
        self.won = False
        self.last = None

    def _neighbors(self, r, c):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.size and 0 <= nc < self.size:
                    yield nr, nc

    def _place(self, safe_r, safe_c):
        forbidden = {(safe_r, safe_c), *self._neighbors(safe_r, safe_c)}
        free = [(r, c) for r in range(self.size) for c in range(self.size) if (r, c) not in forbidden]
        self.mine_set = set(self.rng.sample(free, min(self.mines, len(free))))
        self.placed = True

    def _count(self, r, c):
        return sum(1 for nb in self._neighbors(r, c) if nb in self.mine_set)

    def _cascade(self, r, c):
        stack = [(r, c)]
        opened = 0
        while stack:
            cur = stack.pop()
            if cur in self.revealed:
                continue
            self.revealed.add(cur)
            opened += 1
            n = self._count(*cur)
            self.nums[cur] = n
            if n == 0:
                for nb in self._neighbors(*cur):
                    if nb not in self.revealed and nb not in self.mine_set:
                        stack.append(nb)
        return opened

    def reveal(self, r, c):
        if self.dead or self.won or not (0 <= r < self.size and 0 <= c < self.size):
            return {"ok": False}
        if (r, c) in self.revealed:
            return {"ok": False}
        if not self.placed:
            self._place(r, c)
        self.last = (r, c)
        if (r, c) in self.mine_set:
            self.dead = True
            self.revealed.add((r, c))
            return {"ok": True, "mine": True, "dead": True, "won": False, "revealed": 0}
        opened = self._cascade(r, c)
        self.won = len(self.revealed) == self.size * self.size - self.mines
        return {"ok": True, "mine": False, "dead": False, "won": self.won, "revealed": opened}

    def ai_move(self):
        if self.dead or self.won:
            return None
        if not self.placed:
            return self.size // 2, self.size // 2
        known_mines = set()
        safe = set()
        changed = True
        while changed:
            changed = False
            for (r, c), n in list(self.nums.items()):
                unknown = [nb for nb in self._neighbors(r, c)
                           if nb not in self.revealed and nb not in known_mines]
                if not unknown:
                    continue
                known_adj = sum(1 for nb in self._neighbors(r, c) if nb in known_mines)
                if n == known_adj:
                    for cell in unknown:
                        if cell not in safe:
                            safe.add(cell)
                            changed = True
                elif n == known_adj + len(unknown):
                    for cell in unknown:
                        known_mines.add(cell)
                    changed = True
        if safe:
            return safe.pop()
        candidates = [(r, c) for r in range(self.size) for c in range(self.size)
                      if (r, c) not in self.revealed and (r, c) not in known_mines]
        if not candidates:
            return None

        def risk(cell):
            vals = []
            for nb in self._neighbors(*cell):
                n = self.nums.get(nb)
                if n is None:
                    continue
                unknown = [u for u in self._neighbors(*nb) if u not in self.revealed]
                known_adj = sum(1 for u in unknown if u in known_mines)
                if unknown:
                    vals.append(max(0, n - known_adj) / len(unknown))
            return max(vals) if vals else 0.0

        scores = [(risk(cell), cell) for cell in candidates]
        best = min(s for s, _ in scores)
        return self.rng.choice([cell for s, cell in scores if s <= best + 1e-9])

    def state(self):
        rows = []
        for r in range(self.size):
            row = []
            for c in range(self.size):
                if (r, c) in self.revealed:
                    if self.dead and (r, c) in self.mine_set:
                        row.append("boom" if self.last == (r, c) else "mine")
                    else:
                        row.append(self.nums.get((r, c), self._count(r, c)))
                else:
                    row.append(None)
            rows.append(row)
        if self.dead:
            for r, c in self.mine_set:
                if rows[r][c] is None:
                    rows[r][c] = "mine"
        return {"type": "minesweeper", "size": self.size, "cells": rows, "mines": self.mines,
                "last": list(self.last) if self.last else None, "dead": self.dead, "won": self.won,
                "left": self.size * self.size - self.mines - len(self.revealed)}


def _merge_line(values):
    vals = [v for v in values if v]
    out = []
    gain = 0
    i = 0
    while i < len(vals):
        if i + 1 < len(vals) and vals[i] == vals[i + 1]:
            merged = vals[i] * 2
            out.append(merged)
            gain += merged
            i += 2
        else:
            out.append(vals[i])
            i += 1
    return out + [0] * (4 - len(out)), gain


def _move_grid(grid, direction):
    new = [row[:] for row in grid]
    gain = 0
    if direction in ("left", "right"):
        for r in range(4):
            vals = new[r] if direction == "left" else list(reversed(new[r]))
            merged, g = _merge_line(vals)
            gain += g
            new[r] = merged if direction == "left" else list(reversed(merged))
    elif direction in ("up", "down"):
        for c in range(4):
            vals = [new[r][c] for r in range(4)]
            if direction == "down":
                vals.reverse()
            merged, g = _merge_line(vals)
            gain += g
            if direction == "down":
                merged.reverse()
            for r in range(4):
                new[r][c] = merged[r]
    return new, gain, new != grid


def _log(v):
    return math.log2(v) if v > 0 else 0.0


def _eval_grid(grid):
    empty = sum(1 for row in grid for v in row if v == 0)
    smooth = 0
    for r in range(4):
        for c in range(4):
            v = grid[r][c]
            if not v:
                continue
            if c + 1 < 4 and grid[r][c + 1]:
                smooth -= abs(_log(v) - _log(grid[r][c + 1]))
            if r + 1 < 4 and grid[r + 1][c]:
                smooth -= abs(_log(v) - _log(grid[r + 1][c]))
    mono = 0
    for line in list(grid) + [[grid[r][c] for r in range(4)] for c in range(4)]:
        inc = sum(max(0, _log(line[i + 1]) - _log(line[i])) for i in range(3))
        dec = sum(max(0, _log(line[i]) - _log(line[i + 1])) for i in range(3))
        mono -= min(inc, dec)
    top = max(max(row) for row in grid)
    corner = top if top in (grid[0][0], grid[0][3], grid[3][0], grid[3][3]) else 0
    return empty * 270 + smooth * 8 + mono * 4 + corner * 2


class Game2048:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.grid = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.highest = 0
        self.over = False
        self._spawn()
        self._spawn()

    def _spawn(self):
        free = [(r, c) for r in range(4) for c in range(4) if self.grid[r][c] == 0]
        if not free:
            return
        r, c = self.rng.choice(free)
        self.grid[r][c] = 4 if self.rng.random() < 0.1 else 2
        self.highest = max(self.highest, self.grid[r][c])

    def _has_moves(self):
        if any(v == 0 for row in self.grid for v in row):
            return True
        return any(self.grid[r][c] == self.grid[r][c + 1] for r in range(4) for c in range(3)) or \
            any(self.grid[r][c] == self.grid[r + 1][c] for r in range(3) for c in range(4))

    def move(self, direction):
        if self.over or direction not in DIRS:
            return {"moved": False, "gain": 0, "over": self.over, "highest": self.highest}
        new, gain, moved = _move_grid(self.grid, direction)
        if not moved:
            return {"moved": False, "gain": 0, "over": self.over, "highest": self.highest}
        self.grid = new
        self.score += gain
        self._spawn()
        self.highest = max(self.highest, max(max(row) for row in self.grid))
        self.over = not self._has_moves()
        return {"moved": True, "gain": gain, "over": self.over, "highest": self.highest}

    def ai_move(self):
        best = None
        for d in DIRS:
            new, gain, moved = _move_grid(self.grid, d)
            if not moved:
                continue
            score = _eval_grid(new) + gain * 2
            if best is None or score > best[0]:
                best = (score, d)
        return best[1] if best else None

    def state(self):
        return {"type": "2048", "grid": [row[:] for row in self.grid], "score": self.score,
                "highest": self.highest, "over": self.over}
