from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import statistics
import threading
import time
from typing import Iterable

import cv2
import mss
import numpy as np


DEFAULT_METHODS = (
    "ccoeff_color",
    "grayscale",
    "rgb_count",
    "hsv_count",
    "edge",
    "feature",
)


@dataclass(frozen=True)
class RecognitionResult:
    """
    Template hit with explicit coordinate spaces.

    global_x/global_y are absolute virtual-desktop coordinates and are the
    only coordinates allowed to leave the recognition layer.

    local_x/local_y are relative to the captured image/ROI and exist only for
    diagnostics. x/y remain compatibility aliases to the GLOBAL coordinates.
    """
    global_x: int
    global_y: int
    score: float
    method: str
    scale: float = 1.0
    elapsed_ms: float = 0.0
    local_x: int = 0
    local_y: int = 0
    capture_origin_x: int = 0
    capture_origin_y: int = 0

    @property
    def x(self) -> int:
        return self.global_x

    @property
    def y(self) -> int:
        return self.global_y


@dataclass
class TemplateScanOptions:
    threshold: float = 0.860
    methods: tuple[str, ...] = DEFAULT_METHODS
    scales: tuple[float, ...] = (1.0,)
    feature_detector: str = "SIFT"
    feature_ratio: float = 0.60
    confirm_frames: int = 1
    confirm_tolerance_px: int = 8
    mask_path: str | None = None


