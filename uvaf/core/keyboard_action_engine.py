from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
import random
import time
from typing import Callable


@dataclass(frozen=True)
class KeyboardOptions:
    mode: str = "press"  # press | hold
    count: int = 1
    interval: float = 0.0
    hold_duration: float = 0.050
    duration_variance: float = 0.0
    interval_variance: float = 0.0
    humanized: bool = False


class KeyboardActionEngine:
    # Practical post-input settling heuristic. Each visible BMP character
    # produces one UTF-16 code unit (and therefore one synthetic down/up
    # pair); supplementary characters such as emoji use two units.
    TEXT_SETTLE_PER_UTF16_UNIT_SECONDS = 0.002

    """
    UVAF keyboard actuator.

    Windows uses SendInput-style key events via keybd_event for broad
    compatibility. Humanized mode adds small bounded timing variation and a
    natural down/up cadence, but never changes the requested key itself.
    """

    def press_key(
        self,
        key_name: str,
        options: KeyboardOptions | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        options = options or KeyboardOptions()
        stop_requested = stop_requested or (lambda: False)

        vk = self._virtual_key(key_name)
        count = max(1, int(options.count))
        completed = 0

        for index in range(count):
            if stop_requested():
                break

            hold = (
                max(0.0, float(options.hold_duration))
                if options.mode == "hold"
                else 0.0
            )

            if options.humanized:
                hold += random.uniform(
                    -abs(float(options.duration_variance)),
                    abs(float(options.duration_variance)),
                )
                hold = max(0.0, hold)

            self._key_down(vk)
            try:
                if hold > 0:
                    if not self._sleep_interruptible(
                        hold,
                        stop_requested,
                    ):
                        return completed
            finally:
                self._key_up(vk)

            completed += 1

            if index < count - 1:
                interval = max(
                    0.0,
                    float(options.interval),
                )

                if options.humanized:
                    interval += random.uniform(
                        -abs(float(options.interval_variance)),
                        abs(float(options.interval_variance)),
                    )
                    interval = max(0.0, interval)

                if interval > 0:
                    if not self._sleep_interruptible(
                        interval,
                        stop_requested,
                    ):
                        break

        return completed

    @classmethod
    def recommended_text_settle_delay(
        cls,
        text_value: str,
    ) -> float:
        """
        Estimate how long the target application should be allowed to drain
        the Windows keyboard-message queue after Unicode text injection.

        2 ms per UTF-16 code unit is intentionally conservative enough for
        ordinary UI/game text fields without making short strings feel slow.
        This is a POST-input settling delay, not the character typing interval.
        """
        if not text_value:
            return 0.0

        try:
            units = (
                len(
                    text_value.encode(
                        "utf-16-le"
                    )
                )
                // 2
            )
        except UnicodeEncodeError:
            units = len(
                text_value
            )

        return (
            max(
                0,
                int(units),
            )
            * cls.TEXT_SETTLE_PER_UTF16_UNIT_SECONDS
        )

    def type_text(
        self,
        text_value: str,
        interval: float = 0.0,
        interval_variance: float = 0.0,
        humanized: bool = False,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        """
        Type arbitrary Unicode text on Windows using KEYEVENTF_UNICODE.

        One Unicode code unit is sent as key-down/key-up. Optional interval
        jitter is applied between characters in humanized mode.
        """
        stop_requested = stop_requested or (lambda: False)

        if os.name != "nt":
            raise RuntimeError(
                "当前文本输入后端仅实现 Windows。"
            )

        completed = 0

        for index, char in enumerate(text_value):
            if stop_requested():
                break

            codepoint = ord(char)

            # Windows KEYEVENTF_UNICODE uses UTF-16 code units.
            units = (
                char.encode("utf-16-le")
            )

            for unit_index in range(
                0,
                len(units),
                2,
            ):
                unit = int.from_bytes(
                    units[
                        unit_index:
                        unit_index + 2
                    ],
                    "little",
                )
                self._unicode_key(
                    unit,
                    key_up=False,
                )
                self._unicode_key(
                    unit,
                    key_up=True,
                )

            completed += 1

            if index < len(text_value) - 1:
                wait = max(
                    0.0,
                    float(interval),
                )

                if humanized:
                    wait += random.uniform(
                        -abs(
                            float(
                                interval_variance
                            )
                        ),
                        abs(
                            float(
                                interval_variance
                            )
                        ),
                    )
                    wait = max(
                        0.0,
                        wait,
                    )

                if wait > 0:
                    if not self._sleep_interruptible(
                        wait,
                        stop_requested,
                    ):
                        break

        return completed

    @staticmethod
    def _unicode_key(
        code_unit: int,
        key_up: bool,
    ) -> None:
        flags = 0x0004  # KEYEVENTF_UNICODE

        if key_up:
            flags |= 0x0002  # KEYEVENTF_KEYUP

        ctypes.windll.user32.keybd_event(
            0,
            int(code_unit),
            flags,
            0,
        )

    @staticmethod
    def _sleep_interruptible(
        seconds: float,
        stop_requested: Callable[[], bool],
    ) -> bool:
        end = time.perf_counter() + max(0.0, seconds)

        while True:
            if stop_requested():
                return False

            remaining = end - time.perf_counter()

            if remaining <= 0:
                return True

            time.sleep(
                min(
                    remaining,
                    0.010,
                )
            )

    @staticmethod
    def _virtual_key(
        key_name: str,
    ) -> int:
        key = key_name.strip().upper()

        aliases = {
            "SPACE": 0x20,
            "ENTER": 0x0D,
            "RETURN": 0x0D,
            "ESC": 0x1B,
            "ESCAPE": 0x1B,
            "TAB": 0x09,
            "BACKSPACE": 0x08,
            "DELETE": 0x2E,
            "INSERT": 0x2D,
            "HOME": 0x24,
            "END": 0x23,
            "PAGEUP": 0x21,
            "PAGEDOWN": 0x22,
            "LEFT": 0x25,
            "UP": 0x26,
            "RIGHT": 0x27,
            "DOWN": 0x28,
            "SHIFT": 0x10,
            "CTRL": 0x11,
            "CONTROL": 0x11,
            "ALT": 0x12,
            "CAPSLOCK": 0x14,
        }

        if key in aliases:
            return aliases[key]

        if len(key) == 1:
            char = key

            if "A" <= char <= "Z":
                return ord(char)

            if "0" <= char <= "9":
                return ord(char)

        if key.startswith("F") and key[1:].isdigit():
            number = int(key[1:])

            if 1 <= number <= 24:
                return 0x70 + number - 1

        if os.name == "nt":
            result = ctypes.windll.user32.VkKeyScanW(
                ord(key_name[0])
                if key_name
                else 0
            )
            if result != -1:
                return result & 0xFF

        raise ValueError(
            f"不支持的按键：{key_name}"
        )

    @staticmethod
    def _key_down(
        vk: int,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError(
                "当前键盘执行后端仅实现 Windows。"
            )

        ctypes.windll.user32.keybd_event(
            int(vk),
            0,
            0,
            0,
        )

    @staticmethod
    def _key_up(
        vk: int,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError(
                "当前键盘执行后端仅实现 Windows。"
            )

        ctypes.windll.user32.keybd_event(
            int(vk),
            0,
            0x0002,
            0,
        )
