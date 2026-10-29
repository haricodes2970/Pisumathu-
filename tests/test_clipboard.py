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