class CaptureBackend:
    backend_id = "base"
    display_name = "Base"

    def capture(
        self,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        raise NotImplementedError


class MSSCaptureBackend(CaptureBackend):
    backend_id = "mss"
    display_name = "MSS"

    def capture(
        self,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        with mss.mss() as capture:
            if roi is None:
                monitor = dict(capture.monitors[0])
            else:
                x, y, width, height = roi
                monitor = {
                    "left": int(x),
                    "top": int(y),
                    "width": int(width),
                    "height": int(height),
                }

            frame = np.asarray(
                capture.grab(monitor)
            )

        image = cv2.cvtColor(
            frame,
            cv2.COLOR_BGRA2BGR,
        )

        return (
            image,
            int(monitor["left"]),
            int(monitor["top"]),
        )


class DXCamCaptureBackend(CaptureBackend):
    backend_id = "dxcam"
    display_name = "DXCam"

    def __init__(self) -> None:
        try:
            import dxcam  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "DXCam 未安装。"
            ) from exc

        self._dxcam = dxcam
        self._camera = dxcam.create(
            output_color="BGR"
        )

    def _clamp_roi(
        self,
        roi: tuple[int, int, int, int],
    ) -> tuple[
        tuple[int, int, int, int],
        int,
        int,
    ]:
        """
        DXCam requires 0 <= left < right <= camera.width and likewise for Y.

        UVAF stores ROI as (x, y, width, height). Clamp it to the selected
        DXCam output before calling grab() so an anchor near a screen edge can
        never generate an Invalid Region exception.
        """
        x, y, width, height = (
            int(value)
            for value in roi
        )

        if width <= 0 or height <= 0:
            raise RuntimeError(
                "ROI 的宽度和高度必须大于 0。"
            )

        camera_width = int(
            self._camera.width
        )
        camera_height = int(
            self._camera.height
        )

        requested_left = x
        requested_top = y
        requested_right = x + width
        requested_bottom = y + height

        left = max(
            0,
            requested_left,
        )
        top = max(
            0,
            requested_top,
        )
        right = min(
            camera_width,
            requested_right,
        )
        bottom = min(
            camera_height,
            requested_bottom,
        )

        if (
            right <= left
            or bottom <= top
        ):
            raise RuntimeError(
                (
                    "ROI 完全位于 DXCam 当前显示器之外："
                    f"请求=({requested_left}, {requested_top}, "
                    f"{width}, {height})，"
                    f"显示器={camera_width}x{camera_height}"
                )
            )

        return (
            (
                left,
                top,
                right,
                bottom,
            ),
            left,
            top,
        )

    def capture(
        self,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        left = 0
        top = 0
        region = None

        if roi is not None:
            region, left, top = (
                self._clamp_roi(
                    roi
                )
            )

        try:
            frame = self._camera.grab(
                region=region
            )
        except Exception as exc:
            # DXCam can still reject a region during display-mode changes.
            # Fall back to MSS instead of letting the recognition worker die.
            try:
                return (
                    MSSCaptureBackend()
                    .capture(
                        (
                            left,
                            top,
                            region[2] - region[0],
                            region[3] - region[1],
                        )
                        if region is not None
                        else None
                    )
                )
            except Exception:
                raise RuntimeError(
                    f"DXCam 截图失败：{exc}"
                ) from exc

        if frame is None:
            try:
                frame = self._camera.grab(
                    region=region,
                    new_frame_only=False,
                )
            except TypeError:
                frame = None
            except Exception:
                frame = None

        if frame is None:
            return (
                MSSCaptureBackend()
                .capture(
                    (
                        left,
                        top,
                        region[2] - region[0],
                        region[3] - region[1],
                    )
                    if region is not None
                    else None
                )
            )

        return (
            np.asarray(frame),
            left,
            top,
        )


class PyAutoGUICaptureBackend(CaptureBackend):
    backend_id = "pyautogui"
    display_name = "PyAutoGUI"

    def __init__(self) -> None:
        try:
            import pyautogui  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "PyAutoGUI 未安装。"
            ) from exc

        self._pyautogui = pyautogui

    def capture(
        self,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        if roi is None:
            screenshot = (
                self._pyautogui.screenshot()
            )
            left = 0
            top = 0
        else:
            x, y, width, height = roi
            screenshot = (
                self._pyautogui.screenshot(
                    region=(
                        int(x),
                        int(y),
                        int(width),
                        int(height),
                    )
                )
            )
            left = int(x)
            top = int(y)

        rgb = np.asarray(screenshot)
        bgr = cv2.cvtColor(
            rgb,
            cv2.COLOR_RGB2BGR,
        )

        return bgr, left, top


class NativeCaptureBackend(CaptureBackend):
    """UVAF recommended backend: DXCam first, MSS fallback."""

    backend_id = "native"
    display_name = "UVAF Native"

    def __init__(self) -> None:
        try:
            self._backend: CaptureBackend = (
                DXCamCaptureBackend()
            )
        except Exception:
            self._backend = (
                MSSCaptureBackend()
            )

    @property
    def active_backend_id(self) -> str:
        return self._backend.backend_id

    def capture(
        self,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        return self._backend.capture(roi)


class RecognitionEngine:
    """
    UVAF Recognition Engine.

    MAA-inspired architecture:
    - ROI-first capture
    - decoded template cache
    - optional mask
    - multiple template matching representations
    - feature matching using several detector families
    - multi-scale evaluation
    - optional continuous-frame confirmation
    - benchmark helper
    """

    def __init__(
        self,
        backend: str = "native",
        max_fps: int = 60,
    ) -> None:
        self._template_cache: dict[
            tuple[str, int],
            np.ndarray,
        ] = {}
        self._mask_cache: dict[
            tuple[str, int],
            np.ndarray,
        ] = {}

        self.backend_name = ""
        self.backend: CaptureBackend

        # Recognition remains demand-driven. max_fps is only the upper
        # limit for acquiring fresh frames across all workflow threads.
        self.max_fps = 60
        self._capture_interval = 1.0 / 60.0
        self._capture_lock = threading.Lock()
        self._backend_capture_lock = threading.Lock()
        self._last_capture_time = 0.0

        self.set_max_fps(max_fps)
        self.set_backend(backend)

    def set_max_fps(
        self,
        fps: int,
    ) -> None:
        fps = max(
            1,
            min(
                240,
                int(fps),
            ),
        )

        with self._capture_lock:
            self.max_fps = fps
            self._capture_interval = (
                1.0 / float(fps)
            )

    def _wait_for_capture_slot(
        self,
    ) -> None:
        with self._capture_lock:
            now = time.perf_counter()
            elapsed = (
                now
                - self._last_capture_time
            )
            remaining = (
                self._capture_interval
                - elapsed
            )

            if remaining > 0:
                time.sleep(remaining)

            self._last_capture_time = (
                time.perf_counter()
            )

    def capture(
        self,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[np.ndarray, int, int]:
        """
        Thread-safe fresh-frame acquisition.

        Multiple workflows and the recognition-view window may request frames
        concurrently. The backend itself (especially DXCam) is serialized,
        while the global FPS limiter still controls total fresh-frame rate.
        """
        self._wait_for_capture_slot()

        with self._backend_capture_lock:
            return self.backend.capture(roi)

    def set_backend(
        self,
        backend: str,
    ) -> None:
        backend = str(
            backend or "native"
        ).lower()

        if backend == "mss":
            instance: CaptureBackend = (
                MSSCaptureBackend()
            )
        elif backend == "pyautogui":
            instance = (
                PyAutoGUICaptureBackend()
            )
        else:
            instance = (
                NativeCaptureBackend()
            )
            backend = "native"

        self.backend_name = backend
        self.backend = instance

    def _load_cached_image(
        self,
        path_value: str,
        cache: dict[
            tuple[str, int],
            np.ndarray,
        ],
        flags: int,
    ) -> np.ndarray:
        path = Path(path_value)

        try:
            stamp = (
                path.stat().st_mtime_ns
            )
        except OSError:
            stamp = 0

        resolved = str(
            path.resolve()
        )
        key = (
            resolved,
            stamp,
        )

        cached = cache.get(key)

        if cached is not None:
            return cached

        image = cv2.imread(
            resolved,
            flags,
        )

        if image is None:
            raise RuntimeError(
                f"无法读取图像：{path_value}"
            )

        stale = [
            old_key
            for old_key in cache
            if old_key[0] == resolved
            and old_key != key
        ]

        for old_key in stale:
            cache.pop(
                old_key,
                None,
            )

        cache[key] = image
        return image

    def load_template(
        self,
        path_value: str,
    ) -> np.ndarray:
        return self._load_cached_image(
            path_value,
            self._template_cache,
            cv2.IMREAD_COLOR,
        )

    def load_mask(
        self,
        path_value: str,
    ) -> np.ndarray:
        return self._load_cached_image(
            path_value,
            self._mask_cache,
            cv2.IMREAD_GRAYSCALE,
        )

    @staticmethod
    def _resize_template(
        template: np.ndarray,
        scale: float,
    ) -> np.ndarray:
        if abs(scale - 1.0) < 1e-6:
            return template

        width = max(
            1,
            int(
                round(
                    template.shape[1]
                    * scale
                )
            ),
        )
        height = max(
            1,
            int(
                round(
                    template.shape[0]
                    * scale
                )
            ),
        )

        interpolation = (
            cv2.INTER_AREA
            if scale < 1.0
            else cv2.INTER_CUBIC
        )

        return cv2.resize(
            template,
            (width, height),
            interpolation=interpolation,
        )

    @staticmethod
    def _match_ccoeff(
        screen: np.ndarray,
        template: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> tuple[
        tuple[int, int],
        float,
    ]:
        # CCOEFF_NORMED does not reliably accept masks on all OpenCV builds.
        # When a mask is supplied, use CCORR_NORMED for the masked path.
        if mask is not None:
            result = cv2.matchTemplate(
                screen,
                template,
                cv2.TM_CCORR_NORMED,
                mask=mask,
            )
        else:
            result = cv2.matchTemplate(
                screen,
                template,
                cv2.TM_CCOEFF_NORMED,
            )

        _min_val, max_val, _min_loc, max_loc = (
            cv2.minMaxLoc(result)
        )
        return max_loc, float(max_val)

    @staticmethod
    def _match_grayscale(
        screen: np.ndarray,
        template: np.ndarray,
    ) -> tuple[
        tuple[int, int],
        float,
    ]:
        screen_gray = cv2.cvtColor(
            screen,
            cv2.COLOR_BGR2GRAY,
        )
        template_gray = cv2.cvtColor(
            template,
            cv2.COLOR_BGR2GRAY,
        )

        return RecognitionEngine._match_ccoeff(
            screen_gray,
            template_gray,
        )

    @staticmethod
    def _top_candidates(
        score_map: np.ndarray,
        count: int = 12,
    ) -> list[
        tuple[int, int, float]
    ]:
        flat = score_map.reshape(-1)

        if flat.size == 0:
            return []

        count = min(
            count,
            flat.size,
        )

        indices = np.argpartition(
            flat,
            -count,
        )[-count:]

        width = score_map.shape[1]

        candidates = []

        for index in indices:
            y = int(
                index // width
            )
            x = int(
                index % width
            )
            candidates.append(
                (
                    x,
                    y,
                    float(
                        score_map[
                            y,
                            x,
                        ]
                    ),
                )
            )

        candidates.sort(
            key=lambda item: item[2],
            reverse=True,
        )
        return candidates

    @staticmethod
    def _color_agreement(
        template: np.ndarray,
        region: np.ndarray,
        mode: str,
    ) -> float:
        if template.shape != region.shape:
            return 0.0

        if mode == "rgb_count":
            diff = cv2.absdiff(
                template,
                region,
            )
            mask = (
                np.max(
                    diff,
                    axis=2,
                )
                <= 32
            )
            return float(
                mask.mean()
            )

        template_hsv = cv2.cvtColor(
            template,
            cv2.COLOR_BGR2HSV,
        )
        region_hsv = cv2.cvtColor(
            region,
            cv2.COLOR_BGR2HSV,
        )

        hue_a = (
            template_hsv[
                :,
                :,
                0,
            ].astype(
                np.int16
            )
        )
        hue_b = (
            region_hsv[
                :,
                :,
                0,
            ].astype(
                np.int16
            )
        )

        hue_diff = np.abs(
            hue_a - hue_b
        )
        hue_diff = np.minimum(
            hue_diff,
            180 - hue_diff,
        )

        sat_diff = np.abs(
            template_hsv[
                :,
                :,
                1,
            ].astype(
                np.int16
            )
            - region_hsv[
                :,
                :,
                1,
            ].astype(
                np.int16
            )
        )

        val_diff = np.abs(
            template_hsv[
                :,
                :,
                2,
            ].astype(
                np.int16
            )
            - region_hsv[
                :,
                :,
                2,
            ].astype(
                np.int16
            )
        )

        mask = (
            (hue_diff <= 10)
            & (sat_diff <= 55)
            & (val_diff <= 55)
        )

        return float(
            mask.mean()
        )

    @staticmethod
    def _match_color_count(
        screen: np.ndarray,
        template: np.ndarray,
        mode: str,
    ) -> tuple[
        tuple[int, int],
        float,
    ]:
        base_map = cv2.matchTemplate(
            screen,
            template,
            cv2.TM_CCOEFF_NORMED,
        )

        candidates = (
            RecognitionEngine._top_candidates(
                base_map,
                12,
            )
        )

        best_loc = (
            0,
            0,
        )
        best_score = -1.0

        h, w = template.shape[:2]

        for x, y, shape_score in candidates:
            region = screen[
                y:y + h,
                x:x + w,
            ]

            color_score = (
                RecognitionEngine._color_agreement(
                    template,
                    region,
                    mode,
                )
            )

            score = (
                shape_score * 0.50
                + color_score * 0.50
            )

            if score > best_score:
                best_score = score
                best_loc = (
                    x,
                    y,
                )

        return (
            best_loc,
            float(best_score),
        )

    @staticmethod
    def _match_edge(
        screen: np.ndarray,
        template: np.ndarray,
    ) -> tuple[
        tuple[int, int],
        float,
    ]:
        screen_gray = cv2.cvtColor(
            screen,
            cv2.COLOR_BGR2GRAY,
        )
        template_gray = cv2.cvtColor(
            template,
            cv2.COLOR_BGR2GRAY,
        )

        screen_edge = cv2.Canny(
            screen_gray,
            70,
            160,
        )
        template_edge = cv2.Canny(
            template_gray,
            70,
            160,
        )

        edge_ratio = float(
            np.count_nonzero(template_edge)
        ) / float(
            max(1, template_edge.size)
        )
        edge_variance = float(
            np.var(template_edge)
        )

        # Reject edge-degenerate templates. Without this, a nearly blank edge
        # image can produce a false 1.000 match at arbitrary positions.
        if (
            edge_ratio < 0.008
            or edge_ratio > 0.65
            or edge_variance < 80.0
        ):
            return (0, 0), -1.0

        return RecognitionEngine._match_ccoeff(
            screen_edge,
            template_edge,
        )

    @staticmethod
    def _feature_detector(
        detector_name: str,
    ):
        name = (
            detector_name
            .strip()
            .upper()
        )

        if name == "KAZE":
            return (
                cv2.KAZE_create(),
                cv2.NORM_L2,
            )

        if name == "AKAZE":
            return (
                cv2.AKAZE_create(),
                cv2.NORM_HAMMING,
            )

        if name == "BRISK":
            return (
                cv2.BRISK_create(),
                cv2.NORM_HAMMING,
            )

        if name == "ORB":
            return (
                cv2.ORB_create(
                    nfeatures=1600
                ),
                cv2.NORM_HAMMING,
            )

        if hasattr(
            cv2,
            "SIFT_create",
        ):
            return (
                cv2.SIFT_create(),
                cv2.NORM_L2,
            )

        return (
            cv2.AKAZE_create(),
            cv2.NORM_HAMMING,
        )

    @staticmethod
    def _match_feature(
        screen: np.ndarray,
        template: np.ndarray,
        detector_name: str,
        ratio: float,
    ) -> tuple[
        tuple[int, int],
        float,
    ] | None:
        detector, norm = (
            RecognitionEngine._feature_detector(
                detector_name
            )
        )

        template_gray = cv2.cvtColor(
            template,
            cv2.COLOR_BGR2GRAY,
        )
        screen_gray = cv2.cvtColor(
            screen,
            cv2.COLOR_BGR2GRAY,
        )

        kp1, des1 = (
            detector.detectAndCompute(
                template_gray,
                None,
            )
        )
        kp2, des2 = (
            detector.detectAndCompute(
                screen_gray,
                None,
            )
        )

        if (
            des1 is None
            or des2 is None
            or len(kp1) < 4
            or len(kp2) < 4
        ):
            return None

        matcher = cv2.BFMatcher(
            norm
        )

        pairs = matcher.knnMatch(
            des1,
            des2,
            k=2,
        )

        good = [
            first
            for first, second in pairs
            if first.distance
            < float(ratio)
            * second.distance
        ]

        if len(good) < 4:
            return None

        source_points = np.float32(
            [
                kp1[
                    match.queryIdx
                ].pt
                for match in good
            ]
        ).reshape(
            -1,
            1,
            2,
        )

        target_points = np.float32(
            [
                kp2[
                    match.trainIdx
                ].pt
                for match in good
            ]
        ).reshape(
            -1,
            1,
            2,
        )

        matrix, inliers = (
            cv2.findHomography(
                source_points,
                target_points,
                cv2.RANSAC,
                4.0,
            )
        )

        if (
            matrix is None
            or inliers is None
        ):
            return None

        h, w = template.shape[:2]

        center = np.float32(
            [
                [
                    [
                        w / 2.0,
                        h / 2.0,
                    ]
                ]
            ]
        )

        transformed = (
            cv2.perspectiveTransform(
                center,
                matrix,
            )
        )[0][0]

        inlier_ratio = float(
            inliers.ravel().mean()
        )

        match_ratio = min(
            1.0,
            len(good)
            / max(
                1,
                len(kp1),
            ),
        )

        score = (
            inlier_ratio * 0.70
            + match_ratio * 0.30
        )

        x = int(
            round(
                transformed[0]
                - w / 2.0
            )
        )
        y = int(
            round(
                transformed[1]
                - h / 2.0
            )
        )

        return (
            (
                x,
                y,
            ),
            score,
        )

    def _scan_frame(
        self,
        screen: np.ndarray,
        origin_x: int,
        origin_y: int,
        template: np.ndarray,
        options: TemplateScanOptions,
    ) -> RecognitionResult | None:
        candidates: list[RecognitionResult] = []

        mask_original = None
        if options.mask_path:
            mask_original = self.load_mask(
                options.mask_path
            )

        for scale in options.scales:
            scaled = self._resize_template(
                template,
                float(scale),
            )
            h, w = scaled.shape[:2]

            if (
                h > screen.shape[0]
                or w > screen.shape[1]
            ):
                continue

            scaled_mask = None
            if mask_original is not None:
                scaled_mask = cv2.resize(
                    mask_original,
                    (w, h),
                    interpolation=cv2.INTER_NEAREST,
                )

            for method in options.methods:
                loc = None
                score = -1.0

                if method == "ccoeff_color":
                    loc, score = self._match_ccoeff(
                        screen,
                        scaled,
                        scaled_mask,
                    )
                elif method == "grayscale":
                    loc, score = self._match_grayscale(
                        screen,
                        scaled,
                    )
                elif method in (
                    "rgb_count",
                    "hsv_count",
                ):
                    loc, score = self._match_color_count(
                        screen,
                        scaled,
                        method,
                    )
                elif method == "edge":
                    loc, score = self._match_edge(
                        screen,
                        scaled,
                    )
                elif method == "feature":
                    feature = self._match_feature(
                        screen,
                        scaled,
                        options.feature_detector,
                        options.feature_ratio,
                    )
                    if feature is not None:
                        loc, score = feature

                if (
                    loc is None
                    or not np.isfinite(score)
                    or score < options.threshold
                ):
                    continue

                local_x = int(loc[0]) + w // 2
                local_y = int(loc[1]) + h // 2

                candidates.append(
                    RecognitionResult(
                        global_x=int(origin_x) + local_x,
                        global_y=int(origin_y) + local_y,
                        score=float(score),
                        method=method,
                        scale=float(scale),
                        local_x=local_x,
                        local_y=local_y,
                        capture_origin_x=int(origin_x),
                        capture_origin_y=int(origin_y),
                    )
                )

        if not candidates:
            return None

        radius = max(
            6.0,
            min(
                22.0,
                min(template.shape[:2]) * 0.12,
            ),
        )

        method_weight = {
            "ccoeff_color": 1.00,
            "grayscale": 0.96,
            "rgb_count": 1.00,
            "hsv_count": 1.00,
            "edge": 0.82,
            "feature": 0.88,
        }

        best = candidates[0]
        best_rank = (-1, -1.0, -1.0)

        for candidate in candidates:
            nearby = [
                other
                for other in candidates
                if math.hypot(
                    other.global_x - candidate.global_x,
                    other.global_y - candidate.global_y,
                ) <= radius
            ]
            method_count = len(
                {other.method for other in nearby}
            )
            weighted_mean = sum(
                other.score
                * method_weight.get(other.method, 0.90)
                for other in nearby
            ) / max(1, len(nearby))
            rank = (
                method_count,
                weighted_mean,
                candidate.score
                * method_weight.get(candidate.method, 0.90),
            )
            if rank > best_rank:
                best_rank = rank
                best = candidate

        supporters = [
            other
            for other in candidates
            if math.hypot(
                other.global_x - best.global_x,
                other.global_y - best.global_y,
            ) <= radius
        ]

        if len(supporters) <= 1:
            return best

        weights = [
            max(
                0.001,
                other.score
                * method_weight.get(other.method, 0.90),
            )
            for other in supporters
        ]
        total = sum(weights)

        global_x = int(
            round(
                sum(
                    item.global_x * weight
                    for item, weight
                    in zip(supporters, weights)
                ) / total
            )
        )
        global_y = int(
            round(
                sum(
                    item.global_y * weight
                    for item, weight
                    in zip(supporters, weights)
                ) / total
            )
        )

        methods = sorted(
            {item.method for item in supporters}
        )

        return RecognitionResult(
            global_x=global_x,
            global_y=global_y,
            score=max(item.score for item in supporters),
            method="consensus:" + "+".join(methods),
            scale=best.scale,
            local_x=global_x - int(origin_x),
            local_y=global_y - int(origin_y),
            capture_origin_x=int(origin_x),
            capture_origin_y=int(origin_y),
        )

    @staticmethod
    def _local_maxima_from_map(
        score_map: np.ndarray,
        threshold: float,
        radius_x: int,
        radius_y: int,
        max_candidates: int = 1000,
    ) -> list[tuple[int, int, float]]:
        """
        Extract local maxima efficiently.

        cv2.dilate performs the neighborhood maximum test in C, avoiding a
        potentially enormous Python sort when a broad/flat score map contains
        hundreds of thousands of pixels over the threshold.
        """
        if score_map.size == 0:
            return []

        rx = max(
            2,
            int(radius_x),
        )
        ry = max(
            2,
            int(radius_y),
        )

        kernel = np.ones(
            (
                ry * 2 + 1,
                rx * 2 + 1,
            ),
            dtype=np.uint8,
        )

        dilated = cv2.dilate(
            score_map,
            kernel,
        )

        maxima_mask = (
            (score_map >= float(threshold))
            & (
                score_map
                >= dilated
                - 1e-7
            )
        )

        ys, xs = np.where(
            maxima_mask
        )

        if len(xs) == 0:
            return []

        scores = score_map[
            ys,
            xs,
        ]

        if len(scores) > max_candidates:
            indices = np.argpartition(
                scores,
                -max_candidates,
            )[
                -max_candidates:
            ]
        else:
            indices = np.arange(
                len(scores)
            )

        indices = indices[
            np.argsort(
                scores[
                    indices
                ]
            )[::-1]
        ]

        return [
            (
                int(xs[index]),
                int(ys[index]),
                float(
                    scores[index]
                ),
            )
            for index in indices
        ]


    def _dense_candidate_map(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        methods: tuple[str, ...],
    ) -> np.ndarray | None:
        """
        Produce a dense candidate map for enumerating repeated targets.

        FeatureMatch is not a dense detector by itself, so repeated-target
        enumeration is seeded by template/gray/edge correlation. RGB/HSV and
        FeatureMatch still remain useful in the normal single-target consensus
        pipeline and as verification modes.
        """
        maps: list[np.ndarray] = []

        if "ccoeff_color" in methods or any(
            method in methods
            for method in (
                "rgb_count",
                "hsv_count",
                "feature",
            )
        ):
            maps.append(
                cv2.matchTemplate(
                    screen,
                    template,
                    cv2.TM_CCOEFF_NORMED,
                )
            )

        if "grayscale" in methods:
            screen_gray = cv2.cvtColor(
                screen,
                cv2.COLOR_BGR2GRAY,
            )
            template_gray = cv2.cvtColor(
                template,
                cv2.COLOR_BGR2GRAY,
            )
            maps.append(
                cv2.matchTemplate(
                    screen_gray,
                    template_gray,
                    cv2.TM_CCOEFF_NORMED,
                )
            )

        if "edge" in methods:
            screen_gray = cv2.cvtColor(
                screen,
                cv2.COLOR_BGR2GRAY,
            )
            template_gray = cv2.cvtColor(
                template,
                cv2.COLOR_BGR2GRAY,
            )
            screen_edge = cv2.Canny(
                screen_gray,
                70,
                160,
            )
            template_edge = cv2.Canny(
                template_gray,
                70,
                160,
            )

            edge_ratio = float(
                np.count_nonzero(
                    template_edge
                )
            ) / float(
                max(
                    1,
                    template_edge.size,
                )
            )

            if (
                0.008
                <= edge_ratio
                <= 0.65
                and float(
                    np.var(
                        template_edge
                    )
                ) >= 80.0
            ):
                maps.append(
                    cv2.matchTemplate(
                        screen_edge,
                        template_edge,
                        cv2.TM_CCOEFF_NORMED,
                    )
                )

        if not maps:
            return None

        if len(maps) == 1:
            return maps[0]

        # Independent dense methods vote by their strongest score at each
        # position. NMS below prevents one physical target from duplicating.
        return np.maximum.reduce(
            maps
        )

    def scan_templates(
        self,
        template_path: str,
        roi: tuple[int, int, int, int] | None = None,
        options: TemplateScanOptions | None = None,
        max_results: int = 500,
    ) -> list[RecognitionResult]:
        """
        Enumerate repeated instances of the same template in one frame.

        Returned coordinates are always absolute global desktop coordinates.
        """
        options = (
            options
            or TemplateScanOptions()
        )

        template = self.load_template(
            template_path
        )

        screen, origin_x, origin_y = (
            self.capture(
                roi
            )
        )

        results: list[
            RecognitionResult
        ] = []

        for scale in options.scales:
            scaled = self._resize_template(
                template,
                float(scale),
            )

            h, w = scaled.shape[:2]

            if (
                h > screen.shape[0]
                or w > screen.shape[1]
            ):
                continue

            score_map = self._dense_candidate_map(
                screen,
                scaled,
                tuple(
                    options.methods
                ),
            )

            if score_map is None:
                continue

            local_maxima = (
                self._local_maxima_from_map(
                    score_map,
                    threshold=options.threshold,
                    radius_x=max(
                        4,
                        int(
                            w * 0.45
                        ),
                    ),
                    radius_y=max(
                        4,
                        int(
                            h * 0.45
                        ),
                    ),
                    max_candidates=max_results
                    * 3,
                )
            )

            for x, y, score in local_maxima:
                center_x = (
                    int(x)
                    + w // 2
                )
                center_y = (
                    int(y)
                    + h // 2
                )

                results.append(
                    RecognitionResult(
                        global_x=(
                            int(origin_x)
                            + center_x
                        ),
                        global_y=(
                            int(origin_y)
                            + center_y
                        ),
                        score=float(score),
                        method="multi_template",
                        scale=float(scale),
                        local_x=center_x,
                        local_y=center_y,
                        capture_origin_x=int(
                            origin_x
                        ),
                        capture_origin_y=int(
                            origin_y
                        ),
                    )
                )

        if not results:
            return []

        # Cross-scale NMS.
        template_h, template_w = (
            template.shape[:2]
        )
        suppress_x = max(
            5,
            int(
                template_w * 0.42
            ),
        )
        suppress_y = max(
            5,
            int(
                template_h * 0.42
            ),
        )

        results.sort(
            key=lambda item: (
                item.score,
                -item.global_x,
            ),
            reverse=True,
        )

        kept: list[
            RecognitionResult
        ] = []

        for candidate in results:
            duplicate = False

            for existing in kept:
                if (
                    abs(
                        candidate.global_x
                        - existing.global_x
                    )
                    <= suppress_x
                    and abs(
                        candidate.global_y
                        - existing.global_y
                    )
                    <= suppress_y
                ):
                    duplicate = True
                    break

            if duplicate:
                continue

            kept.append(
                candidate
            )

            if len(kept) >= max_results:
                break

        return kept

    def scan_template(
        self,
        template_path: str,
        roi: tuple[int, int, int, int] | None = None,
        options: TemplateScanOptions | None = None,
    ) -> RecognitionResult | None:
        options = (
            options
            or TemplateScanOptions()
        )

        template = self.load_template(
            template_path
        )

        attempts = max(
            1,
            int(
                options.confirm_frames
            ),
        )

        accepted: list[
            RecognitionResult
        ] = []

        start_time = (
            time.perf_counter()
        )

        for _ in range(attempts):
            screen, origin_x, origin_y = (
                self.capture(
                    roi
                )
            )

            result = self._scan_frame(
                screen,
                origin_x,
                origin_y,
                template,
                options,
            )

            if result is None:
                return None

            accepted.append(
                result
            )

        if len(accepted) > 1:
            anchor = accepted[0]

            for result in accepted[1:]:
                distance = (
                    (
                        result.global_x
                        - anchor.global_x
                    )
                    ** 2
                    + (
                        result.global_y
                        - anchor.global_y
                    )
                    ** 2
                ) ** 0.5

                if (
                    distance
                    > options.confirm_tolerance_px
                ):
                    return None

        best = max(
            accepted,
            key=lambda item: item.score,
        )

        elapsed_ms = (
            time.perf_counter()
            - start_time
        ) * 1000.0

        return RecognitionResult(
            global_x=best.global_x,
            global_y=best.global_y,
            score=best.score,
            method=best.method,
            scale=best.scale,
            elapsed_ms=elapsed_ms,
            local_x=best.local_x,
            local_y=best.local_y,
            capture_origin_x=best.capture_origin_x,
            capture_origin_y=best.capture_origin_y,
        )

    def benchmark(
        self,
        template_path: str,
        iterations: int = 10,
        roi: tuple[int, int, int, int] | None = None,
        options: TemplateScanOptions | None = None,
    ) -> dict[str, float | int | str]:
        times = []
        hits = 0

        for _ in range(
            max(
                1,
                int(iterations),
            )
        ):
            start = (
                time.perf_counter()
            )

            result = self.scan_template(
                template_path,
                roi=roi,
                options=options,
            )

            elapsed = (
                time.perf_counter()
                - start
            ) * 1000.0

            times.append(
                elapsed
            )

            if result is not None:
                hits += 1

        return {
            "backend": self.backend_name,
            "iterations": len(times),
            "hits": hits,
            "mean_ms": float(
                statistics.mean(times)
            ),
            "median_ms": float(
                statistics.median(times)
            ),
            "min_ms": float(
                min(times)
            ),
            "max_ms": float(
                max(times)
            ),
        }
