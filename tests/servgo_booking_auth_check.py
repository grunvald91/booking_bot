from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _bundle_text() -> str:
    index = (ROOT / "web" / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'src="/assets/([^"]+\.js)"', index)
    assert match
    return (ROOT / "web" / "frontend" / "dist" / "assets" / match.group(1)).read_text(encoding="utf-8")


def test_authenticated_webapp_booking_does_not_require_client_phone():
    bundle = _bundle_text()

    assert "disabled:pe||!ce||!N&&!localStorage.getItem(`token`)&&!window.Telegram?.WebApp?.initData" in bundle
    assert "client_phone:N||void 0" in bundle
    assert "localStorage.getItem(`userName`)||``" in bundle
    assert "window.addEventListener(`servgo:auth`" in bundle
    assert "t?.user?.full_name&&le" in bundle


if __name__ == "__main__":
    test_authenticated_webapp_booking_does_not_require_client_phone()
