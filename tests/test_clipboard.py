from pisumathu.output.base import ClipboardBackend
from pisumathu.output.clipboard import Clipboard, NullClipboard


class Recording(ClipboardBackend):
    name = "recording"

    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[str] = []

    def copy(self, text: str) -> bool:
        self.calls.append(text)
        return self.result


class Exploding(ClipboardBackend):
    name = "exploding"

    def copy(self, text: str) -> bool:
        raise RuntimeError("backend exploded")


def test_empty_text_is_not_copied():
    backend = Recording()
    clipboard = Clipboard(backend)
    assert clipboard.copy("") is False
    assert clipboard.copy("   \n ") is False
    assert backend.calls == []


def test_successful_copy_reaches_backend():
    backend = Recording()
    clipboard = Clipboard(backend)
    assert clipboard.copy("hello world") is True
    assert backend.calls == ["hello world"]


def test_backend_failure_propagates():
    clipboard = Clipboard(Recording(result=False))
    assert clipboard.copy("hello") is False


def test_backend_exception_is_contained():
    clipboard = Clipboard(Exploding())
    assert clipboard.copy("hello") is False


def test_null_backend_reports_unavailable():
    clipboard = Clipboard(NullClipboard())
    assert clipboard.available is False
    assert clipboard.copy("hello") is False


def test_backend_name_exposed():
    assert Clipboard(Recording()).backend == "recording"


class ChainClipboard(Clipboard):
    """Clipboard with an explicit backend chain."""

    def __init__(self, *backends: ClipboardBackend) -> None:
        self._backends = list(backends)
        self._used = None


def test_falls_back_when_the_first_backend_fails():
    primary = Recording(result=False)
    primary.name = "linux-wl-copy"
    fallback = Recording()
    fallback.name = "linux-xsel"

    clipboard = ChainClipboard(primary, fallback)

    assert clipboard.copy("hello") is True
    assert primary.calls == ["hello"]
    assert fallback.calls == ["hello"]
    assert clipboard.backend == "linux-xsel"


def test_falls_back_when_the_first_backend_raises():
    fallback = Recording()
    fallback.name = "linux-xsel"

    clipboard = ChainClipboard(Exploding(), fallback)

    assert clipboard.copy("hello") is True
    assert fallback.calls == ["hello"]


def test_reports_failure_when_every_backend_fails():
    first = Recording(result=False)
    second = Recording(result=False)
    clipboard = ChainClipboard(first, second)

    assert clipboard.copy("hello") is False


def test_unavailable_backend_is_skipped():
    fallback = Recording()
    fallback.name = "linux-xsel"
    clipboard = ChainClipboard(NullClipboard(), fallback)

    assert clipboard.copy("hello") is True
    assert clipboard.backend == "linux-xsel"


def test_backend_name_is_the_one_that_worked():
    backend = Recording()
    backend.name = "linux-wl-copy"
    clipboard = ChainClipboard(backend)

    assert clipboard.backend == "linux-wl-copy"
    clipboard.copy("hello")
    assert clipboard.backend == "linux-wl-copy"


def test_clear_falls_through_the_chain():
    first = Recording(result=False)
    second = Recording(result=True)
    clipboard = ChainClipboard(first, second)

    assert clipboard.clear() is True
    assert first.calls == [""]
    assert second.calls == [""]
