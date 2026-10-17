#!/usr/bin/env python3
"""Disabled accounts cannot authenticate, use old tokens, or lose their history."""
import argparse
import os
from unittest.mock import patch

from integration import server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with patch.dict(os.environ, {'LINKCONTEXT_GOOGLE_CLIENT_ID': 'synthetic-client',
                                 'LINKCONTEXT_GOOGLE_CLIENT_SECRET': 'synthetic-secret'}), server(args.binary) as request:
        admin = request('POST', '/api/collections/_superusers/auth-with-password', {
            'identity': 'admin@example.com', 'password': 'SyntheticAdminPassword123!',
        })['token']
        collections = request('GET', '/api/collections', token=admin)['items']
        assert {c['name'] for c in collections if c['type'] == 'auth'} == {'_superusers', 'users'}
        assert next(c for c in collections if c['name'] == 'users')['id'] == '_pb_users_auth_'
        settings = request('GET', '/api/collections/users', token=admin)
        assert settings['createRule'] == "@request.context = 'oauth2'" and settings['authToken']['duration'] == 604800
        assert settings['oauth2']['enabled']
        assert any(p['name'] == 'google' and p['clientId'] == 'synthetic-client' for p in settings['oauth2']['providers'])
        credentials = {'identity': 'member@example.test', 'password': 'SyntheticMemberPassword123!'}
        user = request('POST', '/api/collections/users/records', {
            'email': credentials['identity'], 'name': 'Member', 'password': credentials['password'],
            'passwordConfirm': credentials['password'],
        }, admin)
        request('POST', '/api/collections/users/records', {
            'id': 'dirfailure00001', 'email': 'directory-failure@example.test', 'name': 'Failure',
            'password': credentials['password'], 'passwordConfirm': credentials['password'],
        }, admin, expected=(400, 500))
        request('GET', '/api/collections/users/records/dirfailure00001', token=admin, expected=404)
        path = '/api/collections/users/records/' + user['id']
        token = request('POST', '/api/collections/users/auth-with-password', credentials)['token']
        company = request('POST', '/api/collections/companies/records', {'name': 'Access test'}, token)
        company_path = '/api/collections/companies/records/' + company['id']
        # Users cannot manage their own access state, even if submitting the current value.
        for value in (True, False):
            request('PATCH', path, {'disabled': value}, token, expected=(400, 403, 404))
            request('POST', '/api/batch', {'requests': [
                {'method': 'PATCH', 'url': path, 'body': {'disabled': value}},
            ]}, token, expected=(400, 403))
        request('DELETE', path, token=admin, expected=(400, 403))
        request('PATCH', path, {'disabled': True}, admin)

        def rejected(old_token):
            for method, endpoint, body in [
                ('GET', '/api/context/schema', None),
                ('POST', '/api/context/query', {'sql': 'SELECT * FROM companies'}),
                ('GET', '/api/collections/companies/records', None),
                ('GET', company_path, None),
                ('POST', '/api/collections/companies/records', {'name': 'Forbidden'}),
                ('PATCH', company_path, {'name': 'Forbidden', 'expected_revision': company['revision']}),
                ('GET', path, None),
                ('POST', '/api/collections/users/auth-refresh', None),
                ('POST', '/api/files/token', None),
                ('POST', '/api/batch', {'requests': [
                    {'method': 'POST', 'url': '/api/collections/companies/records', 'body': {'name': 'Forbidden'}},
                ]}),
            ]:
                request(method, endpoint, body, old_token, expected=(400, 401, 403, 404))

        rejected(token)
        request('POST', '/api/collections/users/auth-with-password', credentials, expected=(400, 401, 403))
        disabled = request('GET', path, token=admin)
        assert disabled['disabled'] and disabled['id'] == user['id']
        assert request('GET', company_path, token=admin)['name'] == 'Access test'
        assert request('GET', '/api/collections/user_directory/records/' + user['id'], token=admin)['name'] == 'Member'
        # Re-enabling does not resurrect previously issued tokens.
        request('PATCH', path, {'disabled': False}, admin)
        rejected(token)
        fresh = request('POST', '/api/collections/users/auth-with-password', credentials)['token']
        request('GET', '/api/context/schema', token=fresh)
        assert request('GET', company_path, token=fresh)['created_by'] == user['id']
        assert request('GET', '/api/collections/companies/records', token=admin)['totalItems'] == 1
    print('PASS: disabled accounts reject authentication and old REST/SQL tokens; identity and attribution preserved')


if __name__ == '__main__':
    main()
