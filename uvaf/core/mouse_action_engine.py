from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import math
import os
import random
import time
from typing import Callable

# Keep a private user32 wrapper for the actuator. ctypes function prototypes
# are mutable; sharing ctypes.windll.user32 between unrelated modules can make
# one module's argtypes reject another module's otherwise-compatible structs.
_USER32 = (
    ctypes.WinDLL(
        "user32",
        use_last_error=True,
    )
    if os.name == "nt"
    else None
)



@dataclass(frozen=True)
class MoveOptions:
    # Directional offsets are intentionally signed.
    # Final X = x + right - left; final Y = y + down - up.
    offset_up: float = 0.0
    offset_down: float = 0.0
    offset_left: float = 0.0
    offset_right: float = 0.0

    # "duration": speed_value is total seconds. 0 = teleport.
    # "pixels_per_second": speed_value is px/s.
    speed_mode: str = "duration"
    speed_value: float = 0.0

    # Random +/- deviation applied to duration or px/s for each movement.
    speed_variance: float = 0.0

    # Travel on a randomized smooth Bezier path instead of a straight line.
    random_route: bool = False


@dataclass(frozen=True)
class ClickOptions:
    count: int = 1

    # One click remains an explicit DOWN -> HOLD -> UP sequence so it is
    # semantically different from future standalone Press / Release modules.
    press_duration: float = 0.025
    interval: float = 0.100


