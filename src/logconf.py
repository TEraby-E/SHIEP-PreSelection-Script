import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once. Account name goes in the message via LoggerAdapter."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def account_logger(username: str) -> logging.LoggerAdapter:
    """A logger that prefixes every line with [username] so concurrent output stays readable."""
    base = logging.getLogger("preselect")
    return logging.LoggerAdapter(base, {"user": username})


# Patch the adapter to actually render the prefix.
class _PrefixAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['user']}] {msg}", kwargs


def account_logger(username: str) -> logging.LoggerAdapter:  # noqa: F811
    return _PrefixAdapter(logging.getLogger("preselect"), {"user": username})
