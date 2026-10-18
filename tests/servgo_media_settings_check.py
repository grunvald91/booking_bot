from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_settings_loads_entity_media_manager():
    index = (ROOT / "web" / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
    script = ROOT / "web" / "frontend" / "dist" / "servgo-media-settings.js"

    assert "/servgo-media-settings.js" in index
    assert script.exists()


def test_entity_media_manager_uses_employee_photo_api():
    text = (ROOT / "web" / "frontend" / "dist" / "servgo-media-settings.js").read_text(encoding="utf-8")

    assert "servgo-entity-media-settings" in text
    assert "/admin/businesses/${businessId}/employees?include_inactive=true" in text
    assert "/admin/businesses/${businessId}/employees/${employeeId}/photo" in text
    assert "/api/telegram-photo/${encodeURIComponent(fileId)}" in text
    assert "Фото залов" in text
    assert "Фото специалистов" in text


def test_business_detail_bundle_displays_employee_photos():
    index = (ROOT / "web" / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'src="/assets/([^"]+\.js)"', index)

    assert match

    bundle = (ROOT / "web" / "frontend" / "dist" / "assets" / match.group(1)).read_text(encoding="utf-8")

    assert ".employees.map" in bundle
    assert ".photos)[0]" in bundle
    assert "/api/telegram-photo/${encodeURIComponent(n)}" in bundle
    assert "w-full h-64 object-cover snap-start shrink-0" in bundle


if __name__ == "__main__":
    test_settings_loads_entity_media_manager()
    test_entity_media_manager_uses_employee_photo_api()
    test_business_detail_bundle_displays_employee_photos()
