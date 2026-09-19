"""Action execution errors mapped to action_result entries."""


class ActionError(Exception):
    """Base error for action execution."""

    pass


class MethodNotFoundError(ActionError):
    """Error when a command or request is not found."""

    pass


class ArgumentError(ActionError):
    """Error due to invalid arguments for an action."""

    pass


class ExecutionError(ActionError):
    """Error during execution in Telegram's API."""

    pass
