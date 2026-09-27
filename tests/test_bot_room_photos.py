"""Regression tests for room photos in the Telegram owner flow."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot.handlers import admin
from bot.states import EmployeeEditStates


def _session(monkeypatch, employee, *, owner=True):
    import database.crud as crud

    session = MagicMock()
    session.commit = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(admin, "async_session_maker", lambda: context)
    monkeypatch.setattr(crud, "get_employee_by_id", AsyncMock(return_value=employee))
    monkeypatch.setattr(admin, "get_user_by_telegram_id", AsyncMock(return_value=SimpleNamespace(id=71)))
    monkeypatch.setattr(admin, "is_business_owner", AsyncMock(return_value=owner))
    return session


def _callback(data="edit_emp_photos:39"):
    callback = SimpleNamespace(data=data, from_user=SimpleNamespace(id=437862772))
    callback.message = SimpleNamespace(edit_text=AsyncMock())
    callback.answer = AsyncMock()
    return callback


def test_open_room_photo_menu_accepts_next_photo_without_extra_button(monkeypatch):
    employee = SimpleNamespace(id=39, business_id=11, name="Test room", photos=None)
    _session(monkeypatch, employee)
    state = SimpleNamespace(update_data=AsyncMock(), set_state=AsyncMock())
    callback = _callback()

    asyncio.run(admin.edit_emp_photos_menu(callback, state))

    state.update_data.assert_awaited_once_with(editing_employee_id=39)
    state.set_state.assert_awaited_once_with(EmployeeEditStates.adding_photo)
    callback.message.edit_text.assert_awaited_once()


def test_add_photo_button_prompts_instead_of_name_error(monkeypatch):
    employee = SimpleNamespace(id=39, business_id=11, name="Test room", photos=None)
    _session(monkeypatch, employee)
    state = SimpleNamespace(update_data=AsyncMock(), set_state=AsyncMock())
    callback = _callback("emp_add_photo:39")

    asyncio.run(admin.emp_add_photo_start(callback, state))

    callback.message.edit_text.assert_awaited_once()
    state.set_state.assert_awaited_once_with(EmployeeEditStates.adding_photo)


def test_add_photo_button_rejects_non_owner(monkeypatch):
    employee = SimpleNamespace(id=39, business_id=11, name="Other owner's room", photos=None)
    _session(monkeypatch, employee, owner=False)
    state = SimpleNamespace(update_data=AsyncMock(), set_state=AsyncMock())
    callback = _callback("emp_add_photo:39")

    asyncio.run(admin.emp_add_photo_start(callback, state))

    callback.message.edit_text.assert_not_awaited()
    state.set_state.assert_not_awaited()
    callback.answer.assert_awaited_once()


def test_done_exits_room_photo_capture(monkeypatch):
    edit_employee = AsyncMock()
    monkeypatch.setattr(admin, "edit_employee_menu", edit_employee)
    monkeypatch.setattr(admin, "edit_emp_photos_menu", AsyncMock())
    callback = _callback("emp_photos_done:39")
    state = SimpleNamespace(clear=AsyncMock())

    asyncio.run(admin.emp_photos_done(callback, state))

    state.clear.assert_awaited_once()
    edit_employee.assert_awaited_once_with(callback)


def test_back_exits_room_photo_capture(monkeypatch):
    edit_employee = AsyncMock()
    monkeypatch.setattr(admin, "edit_employee_menu", edit_employee)
    callback = _callback("emp_photos_back:39")
    state = SimpleNamespace(clear=AsyncMock())

    asyncio.run(admin.emp_photos_back(callback, state))

    state.clear.assert_awaited_once()
    edit_employee.assert_awaited_once_with(callback)


def test_room_photo_menu_rejects_non_owner(monkeypatch):
    employee = SimpleNamespace(id=39, business_id=11, name="Other owner's room", photos=None)
    _session(monkeypatch, employee, owner=False)
    state = SimpleNamespace(update_data=AsyncMock(), set_state=AsyncMock())
    callback = _callback()

    asyncio.run(admin.edit_emp_photos_menu(callback, state))

    callback.message.edit_text.assert_not_awaited()
    state.set_state.assert_not_awaited()
    callback.answer.assert_awaited_once()


def test_room_photo_receive_rejects_non_owner_without_database_write(monkeypatch):
    employee = SimpleNamespace(id=39, business_id=11, name="Other owner's room", photos=None)
    session = _session(monkeypatch, employee, owner=False)
    monkeypatch.setattr(admin, "_save_photo_to_cache", AsyncMock(return_value=True))
    message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="fake-test-file-id")],
        from_user=SimpleNamespace(id=437862772),
        bot=MagicMock(),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(get_data=AsyncMock(return_value={"editing_employee_id": 39}), clear=AsyncMock())

    asyncio.run(admin.emp_add_photo_receive(message, state))

    session.commit.assert_not_awaited()
    assert employee.photos is None
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once()


def test_room_photo_receive_saves_authorized_photo_and_acknowledges(monkeypatch):
    employee = SimpleNamespace(id=39, business_id=11, name="Test room", photos=None)
    session = _session(monkeypatch, employee)
    cache = AsyncMock(return_value=True)
    monkeypatch.setattr(admin, "_save_photo_to_cache", cache)
    message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="fake-test-file-id")],
        from_user=SimpleNamespace(id=437862772),
        bot=MagicMock(),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(get_data=AsyncMock(return_value={"editing_employee_id": 39}))

    asyncio.run(admin.emp_add_photo_receive(message, state))

    session.commit.assert_awaited_once()
    assert employee.photos == '["fake-test-file-id"]'
    cache.assert_awaited_once_with(message.bot, "fake-test-file-id")
    message.answer.assert_awaited_once()
