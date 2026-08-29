from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal

from ...core.i18n import tr_text
from ...core.keyboard_action_engine import KeyboardOptions
from ...core.mouse_action_engine import ClickOptions, MoveOptions
from ...core.recognition_engine import DEFAULT_METHODS, TemplateScanOptions
from .registry import (
    ACTION_MODULE_TYPES, LOGIC_CONTAINER_TYPES, VISUAL_MODULE_TYPES,
    get_module_definition,
)

MODULE_MIN_GAP_SECONDS = 0.005

@dataclass(frozen=True)
class ExecutionStep:
    module_type: str
    label: str
    template_path: str | None = None
    match_threshold: float = 0.860
    recognition_methods: tuple[str, ...] = DEFAULT_METHODS
    multi_scale: bool = True
    confirm_frames: int = 1
    feature_detector: str = "SIFT"

    # Scan Template completion policy.
    # When enabled, the module itself remains RUNNING until a match appears
    # or this timeout expires. The downstream module cannot start earlier.
    wait_for_match: bool = True
    wait_timeout_ms: int = 1000

    roi: tuple[int, int, int, int] | None = None
    roi_anchor_template_path: str | None = None
    global_anchor_template_path: str | None = None
    global_anchor_roi: tuple[int, int, int, int] | None = None

    # Fixed coordinate data
    fixed_coordinate_x: int = 0
    fixed_coordinate_y: int = 0
    fixed_coordinate_anchor_path: str | None = None

    # Coordinate modifier data
    coordinate_modify_x: int = 0
    coordinate_modify_y: int = 0

    # Mouse movement
    move_advanced: bool = False
    move_offset_up: float = 0.0
    move_offset_down: float = 0.0
    move_offset_left: float = 0.0
    move_offset_right: float = 0.0
    move_speed_mode: str = "duration"
    move_speed_value: float = 0.0
    move_speed_variance: float = 0.0
    move_random_route: bool = False

    # Click
    click_count: int = 1
    click_advanced: bool = False
    click_press_duration: float = 0.025
    click_interval: float = 0.100

    # Standalone mouse press / release modules.
    mouse_button: str = "left"

    # Drag always receives its start coordinate from the current chain input.
    # coordinate_to_coordinate: simple mode uses the manually configured end
    # point, while complex mode can evaluate drag_end_steps from input_2.
    # coordinate_drag_pixels: end = start + (drag_pixels_x, drag_pixels_y).
    drag_start_x: float = 0.0  # legacy project compatibility only
    drag_start_y: float = 0.0  # legacy project compatibility only
    drag_end_x: float = 0.0
    drag_end_y: float = 0.0
    drag_mode: str = "coordinate_to_coordinate"
    drag_pixels_x: float = 0.0
    drag_pixels_y: float = 0.0
    drag_end_from_input: bool = False
    drag_end_steps: tuple["ExecutionStep", ...] = ()
    drag_press_duration: float = 0.025

    key_name: str = "SPACE"
    key_mode: str = "press"
    key_count: int = 1
    key_interval: float = 0.0
    key_hold_duration: float = 0.500
    key_advanced: bool = False
    key_duration_variance: float = 0.0
    key_interval_variance: float = 0.0
    key_humanized: bool = False
    key_text_mode: bool = False
    key_text: str = ""

    executable_path: str = ""

    delay_value: float = 1.0
    delay_unit: str = "milliseconds"

    clock_value: float = 60.0
    clock_unit: str = "seconds"
    clock_behavior: str = "stop"
    clock_event_slot: int = 0

    loop_count: int = 1
    loop_infinite: bool = False
    branches: tuple[tuple["ExecutionStep", ...], ...] = ()

    children: tuple["ExecutionStep", ...] = ()

class WorkspaceRuntimeSignals(QObject):
    message = Signal(str)
    chain_finished = Signal()
    clock_expired = Signal(str, int)

def intersect_roi(
    first: tuple[int, int, int, int] | None,
    second: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int] | None:
    if first is None:
        return second
    if second is None:
        return first
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return int(left), int(top), int(right-left), int(bottom-top)


