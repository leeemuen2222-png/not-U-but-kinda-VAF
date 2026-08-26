from __future__ import annotations

import inspect


_REQUIRED_RUNTIME_METHODS = (
    "run_workflows",
    "stop_workflows",
    "_launch_chains",
    "_execute_steps",
    "_execute_chain",
    "_activate_global_steps",
    "_on_runtime_message",
    "_on_chain_finished",
    "_on_clock_expired",
)

_REQUIRED_RUNTIME_STATE = (
    "_stop_event",
    "_event_chain_cancel",
    "_runtime_lock",
    "_active_chains",
    "_global_runtime_active",
)


def validate_workspace_runtime_contract(workspace: object) -> None:
    """Fail early when a workspace/runtime refactor breaks method binding.

    PySide/Qt can make exceptions raised from signal callbacks look like a
    button simply did nothing.  This validation deliberately runs before the
    Run button is wired so structural mistakes are reported at startup with a
    precise message.
    """

    cls = type(workspace)

    # The original regression that disabled Run was an orphaned @staticmethod
    # left in WorkspacePage when _duration_seconds moved to ModuleRuntimeMixin.
    raw_run = inspect.getattr_static(
        cls,
        "run_workflows",
        None,
    )
    if isinstance(raw_run, staticmethod):
        raise RuntimeError(
            "Workspace runtime contract broken: run_workflows must be an "
            "instance method, not staticmethod."
        )

    bound_run = getattr(
        workspace,
        "run_workflows",
        None,
    )
    if not inspect.ismethod(bound_run):
        raise RuntimeError(
            "Workspace runtime contract broken: run_workflows is not bound "
            "to the WorkspacePage instance."
        )

    missing_methods = [
        name
        for name in _REQUIRED_RUNTIME_METHODS
        if not callable(
            getattr(
                workspace,
                name,
                None,
            )
        )
    ]
    if missing_methods:
        raise RuntimeError(
            "Workspace runtime contract broken: missing runtime methods: "
            + ", ".join(missing_methods)
        )

    missing_state = [
        name
        for name in _REQUIRED_RUNTIME_STATE
        if not hasattr(
            workspace,
            name,
        )
    ]
    if missing_state:
        raise RuntimeError(
            "Workspace runtime contract broken: missing runtime state: "
            + ", ".join(missing_state)
        )
