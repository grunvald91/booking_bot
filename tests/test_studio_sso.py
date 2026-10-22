"""Sign-in bridge to the marketing studio: who gets a link, what the link says, and instant revocation."""
import os
os.environ.setdefault('BOT_TOKEN', 'test-token')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///:memory:')

import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User, Business, BusinessOwner, Employee
from web.api.database import get_db
from web.api.deps import get_current_admin, get_current_user
from web.api.routes import admin, studio_sso

SSO = 's' * 40
KEY = 'k' * 40


def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def read_ticket(url, secret=SSO):
    token = url.split('?t=', 1)[1]
    payload, signature = token.split('.')
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    assert hmac.compare_digest(signature, expected), 'bad signature'
    return json.loads(unb64(payload))


class StudioSsoTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = mock.patch.dict(os.environ, {'STUDIO_SSO_SECRET': SSO, 'STUDIO_INTERNAL_KEY': KEY})
        self.env.start()
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.sessions() as db:
            users = {name: User(telegram_id=1000 + i, full_name=name) for i, name in enumerate(
                ['owner', 'co', 'stranger', 'admin', 'inactive', 'master'])}
            db.add_all(users.values()); await db.flush()
            self.u = {name: user.id for name, user in users.items()}
            business = Business(owner_id=users['owner'].id, name='Салон', business_type='salon', is_active=True)
            db.add(business); await db.flush()
            self.business_id = business.id
            db.add(BusinessOwner(business_id=business.id, user_id=users['co'].id, role='co_owner'))
            db.add_all([
                Employee(business_id=business.id, name='A', role='administrator', is_active=True, telegram_id=users['admin'].telegram_id),
                Employee(business_id=business.id, name='I', role='administrator', is_active=False, telegram_id=users['inactive'].telegram_id),
                Employee(business_id=business.id, name='M', role='master', is_active=True, telegram_id=users['master'].telegram_id),
            ])
            await db.commit()
        self.current = 'owner'
        app = FastAPI()
        app.include_router(studio_sso.router)
        app.include_router(admin.router, prefix='/admin')

        async def user():
            async with self.sessions() as db:
                return await db.get(User, self.u[self.current])

        async def session():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_current_user] = user
        app.dependency_overrides[get_current_admin] = user
        app.dependency_overrides[get_db] = session
        self.client = TestClient(app)

    async def asyncTearDown(self):
        self.client.close(); await self.engine.dispose(); self.env.stop()

    def ticket(self, who):
        self.current = who
        return self.client.post('/studio/ticket', json={'business_id': self.business_id})

    async def set_flag(self, value):
        async with self.sessions() as db:
            (await db.get(Business, self.business_id)).studio_admin_access = value
            await db.commit()

    def access(self, who, key=KEY, business_id=None):
        return self.client.get('/internal/studio/access', headers={'X-Studio-Key': key},
                               params={'user_id': self.u[who], 'business_id': business_id or self.business_id})

    async def test_owner_gets_a_signed_short_lived_link(self):
        response = self.ticket('owner')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['url'].startswith('https://growth.servgo.ru/studio/sso?t='))
        claims = read_ticket(body['url'])
        self.assertEqual((claims['uid'], claims['biz'], claims['role'], claims['aud']),
                         (self.u['owner'], self.business_id, 'owner', 'growth-studio'))
        self.assertLessEqual(claims['exp'] - time.time(), 60)
        self.assertGreater(claims['exp'] - time.time(), 50)

    async def test_every_link_is_unique(self):
        first = read_ticket(self.ticket('owner').json()['url'])['jti']
        second = read_ticket(self.ticket('owner').json()['url'])['jti']
        self.assertNotEqual(first, second)

    async def test_link_signed_with_another_secret_does_not_verify(self):
        url = self.ticket('owner').json()['url']
        with self.assertRaises(AssertionError):
            read_ticket(url, secret='x' * 40)

    async def test_co_owner_is_allowed_stranger_is_not(self):
        self.assertEqual(read_ticket(self.ticket('co').json()['url'])['role'], 'co_owner')
        self.assertEqual(self.ticket('stranger').status_code, 403)

    async def test_administrator_needs_the_owner_switch(self):
        self.assertEqual(self.ticket('admin').status_code, 403)
        await self.set_flag(True)
        response = self.ticket('admin')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read_ticket(response.json()['url'])['role'], 'administrator')

    async def test_inactive_administrator_and_master_never_get_in(self):
        await self.set_flag(True)
        self.assertEqual(self.ticket('inactive').status_code, 403)
        self.assertEqual(self.ticket('master').status_code, 403)

    async def test_unknown_business_is_refused(self):
        self.current = 'owner'
        self.assertEqual(self.client.post('/studio/ticket', json={'business_id': 99999}).status_code, 403)

    async def test_without_secrets_nothing_works(self):
        with mock.patch.dict(os.environ, {'STUDIO_SSO_SECRET': '', 'STUDIO_INTERNAL_KEY': ''}):
            self.assertEqual(self.ticket('owner').status_code, 503)
            self.assertEqual(self.access('owner').status_code, 503)

    async def test_short_secrets_are_not_accepted(self):
        with mock.patch.dict(os.environ, {'STUDIO_SSO_SECRET': 'short'}):
            self.assertEqual(self.ticket('owner').status_code, 503)

    async def test_internal_check_requires_the_key(self):
        self.assertEqual(self.access('owner', key='wrong').status_code, 403)
        self.assertEqual(self.client.get('/internal/studio/access',
                                         params={'user_id': 1, 'business_id': 1}).status_code, 403)
        self.assertEqual(self.access('owner').json(), {'allowed': True, 'role': 'owner'})

    async def test_internal_check_follows_the_switch_immediately(self):
        await self.set_flag(True)
        self.assertEqual(self.access('admin').json(), {'allowed': True, 'role': 'administrator'})
        await self.set_flag(False)
        self.assertEqual(self.access('admin').json(), {'allowed': False, 'role': None})

    async def test_internal_check_follows_removal_of_the_employee(self):
        await self.set_flag(True)
        async with self.sessions() as db:
            employee = await db.scalar(__import__('sqlalchemy').select(Employee).where(Employee.name == 'A'))
            employee.is_active = False
            await db.commit()
        self.assertFalse(self.access('admin').json()['allowed'])

    async def test_internal_check_for_other_business_is_denied(self):
        self.assertFalse(self.access('owner', business_id=424242).json()['allowed'])
        self.assertFalse(self.access('stranger').json()['allowed'])

    async def test_only_owners_can_change_the_switch(self):
        self.current = 'owner'
        response = self.client.put(f'/admin/businesses/{self.business_id}', json={'studio_admin_access': True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['studio_admin_access'])
        self.assertTrue(self.access('admin').json()['allowed'])
        detail = self.client.get(f'/admin/businesses/{self.business_id}/detail').json()
        self.assertTrue(detail['studio_admin_access'])

    async def test_the_switch_is_off_by_default(self):
        detail = self.client.get(f'/admin/businesses/{self.business_id}/detail').json()
        self.assertFalse(detail['studio_admin_access'])


if __name__ == '__main__':
    unittest.main()
