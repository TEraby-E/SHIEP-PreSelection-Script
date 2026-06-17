from dataclasses import dataclass, field


@dataclass
class ScanResult:
    proxy: str
    username: str
    cookies: list = field(default_factory=list)
    grades: list = field(default_factory=list)
    plan_credits: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def add_error(self, msg: str) -> None:
        """Append an error without clobbering an earlier (usually more important) one."""
        if not msg:
            return
        self.error = msg if not self.error else f"{self.error}; {msg}"