class MouseActionEngine:
    """
    Low-level mouse actuator used by UVAF action modules.

    Design choices absorbed from automation frameworks such as MAA:
    - recognition and actuation are separate layers;
    - resolve the final coordinate before moving;
    - make DOWN and UP explicit instead of hiding them inside GUI helpers;
    - reassert the exact endpoint after interpolated movement;
    - allow configurable press duration / repeat interval;
    - every wait is cooperative so UVAF Stop can interrupt an action.

    Windows uses native user32 calls. PyAutoGUI is only a compatibility
    fallback on other platforms.
    """

    def __init__(self) -> None:
        self._pyautogui = None

        if os.name != "nt":
            try:
                import pyautogui  # type: ignore
                self._pyautogui = pyautogui
            except ImportError:
                self._pyautogui = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def position(self) -> tuple[int, int]:
        if os.name == "nt":
            if _USER32 is None:
                raise RuntimeError(
                    "Windows user32 后端不可用。"
                )

            point = wintypes.POINT()

            get_physical = getattr(
                _USER32,
                "GetPhysicalCursorPos",
                None,
            )

            if get_physical is not None:
                get_physical.argtypes = [
                    ctypes.POINTER(
                        wintypes.POINT
                    )
                ]
                get_physical.restype = (
                    wintypes.BOOL
                )

                if not get_physical(
                    ctypes.byref(
                        point
                    )
                ):
                    raise RuntimeError(
                        "无法读取物理鼠标坐标。"
                    )
            else:
                get_cursor = (
                    _USER32.GetCursorPos
                )
                get_cursor.argtypes = [
                    ctypes.POINTER(
                        wintypes.POINT
                    )
                ]
                get_cursor.restype = (
                    wintypes.BOOL
                )

                if not get_cursor(
                    ctypes.byref(
                        point
                    )
                ):
                    raise RuntimeError(
                        "无法读取当前鼠标坐标。"
                    )

            return (
                int(
                    point.x
                ),
                int(
                    point.y
                ),
            )

        if self._pyautogui is None:
            raise RuntimeError(
                "当前平台没有可用的鼠标执行后端。"
            )

        point = self._pyautogui.position()

        return (
            int(
                point.x
            ),
            int(
                point.y
            ),
        )

    def move_to(
        self,
        x: float,
        y: float,
        options: MoveOptions | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[int, int]:
        options = options or MoveOptions()
        stop_requested = stop_requested or (
            lambda: False
        )

        target_x, target_y = (
            self.resolve_target(
                x,
                y,
                options,
            )
        )

        if stop_requested():
            return self.position()

        start_x, start_y = self.position()

        path = self._build_path(
            start_x,
            start_y,
            target_x,
            target_y,
            random_route=options.random_route,
        )

        travel_distance = (
            self._polyline_length(path)
        )

        duration = self._resolve_duration(
            travel_distance,
            options,
        )

        if duration <= 0.0:
            self._set_position(
                target_x,
                target_y,
            )
            actual_x, actual_y = (
                self.position()
            )

            if (
                abs(actual_x - target_x) > 1
                or abs(actual_y - target_y) > 1
            ):
                self._set_position(
                    target_x,
                    target_y,
                )
                actual_x, actual_y = (
                    self.position()
                )

            return actual_x, actual_y

        # 120 Hz is enough to look smooth while keeping native calls cheap.
        steps = max(
            2,
            int(
                math.ceil(
                    duration * 120.0
                )
            ),
        )

        samples = self._sample_by_arc_length(
            path,
            steps,
        )

        start_time = time.perf_counter()

        for index, (px, py) in enumerate(
            samples[1:],
            start=1,
        ):
            if stop_requested():
                return self.position()

            target_time = (
                start_time
                + duration
                * index
                / (len(samples) - 1)
            )

            self._wait_until(
                target_time,
                stop_requested,
            )

            if stop_requested():
                return self.position()

            self._set_position(
                int(round(px)),
                int(round(py)),
            )

        # Endpoint verification/reassertion avoids interpolation rounding.
        # Read back PHYSICAL coordinates so DPI virtualization cannot hide a
        # mismatch between the recognition coordinate and the actual cursor.
        self._set_position(
            target_x,
            target_y,
        )

        actual_x, actual_y = self.position()

        if (
            abs(actual_x - target_x) > 1
            or abs(actual_y - target_y) > 1
        ):
            self._set_position(
                target_x,
                target_y,
            )
            actual_x, actual_y = (
                self.position()
            )

        return actual_x, actual_y

    def drag(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        options: MoveOptions | None = None,
        press_duration: float = 0.025,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[int, int]:
        """
        Move to start, press left mouse, travel to end, then release.

        Movement uses the same advanced movement model as Move To:
        offsets, duration / px-per-second, speed variance and randomized
        Bezier routes. Offsets are applied to the END point only.
        """
        options = options or MoveOptions()
        stop_requested = stop_requested or (lambda: False)

        if stop_requested():
            return self.position()

        # Start is always exact and immediate.
        self._set_position(
            int(round(start_x)),
            int(round(start_y)),
        )

        self._left_down()

        try:
            if not self._interruptible_sleep(
                max(0.0, float(press_duration)),
                stop_requested,
            ):
                return self.position()

            return self.move_to(
                end_x,
                end_y,
                options=options,
                stop_requested=stop_requested,
            )
        finally:
            self._left_up()

    @staticmethod
    def _normalize_button(button: str) -> str:
        value = str(button or "left").strip().lower()
        aliases = {
            "left": "left",
            "l": "left",
            "左": "left",
            "左键": "left",
            "right": "right",
            "r": "right",
            "右": "right",
            "右键": "right",
            "middle": "middle",
            "mid": "middle",
            "m": "middle",
            "中": "middle",
            "中键": "middle",
        }
        return aliases.get(value, "left")

    def press(
        self,
        button: str = "left",
        stop_requested: Callable[[], bool] | None = None,
    ) -> bool:
        stop_requested = stop_requested or (lambda: False)

        if stop_requested():
            return False

        self._button_down(self._normalize_button(button))
        return True

    def release(
        self,
        button: str = "left",
        stop_requested: Callable[[], bool] | None = None,
    ) -> bool:
        stop_requested = stop_requested or (lambda: False)

        if stop_requested():
            return False

        self._button_up(self._normalize_button(button))
        return True

    def release_all(self) -> None:
        """Best-effort emergency release used when UVAF Stop is pressed."""
        for button in ("left", "right", "middle"):
            try:
                self._button_up(button)
            except Exception:
                pass

    def press_left(
        self,
        stop_requested: Callable[[], bool] | None = None,
    ) -> bool:
        return self.press("left", stop_requested=stop_requested)

    def release_left(
        self,
        stop_requested: Callable[[], bool] | None = None,
    ) -> bool:
        return self.release("left", stop_requested=stop_requested)

    def click(
        self,
        options: ClickOptions | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        options = options or ClickOptions()
        stop_requested = stop_requested or (
            lambda: False
        )

        count = max(
            1,
            int(options.count),
        )
        press_duration = max(
            0.0,
            float(
                options.press_duration
            ),
        )
        interval = max(
            0.0,
            float(
                options.interval
            ),
        )

        completed = 0

        for index in range(count):
            if stop_requested():
                break

            self._left_down()

            try:
                if not self._interruptible_sleep(
                    press_duration,
                    stop_requested,
                ):
                    # Even when Stop occurs while pressed, release before exit.
                    return completed
            finally:
                self._left_up()

            completed += 1

            if index < count - 1:
                if not self._interruptible_sleep(
                    interval,
                    stop_requested,
                ):
                    break

        return completed

    # ------------------------------------------------------------------
    # Coordinate / timing
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_target(
        x: float,
        y: float,
        options: MoveOptions,
    ) -> tuple[int, int]:
        resolved_x = (
            float(x)
            + float(options.offset_right)
            - float(options.offset_left)
        )
        resolved_y = (
            float(y)
            + float(options.offset_down)
            - float(options.offset_up)
        )

        return (
            int(round(resolved_x)),
            int(round(resolved_y)),
        )

    @staticmethod
    def _resolve_duration(
        distance: float,
        options: MoveOptions,
    ) -> float:
        value = max(
            0.0,
            float(
                options.speed_value
            ),
        )
        variance = max(
            0.0,
            float(
                options.speed_variance
            ),
        )

        if options.speed_mode == "pixels_per_second":
            # A non-positive px/s has no meaningful finite travel time.
            if value <= 0.0:
                return 0.0

            actual_speed = max(
                1.0,
                value
                + random.uniform(
                    -variance,
                    variance,
                ),
            )

            return (
                distance
                / actual_speed
            )

        # duration mode: 0 explicitly means teleport.
        if value <= 0.0:
            return 0.0

        return max(
            0.0,
            value
            + random.uniform(
                -variance,
                variance,
            ),
        )

    # ------------------------------------------------------------------
    # Random-route geometry
    # ------------------------------------------------------------------
    @staticmethod
    def _build_path(
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        random_route: bool,
    ) -> list[
        tuple[float, float]
    ]:
        sx = float(start_x)
        sy = float(start_y)
        ex = float(end_x)
        ey = float(end_y)

        if not random_route:
            return [
                (sx, sy),
                (ex, ey),
            ]

        dx = ex - sx
        dy = ey - sy
        distance = math.hypot(
            dx,
            dy,
        )

        if distance < 2.0:
            return [
                (sx, sy),
                (ex, ey),
            ]

        # Unit normal to the direct route.
        nx = -dy / distance
        ny = dx / distance

        # Keep detours proportional but bounded. This makes the route visibly
        # non-linear without producing huge excursions on long movements.
        lateral_limit = min(
            180.0,
            max(
                18.0,
                distance * 0.22,
            ),
        )

        lateral_1 = random.uniform(
            -lateral_limit,
            lateral_limit,
        )
        lateral_2 = random.uniform(
            -lateral_limit,
            lateral_limit,
        )

        c1 = (
            sx
            + dx * random.uniform(
                0.18,
                0.38,
            )
            + nx * lateral_1,
            sy
            + dy * random.uniform(
                0.18,
                0.38,
            )
            + ny * lateral_1,
        )

        c2 = (
            sx
            + dx * random.uniform(
                0.62,
                0.82,
            )
            + nx * lateral_2,
            sy
            + dy * random.uniform(
                0.62,
                0.82,
            )
            + ny * lateral_2,
        )

        points = []

        # Dense polyline; later resampled by arc length for approximately
        # constant physical speed along the random route.
        for index in range(81):
            t = index / 80.0
            one_minus = 1.0 - t

            px = (
                one_minus ** 3 * sx
                + 3.0
                * one_minus ** 2
                * t
                * c1[0]
                + 3.0
                * one_minus
                * t ** 2
                * c2[0]
                + t ** 3 * ex
            )
            py = (
                one_minus ** 3 * sy
                + 3.0
                * one_minus ** 2
                * t
                * c1[1]
                + 3.0
                * one_minus
                * t ** 2
                * c2[1]
                + t ** 3 * ey
            )

            points.append(
                (px, py)
            )

        points[-1] = (
            ex,
            ey,
        )
        return points

    @staticmethod
    def _polyline_length(
        points: list[
            tuple[float, float]
        ],
    ) -> float:
        return sum(
            math.hypot(
                bx - ax,
                by - ay,
            )
            for (
                (ax, ay),
                (bx, by),
            )
            in zip(
                points,
                points[1:],
            )
        )

    @staticmethod
    def _sample_by_arc_length(
        points: list[
            tuple[float, float]
        ],
        steps: int,
    ) -> list[
        tuple[float, float]
    ]:
        if len(points) <= 2:
            ax, ay = points[0]
            bx, by = points[-1]

            return [
                (
                    ax
                    + (bx - ax)
                    * index
                    / steps,
                    ay
                    + (by - ay)
                    * index
                    / steps,
                )
                for index in range(
                    steps + 1
                )
            ]

        cumulative = [0.0]

        for (
            (ax, ay),
            (bx, by),
        ) in zip(
            points,
            points[1:],
        ):
            cumulative.append(
                cumulative[-1]
                + math.hypot(
                    bx - ax,
                    by - ay,
                )
            )

        total = cumulative[-1]

        if total <= 0.0:
            return [
                points[-1]
            ] * (steps + 1)

        result = []
        segment_index = 0

        for index in range(
            steps + 1
        ):
            wanted = (
                total
                * index
                / steps
            )

            while (
                segment_index
                < len(cumulative) - 2
                and cumulative[
                    segment_index + 1
                ] < wanted
            ):
                segment_index += 1

            before = cumulative[
                segment_index
            ]
            after = cumulative[
                segment_index + 1
            ]

            ratio = (
                0.0
                if after <= before
                else (
                    wanted - before
                )
                / (
                    after - before
                )
            )

            ax, ay = points[
                segment_index
            ]
            bx, by = points[
                segment_index + 1
            ]

            result.append(
                (
                    ax
                    + (bx - ax)
                    * ratio,
                    ay
                    + (by - ay)
                    * ratio,
                )
            )

        result[-1] = points[-1]
        return result

    # ------------------------------------------------------------------
    # Native input
    # ------------------------------------------------------------------
    @staticmethod
    def _set_position(
        x: int,
        y: int,
    ) -> None:
        if os.name == "nt":
            if _USER32 is None:
                raise RuntimeError(
                    "Windows user32 后端不可用。"
                )

            set_physical = getattr(
                _USER32,
                "SetPhysicalCursorPos",
                None,
            )

            if set_physical is not None:
                set_physical.argtypes = [
                    ctypes.c_int,
                    ctypes.c_int,
                ]
                set_physical.restype = (
                    wintypes.BOOL
                )

                if not set_physical(
                    int(x),
                    int(y),
                ):
                    raise RuntimeError(
                        "Windows SetPhysicalCursorPos 失败。"
                    )
            else:
                set_cursor = (
                    _USER32.SetCursorPos
                )
                set_cursor.argtypes = [
                    ctypes.c_int,
                    ctypes.c_int,
                ]
                set_cursor.restype = (
                    wintypes.BOOL
                )

                if not set_cursor(
                    int(x),
                    int(y),
                ):
                    raise RuntimeError(
                        "Windows SetCursorPos 失败。"
                    )

            return

        try:
            import pyautogui  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "当前平台没有可用的鼠标执行后端。"
            ) from exc

        pyautogui.moveTo(
            int(x),
            int(y),
            duration=0,
        )

    @staticmethod
    def _button_down(button: str) -> None:
        button = MouseActionEngine._normalize_button(button)
        if os.name == "nt":
            if _USER32 is None:
                raise RuntimeError(
                    "Windows user32 后端不可用。"
                )

            flags = {
                "left": 0x0002,    # MOUSEEVENTF_LEFTDOWN
                "right": 0x0008,   # MOUSEEVENTF_RIGHTDOWN
                "middle": 0x0020,  # MOUSEEVENTF_MIDDLEDOWN
            }
            _USER32.mouse_event(flags[button], 0, 0, 0, 0)
            return

        try:
            import pyautogui  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "当前平台没有可用的鼠标执行后端。"
            ) from exc

        pyautogui.mouseDown(button=button)

    @staticmethod
    def _button_up(button: str) -> None:
        button = MouseActionEngine._normalize_button(button)
        if os.name == "nt":
            if _USER32 is None:
                raise RuntimeError(
                    "Windows user32 后端不可用。"
                )

            flags = {
                "left": 0x0004,    # MOUSEEVENTF_LEFTUP
                "right": 0x0010,   # MOUSEEVENTF_RIGHTUP
                "middle": 0x0040,  # MOUSEEVENTF_MIDDLEUP
            }
            _USER32.mouse_event(flags[button], 0, 0, 0, 0)
            return

        try:
            import pyautogui  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "当前平台没有可用的鼠标执行后端。"
            ) from exc

        pyautogui.mouseUp(button=button)

    @staticmethod
    def _left_down() -> None:
        MouseActionEngine._button_down("left")

    @staticmethod
    def _left_up() -> None:
        MouseActionEngine._button_up("left")

    @staticmethod
    def _interruptible_sleep(
        seconds: float,
        stop_requested: Callable[[], bool],
    ) -> bool:
        end = (
            time.perf_counter()
            + max(
                0.0,
                float(seconds),
            )
        )

        while True:
            if stop_requested():
                return False

            remaining = (
                end
                - time.perf_counter()
            )

            if remaining <= 0.0:
                return True

            time.sleep(
                min(
                    remaining,
                    0.010,
                )
            )

    @staticmethod
    def _wait_until(
        target_time: float,
        stop_requested: Callable[[], bool],
    ) -> None:
        while True:
            if stop_requested():
                return

            remaining = (
                target_time
                - time.perf_counter()
            )

            if remaining <= 0.0:
                return

            time.sleep(
                min(
                    remaining,
                    0.004,
                )
            )