class ModuleRuntimeMixin:
    def _runtime_cancelled(self) -> bool:
            return (
                self._stop_event.is_set()
                or self._event_chain_cancel.is_set()
            )

    def _wait_module_gap(
            self,
            seconds: float = MODULE_MIN_GAP_SECONDS,
            ignore_event_chain_cancel: bool = False,
        ) -> bool:
            """
            Cooperative gap between two COMPLETED modules in the same chain.

            _execute_steps is intentionally synchronous: the next iteration is
            unreachable until the current module has finished all of its internal
            work. Separate event chains use separate worker threads and therefore
            remain concurrent.
            """
            end_time = (
                time.perf_counter()
                + max(
                    0.0,
                    float(seconds),
                )
            )

            while True:
                if self._stop_event.is_set():
                    return False

                if (
                    not ignore_event_chain_cancel
                    and self._event_chain_cancel.is_set()
                ):
                    return False

                remaining = (
                    end_time
                    - time.perf_counter()
                )

                if remaining <= 0:
                    return True

                time.sleep(
                    min(
                        remaining,
                        0.001,
                    )
                )

    @staticmethod
    def _duration_seconds(value: float, unit: str) -> float:
            return max(0.0,float(value))*{"milliseconds":0.001,"seconds":1.0,"minutes":60.0,"hours":3600.0}.get(str(unit),1.0)

    def _start_clock(self, step: ExecutionStep) -> None:
            seconds=self._duration_seconds(step.clock_value,step.clock_unit); behavior=step.clock_behavior
            def worker():
                if not self._stop_event.wait(seconds):
                    self.runtime_signals.clock_expired.emit(
                        str(behavior),
                        int(step.clock_event_slot),
                    )
            th=threading.Thread(target=worker,daemon=True,name="UVAF-Clock"); self._clock_threads.append(th); th.start()
            self.logger.info(f"时钟已启动：{seconds:.3f}s → {behavior}",source="global")

    def _on_clock_expired(
            self,
            behavior: str,
            clock_event_slot: int,
        ) -> None:
            self.logger.info(
                f"时钟结束：{behavior}",
                source="global",
            )

            if behavior in {
                "execute_chain",
                "stop_others_execute_chain",
            }:
                if behavior == "stop_others_execute_chain":
                    # Stop ordinary/event chains only. Do not set _stop_event,
                    # because the clock-end chain must remain allowed to run.
                    self._event_chain_cancel.set()
                    self.logger.info(
                        "时钟：已终止其他事件链条，开始执行时钟终止后链。",
                        source="global",
                    )

                event_chain = self._clock_event_chains.get(
                    int(clock_event_slot),
                    [],
                )

                if event_chain:
                    context = {
                        "last_output": None,
                        "last_output_space": None,
                        "global_recognition_roi": (
                            self._active_global_recognition_roi
                        ),
                        "global_anchor_point": (
                            self._active_global_anchor_point
                        ),
                    }

                    def runner():
                        self._execute_steps(
                            9001,
                            event_chain,
                            context,
                            None,
                            ignore_event_chain_cancel=True,
                        )

                    threading.Thread(
                        target=runner,
                        daemon=True,
                        name="UVAF-ClockEvent",
                    ).start()

                return

            self.stop_workflows()

            if behavior == "stop_close":
                self.window().close()

    def _activate_global_steps(
            self,
            global_steps: list[ExecutionStep],
        ) -> bool:
            """
            Apply global settings synchronously before ordinary workflow threads
            start. Their effects remain stored on WorkspacePage until Stop.
            """
            if not global_steps:
                return True

            combined_roi: (
                tuple[int, int, int, int]
                | None
            ) = None

            first_anchor_point = None

            for step in global_steps:
                if self._stop_event.is_set():
                    return False

                if not self._wait_module_gap():
                    return False

                if step.module_type == "clock":
                    self._start_clock(step)
                    continue

                if (
                    not step.global_anchor_template_path
                    or step.global_anchor_roi is None
                ):
                    self.runtime_status.setText(
                        tr_text(
                            "全局设置未完成配置"
                        )
                    )
                    return False

                anchor = (
                    self.recognition_engine.scan_template(
                        step.global_anchor_template_path,
                        roi=combined_roi,
                        options=TemplateScanOptions(
                            threshold=0.860,
                            methods=(
                                "ccoeff_color",
                                "grayscale",
                                "feature",
                            ),
                            scales=(
                                0.90,
                                1.0,
                                1.10,
                            ),
                            confirm_frames=1,
                        ),
                    )
                )

                if anchor is None:
                    self.runtime_status.setText(
                        tr_text(
                            "全局锚点未找到"
                        )
                    )
                    return False

                if first_anchor_point is None:
                    first_anchor_point = (
                        anchor.global_x,
                        anchor.global_y,
                    )

                off_x, off_y, width, height = (
                    step.global_anchor_roi
                )

                resolved = (
                    anchor.x + off_x,
                    anchor.y + off_y,
                    width,
                    height,
                )

                combined_roi = intersect_roi(
                    combined_roi,
                    resolved,
                )

                if combined_roi is None:
                    self.runtime_status.setText(
                        tr_text(
                            "多个全局识别范围没有交集"
                        )
                    )
                    return False

            with self._runtime_lock:
                self._active_global_recognition_roi = (
                    combined_roi
                )
                self._active_global_anchor_point = (
                    first_anchor_point
                )
                self._global_runtime_active = True

            global_message = (
                "全局设置已持续启用："
                f"{combined_roi}"
            )

            self.logger.info(
                global_message,
                source="global",
            )
            self.runtime_signals.message.emit(
                global_message
            )

            return True

    def stop_workflows(self) -> None:
            """
            Stop the current runtime and remove every persistent global setting.

            Existing worker threads are cooperative: each module boundary checks
            _stop_event and exits as soon as possible.
            """
            self._vision_clear_debug()

            # Standalone Mouse Down modules may intentionally leave a button
            # held across later modules. Stop must never leave Windows in a
            # stuck mouse-button state.
            try:
                self.mouse_action_engine.release_all()
            except Exception:
                pass

            self._stop_event.set()

            with self._runtime_lock:
                self._active_global_recognition_roi = None
                self._active_global_anchor_point = None
                self._global_runtime_active = False

            self._active_chains = 0

            if hasattr(
                self,
                "run_button",
            ):
                self.run_button.setEnabled(
                    True
                )

            if hasattr(
                self,
                "stop_button",
            ):
                self.stop_button.setEnabled(
                    False
                )

            if hasattr(
                self,
                "runtime_status",
            ):
                self.runtime_status.setText(
                    tr_text(
                        "已停止"
                    )
                )

    def _resolve_global_step_roi(
            self,
            step: ExecutionStep,
        ) -> tuple[int, int, int, int] | None:
            if (
                step.module_type != "global_anchor_roi"
                or not step.global_anchor_template_path
                or step.global_anchor_roi is None
            ):
                return None

            anchor = self.recognition_engine.scan_template(
                step.global_anchor_template_path,
                roi=None,
                options=TemplateScanOptions(
                    threshold=0.860,
                    methods=("ccoeff_color", "grayscale", "feature"),
                    scales=(0.90, 1.0, 1.10),
                    confirm_frames=1,
                ),
            )

            if anchor is None:
                return None

            off_x, off_y, width, height = step.global_anchor_roi
            return (
                anchor.x + off_x,
                anchor.y + off_y,
                width,
                height,
            )

    def _launch_chains(
            self,
            chains: list[
                list[ExecutionStep]
            ],
        ) -> None:
            # Global settings are intentionally resolved before any start chain
            # launches, so one connected global-setting module constrains every
            # concurrently executing start chain. Multiple global restrictions
            # combine by intersection.
            # Global settings have already been resolved synchronously by
            # _activate_global_steps() before ordinary chains are launched.
            # Start from that persistent restriction instead of None.
            with self._runtime_lock:
                run_global_roi = (
                    self._active_global_recognition_roi
                )

            for chain in chains:
                for step in chain:
                    if step.module_type != "global_anchor_roi":
                        continue

                    try:
                        resolved = self._resolve_global_step_roi(step)
                    except Exception as exc:
                        self.logger.warning(
                            f"Global recognition restriction failed: {exc}",
                            source="global",
                        )
                        resolved = None

                    if resolved is not None:
                        run_global_roi = intersect_roi(
                            run_global_roi,
                            resolved,
                        )

            self._active_chains = len(
                chains
            )
            self.run_button.setEnabled(
                False
            )
            self.stop_button.setEnabled(
                True
            )
            self.runtime_status.setText(
                tr_text(
                    f"正在运行 {len(chains)} 条流程"
                )
            )

            barrier = threading.Barrier(
                len(chains)
            )

            for index, steps in enumerate(
                chains,
                start=1,
            ):
                worker = threading.Thread(
                    target=self._execute_chain,
                    args=(
                        index,
                        steps,
                        barrier,
                        run_global_roi,
                    ),
                    daemon=True,
                    name=(
                        f"UVAF-Workflow-{index}"
                    ),
                )
                worker.start()

    def _execute_chain(
            self,
            chain_index: int,
            steps: list[ExecutionStep],
            barrier: threading.Barrier,
            run_global_roi: tuple[int, int, int, int] | None,
        ) -> None:
            try:
                try:
                    barrier.wait(
                        timeout=3.0
                    )
                except (
                    threading.BrokenBarrierError
                ):
                    pass

                context: dict[
                    str,
                    object,
                ] = {
                    "last_output": None,
                    "last_output_space": None,
                    "global_recognition_roi": (
                        run_global_roi
                        if run_global_roi is not None
                        else self._active_global_recognition_roi
                    ),
                    "global_anchor_point": (
                        self._active_global_anchor_point
                        if hasattr(
                            self,
                            "_active_global_anchor_point",
                        )
                        else None
                    ),
                }

                self._execute_steps(
                    chain_index,
                    steps,
                    context,
                    active_roi=None,
                )

            finally:
                self.runtime_signals.chain_finished.emit()

    @staticmethod
    def _condition_truth(value) -> bool:
            if isinstance(value,bool):
                return value
            if isinstance(value,(int,float)):
                return value != 0
            if isinstance(value,(tuple,list)) and len(value)>=2:
                return True
            if value is None:
                return False
            return bool(value)

    @classmethod
    def _step_contributes_condition(
            cls,
            step: ExecutionStep,
        ) -> bool:
            if step.module_type in ACTION_MODULE_TYPES:
                return False

            if step.module_type == "roi":
                return any(
                    cls._step_contributes_condition(child)
                    for child in step.children
                )

            if step.module_type in LOGIC_CONTAINER_TYPES:
                return any(
                    cls._step_contributes_condition(child)
                    for branch in step.branches
                    for child in branch
                )

            if step.module_type == "global_anchor_roi":
                return False

            return True

    def _evaluate_condition_branch(
            self,
            chain_index:int,
            branch,
            context:dict[str,object],
            active_roi,
            selection_anchor,
            ignore_event_chain_cancel:bool,
            local_cancel_event=None,
        ) -> tuple[bool,dict[str,object]]:
            branch_context=dict(context)

            # An empty judgement frame does not satisfy a condition.
            if not branch:
                return False, branch_context

            contributes=any(
                self._step_contributes_condition(step)
                for step in branch
            )

            success=self._execute_steps(
                chain_index,
                branch,
                branch_context,
                active_roi,
                selection_anchor=selection_anchor,
                ignore_event_chain_cancel=ignore_event_chain_cancel,
                local_cancel_event=local_cancel_event,
            )

            if not success:
                return False,branch_context

            # Explicit user rule: if the judgement frame contains only actions,
            # successful completion counts as True, while those actions themselves
            # never provide a separate judgement value.
            if not contributes:
                return True,branch_context

            return (
                self._condition_truth(
                    branch_context.get("last_output")
                ),
                branch_context,
            )

    def _evaluate_two_conditions_parallel(
            self,
            chain_index:int,
            first,
            second,
            context:dict[str,object],
            active_roi,
            selection_anchor,
            ignore_event_chain_cancel:bool,
            mode:str,
            local_cancel_event=None,
        ):
            """
            Evaluate two judgement branches concurrently.

            OR:  return as soon as either branch becomes True.
            AND: return False as soon as either branch becomes False; otherwise
                 wait for both True.
            NOR: return False as soon as either becomes True; otherwise wait until
                 both finish False.

            The unneeded sibling branch receives a local cancellation event, so an
            infinite detector in that branch cannot block a decision already made
            by the other branch.
            """
            results=[None,None]
            done=[threading.Event(),threading.Event()]
            cancel=[threading.Event(),threading.Event()]

            def worker(index:int,branch)->None:
                try:
                    results[index]=self._evaluate_condition_branch(
                        chain_index,
                        branch,
                        context,
                        active_roi,
                        selection_anchor,
                        ignore_event_chain_cancel,
                        cancel[index],
                    )
                finally:
                    done[index].set()

            threads=[
                threading.Thread(
                    target=worker,
                    args=(0,first),
                    daemon=True,
                    name=f"UVAF-Cond-{chain_index}-A",
                ),
                threading.Thread(
                    target=worker,
                    args=(1,second),
                    daemon=True,
                    name=f"UVAF-Cond-{chain_index}-B",
                ),
            ]

            for thread in threads:
                thread.start()

            verdict=None
            selected_context=dict(context)

            while verdict is None:
                if (
                    self._stop_event.is_set()
                    or (
                        local_cancel_event is not None
                        and local_cancel_event.is_set()
                    )
                ):
                    cancel[0].set(); cancel[1].set()
                    verdict=False
                    break

                known=[
                    (
                        results[index][0]
                        if results[index] is not None
                        else None
                    )
                    for index in range(2)
                ]

                if mode=="or":
                    for index,value in enumerate(known):
                        if value is True:
                            verdict=True
                            selected_context=results[index][1]
                            cancel[1-index].set()
                            break

                    if verdict is None and all(done_event.is_set() for done_event in done):
                        verdict=False
                        for result in results:
                            if result is not None:
                                selected_context=result[1]

                elif mode=="and":
                    for index,value in enumerate(known):
                        if value is False:
                            verdict=False
                            selected_context=results[index][1]
                            cancel[1-index].set()
                            break

                    if (
                        verdict is None
                        and all(value is True for value in known)
                    ):
                        verdict=True
                        selected_context=results[1][1]

                else:  # NOR
                    for index,value in enumerate(known):
                        if value is True:
                            verdict=False
                            selected_context=results[index][1]
                            cancel[1-index].set()
                            break

                    if (
                        verdict is None
                        and all(done_event.is_set() for done_event in done)
                    ):
                        verdict=all(value is False for value in known)
                        for result in results:
                            if result is not None:
                                selected_context=result[1]

                if verdict is None:
                    time.sleep(0.005)

            for thread in threads:
                thread.join(timeout=0.10)

            values=[
                (
                    results[index][0]
                    if results[index] is not None
                    else False
                )
                for index in range(2)
            ]

            return (
                bool(verdict),
                selected_context,
                bool(values[0]),
                bool(values[1]),
            )

    def _execute_steps(
            self,
            chain_index: int,
            steps,
            context: dict[str, object],
            active_roi,
            selection_anchor=None,
            ignore_event_chain_cancel: bool = False,
            local_cancel_event=None,
        ) -> bool:
            def module_cancelled() -> bool:
                if self._stop_event.is_set():
                    return True
                if (
                    not ignore_event_chain_cancel
                    and self._event_chain_cancel.is_set()
                ):
                    return True
                if (
                    local_cancel_event is not None
                    and local_cancel_event.is_set()
                ):
                    return True
                return False

            for step_index, step in enumerate(
                steps
            ):
                if self._stop_event.is_set():
                    return False

                if (
                    not ignore_event_chain_cancel
                    and self._event_chain_cancel.is_set()
                ):
                    return False

                if (
                    local_cancel_event is not None
                    and local_cancel_event.is_set()
                ):
                    return False

                # Mandatory executor guard: every module gets at least a 5 ms
                # scheduling gap before it runs. This also covers the first child
                # inside ROI containers and event-triggered chains.
                if not self._wait_module_gap(
                    MODULE_MIN_GAP_SECONDS,
                    ignore_event_chain_cancel=(
                        ignore_event_chain_cancel
                    ),
                ):
                    return False

                if step.module_type == "custom_module_instance":
                    branches = [
                        branch
                        for branch in step.branches
                        if branch
                    ]

                    if not branches:
                        self.logger.warning(
                            f"流程 {chain_index}：自定义模块 {step.label} 没有可执行内容。",
                            source="custom",
                        )
                        continue

                    if len(branches) == 1:
                        if not self._execute_steps(
                            chain_index,
                            branches[0],
                            context,
                            active_roi,
                            selection_anchor=selection_anchor,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                            local_cancel_event=local_cancel_event,
                        ):
                            return False
                    else:
                        done_events: list[threading.Event] = []
                        results: list[tuple[bool, dict[str, object]] | None] = [
                            None
                            for _ in branches
                        ]

                        def run_custom_branch(
                            branch_index: int,
                            branch_steps,
                        ) -> None:
                            branch_context = dict(context)
                            ok = self._execute_steps(
                                chain_index,
                                branch_steps,
                                branch_context,
                                active_roi,
                                selection_anchor=selection_anchor,
                                ignore_event_chain_cancel=ignore_event_chain_cancel,
                                local_cancel_event=local_cancel_event,
                            )
                            results[branch_index] = (
                                ok,
                                branch_context,
                            )
                            done_events[branch_index].set()

                        for branch_index, branch_steps in enumerate(branches):
                            done = threading.Event()
                            done_events.append(done)
                            threading.Thread(
                                target=run_custom_branch,
                                args=(branch_index, branch_steps),
                                daemon=True,
                                name=f"UVAF-Custom-{chain_index}-{branch_index+1}",
                            ).start()

                        while not all(
                            event.is_set()
                            for event in done_events
                        ):
                            if self._stop_event.wait(0.005):
                                return False
                            if (
                                local_cancel_event is not None
                                and local_cancel_event.is_set()
                            ):
                                return False

                        for result in results:
                            if result is None or not result[0]:
                                return False

                        # Multiple internal roots complete as one module. Use the
                        # last branch's final output as the custom module output.
                        if results and results[-1] is not None:
                            context.update(results[-1][1])

                    self.logger.info(
                        f"流程 {chain_index}：自定义模块 {step.label} 完成",
                        source="custom",
                    )
                    continue

                if step.module_type == "loop":
                    branch = step.branches[0] if step.branches else ()
                    iteration = 0

                    while (
                        step.loop_infinite
                        or iteration < max(1, int(step.loop_count))
                    ):
                        if module_cancelled():
                            return False
                        if local_cancel_event is not None and local_cancel_event.is_set():
                            return False

                        if branch:
                            if not self._execute_steps(
                                chain_index,
                                branch,
                                context,
                                active_roi,
                                selection_anchor=selection_anchor,
                                ignore_event_chain_cancel=ignore_event_chain_cancel,
                                local_cancel_event=local_cancel_event,
                            ):
                                return False
                        else:
                            if not self._wait_module_gap(
                                MODULE_MIN_GAP_SECONDS,
                                ignore_event_chain_cancel=ignore_event_chain_cancel,
                            ):
                                return False

                        iteration += 1

                    self.logger.info(
                        f"流程 {chain_index}：循环完成 · {iteration} 次",
                        source="logic",
                    )
                    continue

                if step.module_type == "loop_until":
                    repeating = step.branches[0] if len(step.branches) > 0 else ()
                    terminator = step.branches[1] if len(step.branches) > 1 else ()

                    stop_repeating = threading.Event()
                    repeating_done = threading.Event()
                    repeating_context = dict(context)

                    def repeat_worker() -> None:
                        try:
                            while (
                                not stop_repeating.is_set()
                                and not self._stop_event.is_set()
                            ):
                                if repeating:
                                    completed = self._execute_steps(
                                        chain_index,
                                        repeating,
                                        repeating_context,
                                        active_roi,
                                        selection_anchor=selection_anchor,
                                        ignore_event_chain_cancel=ignore_event_chain_cancel,
                                        local_cancel_event=stop_repeating,
                                    )
                                    if not completed and not stop_repeating.is_set():
                                        break
                                else:
                                    if stop_repeating.wait(MODULE_MIN_GAP_SECONDS):
                                        break
                        finally:
                            repeating_done.set()

                    thread = threading.Thread(
                        target=repeat_worker,
                        daemon=True,
                        name=f"UVAF-LoopUntil-{chain_index}",
                    )
                    thread.start()

                    terminator_context = dict(context)

                    if terminator:
                        self._execute_steps(
                            chain_index,
                            terminator,
                            terminator_context,
                            active_roi,
                            selection_anchor=selection_anchor,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                            local_cancel_event=local_cancel_event,
                        )

                    stop_repeating.set()

                    while not repeating_done.wait(0.005):
                        if self._stop_event.is_set():
                            break

                    thread.join(timeout=0.10)
                    context.update(terminator_context)

                    self.logger.info(
                        f"流程 {chain_index}：循环…直到…终止分支已完成",
                        source="logic",
                    )
                    continue

                if step.module_type == "logic_if":
                    condition_branch = step.branches[0] if len(step.branches) > 0 else ()
                    then_branch = step.branches[1] if len(step.branches) > 1 else ()

                    condition, condition_context = self._evaluate_condition_branch(
                        chain_index,
                        condition_branch,
                        context,
                        active_roi,
                        selection_anchor,
                        ignore_event_chain_cancel,
                        local_cancel_event,
                    )
                    context.update(condition_context)

                    if condition and then_branch:
                        if not self._execute_steps(
                            chain_index,
                            then_branch,
                            context,
                            active_roi,
                            selection_anchor=selection_anchor,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                            local_cancel_event=local_cancel_event,
                        ):
                            return False

                    self.logger.info(
                        f"流程 {chain_index}：IF 判定 → {condition}",
                        source="logic",
                    )
                    continue

                if step.module_type in {"logic_or", "logic_nor", "logic_and"}:
                    first_branch = step.branches[0] if len(step.branches) > 0 else ()
                    second_branch = step.branches[1] if len(step.branches) > 1 else ()
                    action_branch = step.branches[2] if len(step.branches) > 2 else ()

                    mode = (
                        "or"
                        if step.module_type == "logic_or"
                        else (
                            "nor"
                            if step.module_type == "logic_nor"
                            else "and"
                        )
                    )

                    (
                        verdict,
                        selected_context,
                        first_value,
                        second_value,
                    ) = self._evaluate_two_conditions_parallel(
                        chain_index,
                        first_branch,
                        second_branch,
                        context,
                        active_roi,
                        selection_anchor,
                        ignore_event_chain_cancel,
                        mode,
                        local_cancel_event,
                    )

                    context.update(selected_context)

                    if verdict and action_branch:
                        if not self._execute_steps(
                            chain_index,
                            action_branch,
                            context,
                            active_roi,
                            selection_anchor=selection_anchor,
                            ignore_event_chain_cancel=ignore_event_chain_cancel,
                            local_cancel_event=local_cancel_event,
                        ):
                            return False

                    self.logger.info(
                        (
                            f"流程 {chain_index}：{step.module_type} → "
                            f"A={first_value}, B={second_value}, 结果={verdict}"
                        ),
                        source="logic",
                    )
                    continue

                if step.module_type == "global_anchor_roi":
                    if not step.global_anchor_template_path or step.global_anchor_roi is None:
                        self.logger.warning(f"流程 {chain_index}：仅识别锚点未完成设置。", source="global")
                        return False

                    anchor = self.recognition_engine.scan_template(
                        step.global_anchor_template_path,
                        roi=None,
                        options=TemplateScanOptions(
                            threshold=0.860,
                            methods=("ccoeff_color", "grayscale", "feature"),
                            scales=(0.90, 1.0, 1.10),
                            confirm_frames=1,
                        ),
                    )
                    if anchor is None:
                        self.logger.warning(f"流程 {chain_index}：全局锚点未找到。", source="global")
                        return False
                    off_x, off_y, width, height = step.global_anchor_roi
                    resolved_global_roi = (
                        anchor.x + off_x,
                        anchor.y + off_y,
                        width,
                        height,
                    )
                    context["global_recognition_roi"] = intersect_roi(
                        context.get("global_recognition_roi"),
                        resolved_global_roi,
                    )
                    if context["global_recognition_roi"] is None:
                        return False
                    self.runtime_signals.message.emit(
                        f"流程 {chain_index}：全局识别视野已限制为 {context['global_recognition_roi']}"
                    )
                    continue

                if step.module_type == "roi":
                    roi = step.roi

                    if roi is None:
                        return False

                    resolved_roi = roi

                    if step.roi_anchor_template_path:
                        anchor_result = (
                            self.recognition_engine.scan_template(
                                step.roi_anchor_template_path,
                                roi=context.get("global_recognition_roi"),
                                options=TemplateScanOptions(
                                    threshold=0.860,
                                    methods=(
                                        "ccoeff_color",
                                        "grayscale",
                                        "feature",
                                    ),
                                    scales=(
                                        0.90,
                                        1.0,
                                        1.10,
                                    ),
                                    confirm_frames=1,
                                ),
                            )
                        )

                        if anchor_result is None:
                            return False

                        anchor_x = anchor_result.x
                        anchor_y = anchor_result.y
                        off_x, off_y, width, height = roi

                        resolved_roi = (
                            anchor_x + off_x,
                            anchor_y + off_y,
                            width,
                            height,
                        )

                    resolved_roi = intersect_roi(
                        resolved_roi,
                        context.get("global_recognition_roi"),
                    )
                    if resolved_roi is None:
                        self.logger.warning(f"流程 {chain_index}：ROI 与全局识别视野没有交集。", source="roi")
                        return False

                    roi_anchor_point = (
                        (
                            anchor_x,
                            anchor_y,
                        )
                        if step.roi_anchor_template_path
                        else None
                    )

                    if step.children:
                        if not self._execute_steps(
                            chain_index,
                            step.children,
                            context,
                            resolved_roi,
                            selection_anchor=(
                                roi_anchor_point
                                or context.get(
                                    "global_anchor_point"
                                )
                            ),
                            ignore_event_chain_cancel=(
                                ignore_event_chain_cancel
                            ),
                            local_cancel_event=(
                                local_cancel_event
                            ),
                        ):
                            return False

                    # In complex mode an ROI node with no embedded children acts
                    # as a modifier for the following chain.
                    active_roi = resolved_roi
                    selection_anchor = (
                        roi_anchor_point
                        or context.get(
                            "global_anchor_point"
                        )
                    )
                    continue

                if step.module_type == "coordinate_modify":
                    incoming = context.get(
                        "last_output"
                    )

                    if (
                        not isinstance(
                            incoming,
                            (tuple, list),
                        )
                        or len(incoming) != 2
                    ):
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                "坐标修改需要一个坐标输入，"
                                f"实际输入={incoming!r}"
                            ),
                            source="data",
                        )
                        return False

                    try:
                        input_x = int(
                            round(
                                float(
                                    incoming[0]
                                )
                            )
                        )
                        input_y = int(
                            round(
                                float(
                                    incoming[1]
                                )
                            )
                        )
                    except (
                        TypeError,
                        ValueError,
                        OverflowError,
                    ):
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                "坐标修改收到的坐标无法转换为数值。"
                            ),
                            source="data",
                        )
                        return False

                    output = (
                        input_x
                        + int(
                            step.coordinate_modify_x
                        ),
                        input_y
                        + int(
                            step.coordinate_modify_y
                        ),
                    )

                    context[
                        "last_output"
                    ] = output
                    context[
                        "last_output_space"
                    ] = (
                        context.get(
                            "last_output_space"
                        )
                        or "global_screen"
                    )

                    self.logger.info(
                        (
                            f"流程 {chain_index}："
                            f"坐标修改 {incoming} "
                            f"+ ({step.coordinate_modify_x:+d}, "
                            f"{step.coordinate_modify_y:+d}) "
                            f"→ {output}"
                        ),
                        source="data",
                    )
                    continue

                if step.module_type == "fixed_coordinate":
                    output_x = int(
                        step.fixed_coordinate_x
                    )
                    output_y = int(
                        step.fixed_coordinate_y
                    )

                    anchor_path = (
                        step.fixed_coordinate_anchor_path
                    )

                    if anchor_path:
                        effective_roi = intersect_roi(
                            active_roi,
                            context.get(
                                "global_recognition_roi"
                            ),
                        )

                        if (
                            active_roi is not None
                            and context.get(
                                "global_recognition_roi"
                            ) is not None
                            and effective_roi is None
                        ):
                            self.logger.warning(
                                (
                                    f"流程 {chain_index}："
                                    "固定坐标的锚点搜索范围为空。"
                                ),
                                source="data",
                            )
                            return False

                        try:
                            anchor = (
                                self.recognition_engine
                                .scan_template(
                                    anchor_path,
                                    roi=effective_roi,
                                    options=TemplateScanOptions(
                                        threshold=0.860,
                                        methods=(
                                            "ccoeff_color",
                                            "grayscale",
                                            "feature",
                                        ),
                                        scales=(
                                            0.90,
                                            1.0,
                                            1.10,
                                        ),
                                        confirm_frames=1,
                                    ),
                                )
                            )
                        except Exception as exc:
                            self.logger.warning(
                                (
                                    f"流程 {chain_index}："
                                    f"固定坐标锚点识别失败：{exc}"
                                ),
                                source="data",
                            )
                            return False

                        if anchor is None:
                            self.logger.warning(
                                (
                                    f"流程 {chain_index}："
                                    "固定坐标未找到锚点。"
                                ),
                                source="data",
                            )
                            return False

                        output_x = int(
                            anchor.global_x
                        ) + output_x
                        output_y = int(
                            anchor.global_y
                        ) + output_y

                        anchor_name = Path(
                            anchor_path
                        ).name
                        mode_text = (
                            f"锚点={anchor_name}"
                        )
                    else:
                        mode_text = "全屏坐标"

                    output = (
                        output_x,
                        output_y,
                    )

                    context[
                        "last_output"
                    ] = output
                    context[
                        "last_output_space"
                    ] = "global_screen"

                    self.logger.info(
                        (
                            f"流程 {chain_index}："
                            f"固定坐标 → {output} · "
                            f"{mode_text}"
                        ),
                        source="data",
                    )
                    continue

                if step.module_type in VISUAL_MODULE_TYPES:
                    if not step.template_path:
                        return False

                    effective_roi = intersect_roi(
                        active_roi,
                        context.get(
                            "global_recognition_roi"
                        ),
                    )

                    if (
                        active_roi is not None
                        and context.get(
                            "global_recognition_roi"
                        ) is not None
                        and effective_roi is None
                    ):
                        return False

                    definition = get_module_definition(
                        step.module_type
                    )
                    module_display = (
                        definition.runtime_label
                        if definition is not None
                        and definition.runtime_label
                        else step.label
                    )

                    self._vision_begin_sensing(
                        module_display,
                        effective_roi,
                    )

                    scales = (
                        (
                            0.90,
                            0.95,
                            1.0,
                            1.05,
                            1.10,
                        )
                        if step.multi_scale
                        else (1.0,)
                    )

                    options = TemplateScanOptions(
                        threshold=(
                            step.match_threshold
                        ),
                        methods=tuple(
                            step.recognition_methods
                        ),
                        scales=scales,
                        confirm_frames=max(
                            1,
                            int(
                                step.confirm_frames
                            ),
                        ),
                        feature_detector=(
                            step.feature_detector
                        ),
                    )

                    def get_matches():
                        return (
                            self.recognition_engine
                            .scan_templates(
                                step.template_path,
                                roi=effective_roi,
                                options=options,
                            )
                        )

                    def boxes_for(matches):
                        try:
                            template_image = (
                                self.recognition_engine
                                .load_template(
                                    step.template_path
                                )
                            )
                            template_h, template_w = (
                                template_image.shape[:2]
                            )
                        except Exception:
                            return []

                        boxes = []

                        for item in matches:
                            matched_w = max(
                                1,
                                int(
                                    round(
                                        template_w
                                        * float(
                                            item.scale
                                        )
                                    )
                                ),
                            )
                            matched_h = max(
                                1,
                                int(
                                    round(
                                        template_h
                                        * float(
                                            item.scale
                                        )
                                    )
                                ),
                            )
                            boxes.append(
                                (
                                    int(
                                        round(
                                            item.global_x
                                            - matched_w
                                            / 2.0
                                        )
                                    ),
                                    int(
                                        round(
                                            item.global_y
                                            - matched_h
                                            / 2.0
                                        )
                                    ),
                                    matched_w,
                                    matched_h,
                                )
                            )

                        return boxes

                    def choose_match(matches):
                        if not matches:
                            return None

                        anchor_point = (
                            selection_anchor
                            or context.get(
                                "global_anchor_point"
                            )
                        )

                        if anchor_point is not None:
                            anchor_x, anchor_y = (
                                anchor_point
                            )
                            return min(
                                matches,
                                key=lambda item: (
                                    (
                                        item.global_x
                                        - anchor_x
                                    )
                                    ** 2
                                    + (
                                        item.global_y
                                        - anchor_y
                                    )
                                    ** 2,
                                    item.global_x,
                                    item.global_y,
                                ),
                            )

                        # No anchor: always choose the left-most visible instance.
                        return min(
                            matches,
                            key=lambda item: (
                                item.global_x,
                                item.global_y,
                            ),
                        )

                    if step.module_type == "template_count":
                        try:
                            matches = get_matches()
                        except Exception as exc:
                            self.logger.error(
                                str(exc),
                                source="template_count",
                            )
                            return False

                        self._vision_publish_detection(
                            module_display,
                            effective_roi,
                            boxes_for(
                                matches
                            ),
                        )

                        count = len(
                            matches
                        )
                        context[
                            "last_output"
                        ] = count
                        context[
                            "last_output_space"
                        ] = "number"

                        message = (
                            f"流程 {chain_index}："
                            f"模板计数 → {count}"
                        )
                        self.logger.info(
                            message,
                            source="template_count",
                        )
                        self.runtime_signals.message.emit(
                            message
                        )
                        continue

                    if step.module_type == "lock_template":
                        remaining_steps = list(
                            steps[
                                step_index + 1:
                            ]
                        )

                        while not module_cancelled():
                            try:
                                matches = get_matches()
                            except Exception as exc:
                                self.logger.error(
                                    str(exc),
                                    source="lock_template",
                                )
                                return False

                            self._vision_publish_detection(
                                module_display,
                                effective_roi,
                                boxes_for(
                                    matches
                                ),
                            )

                            chosen = choose_match(
                                matches
                            )

                            if chosen is None:
                                self.runtime_signals.message.emit(
                                    (
                                        f"流程 {chain_index}："
                                        "锁定模板已消失"
                                    )
                                )
                                return True

                            context[
                                "last_output"
                            ] = (
                                int(
                                    chosen.global_x
                                ),
                                int(
                                    chosen.global_y
                                ),
                            )
                            context[
                                "last_output_space"
                            ] = "global_screen"

                            self.runtime_signals.message.emit(
                                (
                                    f"流程 {chain_index}："
                                    "锁定模板 → "
                                    f"({chosen.global_x}, "
                                    f"{chosen.global_y})"
                                )
                            )

                            if remaining_steps:
                                if not self._execute_steps(
                                    chain_index,
                                    remaining_steps,
                                    context,
                                    effective_roi,
                                    selection_anchor=(
                                        selection_anchor
                                    ),
                                    ignore_event_chain_cancel=(
                                        ignore_event_chain_cancel
                                    ),
                                    local_cancel_event=(
                                        local_cancel_event
                                    ),
                                ):
                                    return False

                            frame_wait = max(
                                0.001,
                                1.0 / max(
                                    1,
                                    int(
                                        self.recognition_engine.max_fps
                                    ),
                                ),
                            )
                            wait_end=time.perf_counter()+frame_wait
                            while time.perf_counter()<wait_end:
                                if module_cancelled():
                                    return False
                                time.sleep(
                                    min(
                                        0.005,
                                        max(
                                            0.0,
                                            wait_end-time.perf_counter(),
                                        ),
                                    )
                                )

                        return False

                    continuous_until_found = (
                        step.module_type == "scan_until_found"
                    )

                    # Standard Scan Template.
                    #
                    # Strict same-chain completion rule:
                    # this module remains inside this loop and therefore has NOT
                    # completed while the target is absent. No downstream module
                    # in this chain can execute until a match is produced or the
                    # timeout terminates the chain.
                    wait_enabled = (
                        True
                        if continuous_until_found
                        else bool(step.wait_for_match)
                    )
                    wait_timeout_seconds = (
                        max(
                            1,
                            int(
                                step.wait_timeout_ms
                            ),
                        )
                        / 1000.0
                    )
                    wait_started = (
                        time.perf_counter()
                    )
                    wait_deadline = (
                        wait_started
                        + wait_timeout_seconds
                    )

                    matches = []
                    result = None
                    attempts = 0

                    while True:
                        if module_cancelled():
                            return False

                        if (
                            not ignore_event_chain_cancel
                            and self._event_chain_cancel.is_set()
                        ):
                            return False

                        if (
                            local_cancel_event is not None
                            and local_cancel_event.is_set()
                        ):
                            return False

                        attempt_started = (
                            time.perf_counter()
                        )
                        attempts += 1

                        try:
                            matches = get_matches()
                        except Exception as exc:
                            self.logger.error(
                                str(exc),
                                source="findtemplate",
                            )
                            return False

                        self._vision_publish_detection(
                            module_display,
                            effective_roi,
                            boxes_for(
                                matches
                            ),
                        )

                        result = choose_match(
                            matches
                        )

                        if result is not None:
                            break

                        # Legacy one-shot behavior remains available by disabling
                        # "等待识别" in this module's settings.
                        if not wait_enabled:
                            message = (
                                f"流程 {chain_index}："
                                "扫描模板未命中"
                            )
                            self.runtime_signals.message.emit(
                                message
                            )
                            return False

                        now = time.perf_counter()

                        if (
                            not continuous_until_found
                            and now >= wait_deadline
                        ):
                            elapsed_ms = int(
                                round(
                                    (
                                        now
                                        - wait_started
                                    )
                                    * 1000.0
                                )
                            )
                            message = (
                                f"流程 {chain_index}："
                                "扫描模板等待识别超时 · "
                                f"{elapsed_ms} ms · "
                                f"尝试 {attempts} 次"
                            )
                            self.logger.warning(
                                message,
                                source="findtemplate",
                            )
                            self.runtime_signals.message.emit(
                                message
                            )
                            return False

                        # Poll no faster than the Recognition Engine frame rate.
                        # Recognition itself may already take longer than one
                        # frame; in that case there is no extra frame wait.
                        scan_elapsed = (
                            time.perf_counter()
                            - attempt_started
                        )
                        frame_period = (
                            1.0
                            / max(
                                1,
                                int(
                                    self.recognition_engine
                                    .max_fps
                                ),
                            )
                        )
                        until_next_frame = max(
                            0.0,
                            frame_period
                            - scan_elapsed,
                        )
                        remaining = (
                            max(
                                0.0,
                                wait_deadline - time.perf_counter(),
                            )
                            if not continuous_until_found
                            else max(
                                0.001,
                                1.0 / max(
                                    1,
                                    int(
                                        self.recognition_engine.max_fps
                                    ),
                                ),
                            )
                        )

                        # A tiny cooperative pause also prevents a very fast
                        # matcher from busy-spinning when the target is absent.
                        poll_wait = min(
                            remaining,
                            max(
                                0.001,
                                until_next_frame,
                            ),
                        )

                        if poll_wait > 0:
                            poll_end=(
                                time.perf_counter()
                                + poll_wait
                            )

                            while (
                                time.perf_counter()
                                < poll_end
                            ):
                                if module_cancelled():
                                    return False

                                time.sleep(
                                    min(
                                        0.005,
                                        max(
                                            0.0,
                                            poll_end
                                            - time.perf_counter(),
                                        ),
                                    )
                                )

                    global_x = int(
                        result.global_x
                    )
                    global_y = int(
                        result.global_y
                    )

                    context[
                        "last_output"
                    ] = (
                        global_x,
                        global_y,
                    )
                    context[
                        "last_output_space"
                    ] = "global_screen"

                    selection_text = (
                        "靠近锚点"
                        if (
                            selection_anchor
                            or context.get(
                                "global_anchor_point"
                            )
                        )
                        else "最左侧"
                    )

                    elapsed_ms = int(
                        round(
                            (
                                time.perf_counter()
                                - wait_started
                            )
                            * 1000.0
                        )
                    )

                    message = (
                        f"流程 {chain_index}："
                        f"扫描模板 → "
                        f"({global_x}, {global_y}) · "
                        f"候选 {len(matches)} · "
                        f"选择 {selection_text} · "
                        f"完成 {elapsed_ms} ms"
                        + (
                            f" · 尝试 {attempts} 次"
                            if wait_enabled
                            else ""
                        )
                    )

                    self.logger.info(
                        message,
                        source="findtemplate",
                    )
                    self.runtime_signals.message.emit(
                        message
                    )

                elif (
                    step.module_type
                    == "move_to"
                ):
                    coordinate = context.get(
                        "last_output"
                    )
                    coordinate_space = context.get(
                        "last_output_space"
                    )

                    if (
                        not isinstance(
                            coordinate,
                            (tuple, list),
                        )
                        or len(coordinate) < 2
                    ):
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                "移至需要上一个模块提供坐标数据。"
                            ),
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            (
                                f"流程 {chain_index}："
                                "移至缺少坐标输入"
                            )
                        )
                        return False

                    if coordinate_space != "global_screen":
                        self.logger.warning(
                            (
                                f"流程 {chain_index}："
                                "移至拒绝非全局屏幕坐标输入。"
                            ),
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            (
                                f"流程 {chain_index}："
                                "移至收到的不是全局屏幕坐标"
                            )
                        )
                        return False

                    try:
                        input_x = float(
                            coordinate[0]
                        )
                        input_y = float(
                            coordinate[1]
                        )

                        if step.move_advanced:
                            move_options = MoveOptions(
                                offset_up=step.move_offset_up,
                                offset_down=step.move_offset_down,
                                offset_left=step.move_offset_left,
                                offset_right=step.move_offset_right,
                                speed_mode=step.move_speed_mode,
                                speed_value=step.move_speed_value,
                                speed_variance=step.move_speed_variance,
                                random_route=step.move_random_route,
                            )
                        else:
                            # Normal mode is intentionally deterministic:
                            # exact target + immediate movement.
                            move_options = MoveOptions()

                        final_x, final_y = (
                            self.mouse_action_engine.move_to(
                                input_x,
                                input_y,
                                options=move_options,
                                stop_requested=(
                                    module_cancelled
                                ),
                            )
                        )

                        if self._stop_event.is_set():
                            return False

                        context[
                            "last_output"
                        ] = (
                            final_x,
                            final_y,
                        )
                        context[
                            "last_output_space"
                        ] = "global_screen"

                        message = (
                            f"流程 {chain_index}："
                            f"移至 → ({final_x}, {final_y})"
                        )

                        if step.move_advanced:
                            message += (
                                " · "
                                + (
                                    f"{step.move_speed_value:.3f}s"
                                    if step.move_speed_mode
                                    == "duration"
                                    else
                                    f"{step.move_speed_value:.1f}px/s"
                                )
                                + (
                                    " · 随机路线"
                                    if step.move_random_route
                                    else ""
                                )
                            )

                        self.logger.info(
                            message,
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            message
                        )

                    except Exception as exc:
                        self.logger.error(
                            f"移至失败：{exc}",
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            f"流程 {chain_index}：移至失败"
                        )
                        return False

                elif (
                    step.module_type
                    == "mouse_press"
                ):
                    try:
                        completed = self.mouse_action_engine.press(
                            step.mouse_button,
                            stop_requested=module_cancelled,
                        )

                        if self._stop_event.is_set():
                            return False

                        if not completed:
                            return False

                        button_name = {
                            "left": "左键",
                            "right": "右键",
                            "middle": "中键",
                        }.get(str(step.mouse_button), "左键")
                        message = (
                            f"流程 {chain_index}："
                            f"鼠标按下 · {button_name}"
                        )

                        self.logger.info(
                            message,
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            message
                        )

                    except Exception as exc:
                        self.logger.error(
                            f"鼠标按下失败：{exc}",
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            f"流程 {chain_index}：鼠标按下失败"
                        )
                        return False

                elif (
                    step.module_type
                    == "mouse_release"
                ):
                    try:
                        completed = self.mouse_action_engine.release(
                            step.mouse_button,
                            stop_requested=module_cancelled,
                        )

                        if self._stop_event.is_set():
                            return False

                        if not completed:
                            return False

                        button_name = {
                            "left": "左键",
                            "right": "右键",
                            "middle": "中键",
                        }.get(str(step.mouse_button), "左键")
                        message = (
                            f"流程 {chain_index}："
                            f"鼠标抬起 · {button_name}"
                        )

                        self.logger.info(
                            message,
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            message
                        )

                    except Exception as exc:
                        self.logger.error(
                            f"鼠标抬起失败：{exc}",
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            f"流程 {chain_index}：鼠标抬起失败"
                        )
                        return False

                elif (
                    step.module_type
                    == "click"
                ):
                    try:
                        if step.click_advanced:
                            press_duration = (
                                step.click_press_duration
                            )
                            interval = (
                                step.click_interval
                            )
                        else:
                            # Stable short press and repeat interval. Even normal
                            # Click remains explicit DOWN -> UP internally.
                            press_duration = 0.025
                            interval = 0.100

                        completed = (
                            self.mouse_action_engine.click(
                                ClickOptions(
                                    count=max(
                                        1,
                                        int(
                                            step.click_count
                                        ),
                                    ),
                                    press_duration=max(
                                        0.0,
                                        float(
                                            press_duration
                                        ),
                                    ),
                                    interval=max(
                                        0.0,
                                        float(
                                            interval
                                        ),
                                    ),
                                ),
                                stop_requested=(
                                    module_cancelled
                                ),
                            )
                        )

                        if self._stop_event.is_set():
                            return False

                        # Click does not destroy coordinate data from a preceding
                        # scan/move, so downstream modules may still reuse it.
                        message = (
                            f"流程 {chain_index}："
                            f"点击 × {completed}"
                        )

                        self.logger.info(
                            message,
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            message
                        )

                    except Exception as exc:
                        self.logger.error(
                            f"点击失败：{exc}",
                            source="mouse",
                        )
                        self.runtime_signals.message.emit(
                            f"流程 {chain_index}：点击失败"
                        )
                        return False

                elif step.module_type == "drag":
                    start_coordinate = context.get("last_output")
                    start_space = context.get("last_output_space")

                    if (
                        not isinstance(start_coordinate, (tuple, list))
                        or len(start_coordinate) < 2
                    ):
                        message = (
                            f"流程 {chain_index}："
                            "拖动需要上一个模块提供起点坐标。"
                        )
                        self.logger.warning(message, source="mouse")
                        self.runtime_signals.message.emit(message)
                        return False

                    if start_space != "global_screen":
                        message = (
                            f"流程 {chain_index}："
                            "拖动拒绝非全局屏幕起点坐标。"
                        )
                        self.logger.warning(message, source="mouse")
                        self.runtime_signals.message.emit(message)
                        return False

                    try:
                        start_x = float(start_coordinate[0])
                        start_y = float(start_coordinate[1])
                    except (TypeError, ValueError, OverflowError):
                        self.runtime_signals.message.emit(
                            f"流程 {chain_index}：拖动起点坐标无效"
                        )
                        return False

                    drag_mode = str(
                        getattr(
                            step,
                            "drag_mode",
                            "coordinate_to_coordinate",
                        )
                    )

                    if drag_mode == "coordinate_drag_pixels":
                        end_x = start_x + float(step.drag_pixels_x)
                        end_y = start_y + float(step.drag_pixels_y)
                    else:
                        if step.drag_end_from_input:
                            if not step.drag_end_steps:
                                message = (
                                    f"流程 {chain_index}："
                                    "复杂模式拖动缺少终点坐标输入。"
                                )
                                self.logger.warning(message, source="mouse")
                                self.runtime_signals.message.emit(message)
                                return False

                            end_context = dict(context)
                            # The auxiliary endpoint branch must produce its own
                            # coordinate rather than inheriting the start value.
                            end_context["last_output"] = None
                            end_context["last_output_space"] = None
                            if not self._execute_steps(
                                chain_index,
                                step.drag_end_steps,
                                end_context,
                                active_roi,
                                selection_anchor=selection_anchor,
                                ignore_event_chain_cancel=ignore_event_chain_cancel,
                                local_cancel_event=local_cancel_event,
                            ):
                                return False
                            end_coordinate = end_context.get("last_output")
                            end_space = end_context.get("last_output_space")
                            if (
                                not isinstance(end_coordinate, (tuple, list))
                                or len(end_coordinate) < 2
                                or end_space != "global_screen"
                            ):
                                message = (
                                    f"流程 {chain_index}："
                                    "拖动终点输入没有输出全局屏幕坐标。"
                                )
                                self.logger.warning(message, source="mouse")
                                self.runtime_signals.message.emit(message)
                                return False
                            end_x = float(end_coordinate[0])
                            end_y = float(end_coordinate[1])
                        else:
                            # Simple mode: endpoint is configured manually.
                            end_x = float(step.drag_end_x)
                            end_y = float(step.drag_end_y)

                    opts = MoveOptions(
                        offset_up=step.move_offset_up if step.move_advanced else 0.0,
                        offset_down=step.move_offset_down if step.move_advanced else 0.0,
                        offset_left=step.move_offset_left if step.move_advanced else 0.0,
                        offset_right=step.move_offset_right if step.move_advanced else 0.0,
                        speed_mode=step.move_speed_mode if step.move_advanced else "duration",
                        speed_value=step.move_speed_value if step.move_advanced else 0.0,
                        speed_variance=step.move_speed_variance if step.move_advanced else 0.0,
                        random_route=step.move_random_route if step.move_advanced else False,
                    )
                    final = self.mouse_action_engine.drag(
                        start_x,
                        start_y,
                        end_x,
                        end_y,
                        options=opts,
                        press_duration=step.drag_press_duration,
                        stop_requested=module_cancelled,
                    )
                    context["last_output"] = final
                    context["last_output_space"] = "global_screen"
                    mode_text = (
                        f"像素偏移 ({step.drag_pixels_x:+g}, {step.drag_pixels_y:+g})"
                        if drag_mode == "coordinate_drag_pixels"
                        else "坐标至坐标"
                    )
                    self.logger.info(
                        f"流程 {chain_index}：拖动 {mode_text} "
                        f"({start_x:g}, {start_y:g}) → {final}",
                        source="mouse",
                    )

                elif step.module_type == "keyboard_input":
                    stop_requested = (
                        module_cancelled
                    )

                    if step.key_text_mode:
                        done = (
                            self.keyboard_action_engine
                            .type_text(
                                step.key_text,
                                interval=step.key_interval,
                                interval_variance=(
                                    step.key_interval_variance
                                    if step.key_advanced
                                    else 0.0
                                ),
                                humanized=(
                                    step.key_humanized
                                    if step.key_advanced
                                    else False
                                ),
                                stop_requested=stop_requested,
                            )
                        )

                        completed_text = (
                            step.key_text[:done]
                        )
                        settle_seconds = (
                            self.keyboard_action_engine
                            .recommended_text_settle_delay(
                                completed_text
                            )
                        )

                        self.logger.info(
                            (
                                f"流程 {chain_index}："
                                f"文本输入 {done} 字符 · "
                                f"自动处理缓冲 {settle_seconds * 1000:.0f} ms "
                                "(+ 下一模块固定 5 ms)"
                            ),
                            source="keyboard",
                        )

                        if settle_seconds > 0:
                            settle_end=(
                                time.perf_counter()
                                + settle_seconds
                            )

                            while (
                                time.perf_counter()
                                < settle_end
                            ):
                                if module_cancelled():
                                    return False

                                time.sleep(
                                    min(
                                        0.005,
                                        max(
                                            0.0,
                                            settle_end
                                            - time.perf_counter(),
                                        ),
                                    )
                                )
                    else:
                        opts = KeyboardOptions(
                            mode=step.key_mode,
                            count=step.key_count,
                            interval=step.key_interval,
                            hold_duration=(
                                step.key_hold_duration
                            ),
                            duration_variance=(
                                step.key_duration_variance
                                if step.key_advanced
                                else 0.0
                            ),
                            interval_variance=(
                                step.key_interval_variance
                                if step.key_advanced
                                else 0.0
                            ),
                            humanized=(
                                step.key_humanized
                                if step.key_advanced
                                else False
                            ),
                        )

                        done = (
                            self.keyboard_action_engine
                            .press_key(
                                step.key_name,
                                options=opts,
                                stop_requested=(
                                    stop_requested
                                ),
                            )
                        )

                        self.logger.info(
                            (
                                f"流程 {chain_index}："
                                f"键盘 {step.key_name} "
                                f"× {done}"
                            ),
                            source="keyboard",
                        )

                elif step.module_type == "launch_exe":
                    path=os.path.expandvars(os.path.expanduser(step.executable_path.strip()))
                    if not path:return False
                    try:
                        subprocess.Popen([path],cwd=str(Path(path).parent) if Path(path).parent.exists() else None)
                        self.logger.info(f"流程 {chain_index}：已启动 {path}",source="process")
                    except Exception as exc:
                        self.logger.error(f"启动程序失败：{exc}",source="process"); return False

                elif step.module_type == "delay_wait":
                    seconds=self._duration_seconds(step.delay_value,step.delay_unit)
                    self.logger.info(f"流程 {chain_index}：延时等待 {seconds:.3f}s",source="runtime")
                    end_time = time.perf_counter() + seconds
                    while time.perf_counter() < end_time:
                        if module_cancelled():
                            return False
                        time.sleep(
                            min(
                                0.02,
                                max(
                                    0.0,
                                    end_time - time.perf_counter(),
                                ),
                            )
                        )

                elif (
                    step.module_type
                    == "inspect_input"
                ):
                    value = context.get(
                        "last_output"
                    )
                    value_space = context.get(
                        "last_output_space"
                    )

                    python_type = type(
                        value
                    ).__name__

                    if value_space is None:
                        space_text = "未标记"
                    else:
                        space_text = str(
                            value_space
                        )

                    # Report the ACTUAL resolved recognition/execution viewport,
                    # not the ROI module's stored anchor-relative offsets.
                    global_roi = context.get(
                        "global_recognition_roi"
                    )

                    effective_debug_roi = intersect_roi(
                        active_roi,
                        global_roi,
                    )

                    if (
                        active_roi is not None
                        and global_roi is not None
                        and effective_debug_roi is None
                    ):
                        roi_text = "无交集"
                    elif effective_debug_roi is None:
                        roi_text = "全屏"
                    else:
                        roi_x, roi_y, roi_w, roi_h = (
                            effective_debug_roi
                        )

                        if (
                            active_roi is None
                            and global_roi is not None
                        ):
                            roi_source = "全局"
                        elif (
                            active_roi is not None
                            and global_roi is None
                        ):
                            roi_source = "局部"
                        elif (
                            active_roi is not None
                            and global_roi is not None
                        ):
                            roi_source = "交集"
                        else:
                            roi_source = "有效"

                        roi_text = (
                            f"{roi_source}"
                            f"({roi_x}, {roi_y}, "
                            f"{roi_w}×{roi_h})"
                        )

                    message = (
                        f"流程 {chain_index}："
                        f"检测输入 → "
                        f"值={value!r} · "
                        f"类型={python_type} · "
                        f"数据标记={space_text} · "
                        f"ROI={roi_text}"
                    )

                    self.logger.info(
                        message,
                        source="debug",
                    )
                    self.runtime_signals.message.emit(
                        message
                    )

                    # Transparent pass-through: do not modify last_output or
                    # last_output_space, so downstream modules receive exactly
                    # the same value.
                    continue

                elif (
                    step.module_type
                    == "placeholder"
                ):
                    self.logger.info(
                        (
                            f"流程 {chain_index}："
                            f"执行 {step.label}；"
                            f"输入="
                            f"{context['last_output']!r}"
                        ),
                        source="workspace",
                    )

            return True

    def _on_runtime_message(
            self,
            message: str,
        ) -> None:
            self.runtime_status.setText(
                message
            )

    def _on_chain_finished(
            self,
        ) -> None:
            # Stop may have already zeroed the counter.
            if self._stop_event.is_set():
                return

            self._active_chains = max(
                0,
                self._active_chains - 1,
            )

            if self._active_chains != 0:
                return

            if self._global_runtime_active:
                self.run_button.setEnabled(
                    False
                )
                self.stop_button.setEnabled(
                    True
                )
                self.runtime_status.setText(
                    tr_text(
                        "普通流程完成 · 全局设置持续运行中"
                    )
                )
            else:
                self.run_button.setEnabled(
                    True
                )
                self.stop_button.setEnabled(
                    False
                )
                self.runtime_status.setText(
                    tr_text(
                        "运行完成"
                    )
                )

