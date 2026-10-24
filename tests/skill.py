#!/usr/bin/env python3
"""Portable CLI against isolated application data, including stale-write rejection, idempotent upsert, and sync runs."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from integration import ROOT, server

parser = argparse.ArgumentParser()
parser.add_argument('--binary', required=True)
parser.add_argument('--client', help='Executable release launcher to exercise; package mutation checks still use the local test copy')
parser.add_argument('--write-schema', action='store_true')
args = parser.parse_args()

with server(args.binary) as request, tempfile.TemporaryDirectory(prefix='linkcontext-skill-') as tmp:
    admin = request('POST', '/api/collections/_superusers/auth-with-password', {'identity': 'admin@example.com', 'password': 'SyntheticAdminPassword123!'})['token']
    password = 'SyntheticSkillPassword123!'
    request('POST', '/api/collections/users/records', {'email': 'skill@example.com', 'name': 'Synthetic skill', 'password': password, 'passwordConfirm': password}, admin)
    token = request('POST', '/api/collections/users/auth-with-password', {'identity': 'skill@example.com', 'password': password})['token']
    schema = request('GET', '/api/context/schema', token=token)
    snapshot = ROOT / 'skills/linkcontext/references/schema.json'
    if args.write_schema:
        snapshot.write_text(json.dumps(schema, indent=2) + '\n')
        (ROOT / 'src/linkcontext_client/schema.json').write_text(snapshot.read_text())
    assert json.loads(snapshot.read_text()) == schema, 'Schema changed; review and regenerate snapshot'
    skill = Path(tmp) / 'portable'
    shutil.copytree(ROOT / 'skills/linkcontext', skill)
    env = {
        **{key: value for key, value in os.environ.items() if key != 'LINKCONTEXT_SESSION_DIR'},
        'UV_PYTHON': sys.executable,
        'UV_CACHE_DIR': str(Path(tmp) / 'uv-cache'),
        'HOME': tmp,
        'XDG_CACHE_HOME': str(Path(tmp) / 'cache'),
        'XDG_STATE_HOME': str(Path(tmp) / 'state'),
        'LINKCONTEXT_URL': request.base_url,
        'LINKCONTEXT_USER_EMAIL': 'skill@example.com',
        'LINKCONTEXT_USER_PASSWORD': password,
    }
    def cli(*argv, expected=0):
        command = [str(Path(args.client).resolve())] if args.client else [sys.executable, str(skill / 'linkcontext')]
        result = subprocess.run([*command, *argv], env=env, cwd=tmp, capture_output=True, text=True)
        assert password not in result.stdout + result.stderr and token not in result.stdout + result.stderr
        assert result.returncode == expected, (argv, result.stdout, result.stderr)
        return result.stdout

    cli('whoami')
    cli('check')

    # Standard CRUD & revision conflict checks
    comp = json.loads(cli('create', 'companies', '{"name":"Synthetic Ventures","universal_name":"synthetic-ventures"}'))
    row = json.loads(cli('get', 'companies', comp['id']))
    assert row['name'] == 'Synthetic Ventures'
    body = json.dumps({'tagline': 'Updated synthetic tagline', 'expected_revision': comp['revision']})
    cli('update', 'companies', comp['id'], body)
    cli('update', 'companies', comp['id'], body, expected=4)
    cli('update', 'companies', comp['id'], '{"tagline":"No revision"}', expected=2)
    cli('query', 'SELECT name FROM companies')
    cli('batch', json.dumps([{'method': 'POST', 'url': '/api/collections/companies/records', 'body': {'name': 'Batch synthetic company'}}]))
    cli('batch', json.dumps([{'method': 'POST', 'url': '/api/collections/users/records', 'body': {}}]), expected=2)

    # Deterministic ID check
    det_id_1 = cli('deterministic-id', 'profiles', 'jane-doe').strip()
    det_id_2 = cli('deterministic-id', 'profiles', 'jane-doe').strip()
    assert len(det_id_1) == 15 and det_id_1 == det_id_2

    # Sync run start -> Upsert deduplication & non-destructive merge -> Sync run finish
    sync_start = json.loads(cli('sync-start', 'feed', '--since', '7d', '--max-items', '25'))
    sync_id = sync_start['sync_run']['id']
    assert sync_start['lookback_since']

    profiles_payload = json.dumps([
        {
            'full_name': 'Jane Doe',
            'linkedin_url': 'https://www.linkedin.com/in/jane-doe/?miniProfileUrn=urn%3Ali%3Afs_miniProfile%3A123',
            'headline': 'VP Engineering at Synthetic Ventures',
            'about': 'Detailed bio from full profile scrape.',
            'completeness': 'full',
            'connection_degree': 'first',
        },
        {
            'full_name': 'Alex Smith',
            'public_id': 'alex-smith',
            'headline': 'Partner at Synthetic Capital',
            'completeness': 'card',
            'connection_degree': 'second',
        },
    ])
    up1 = json.loads(cli('upsert', 'profiles', profiles_payload, '--sync-run', sync_id))
    assert up1['created'] == 2 and up1['updated'] == 0 and up1['unchanged'] == 0
    assert up1['ids'][0] == det_id_1

    # Second identical upsert must be 100% no-op (unchanged == 2)
    up2 = json.loads(cli('upsert', 'profiles', profiles_payload, '--sync-run', sync_id))
    assert up2['created'] == 0 and up2['updated'] == 0 and up2['unchanged'] == 2
    jane_row = json.loads(cli('get', 'profiles', det_id_1))
    assert jane_row['revision'] == 1

    # Shallow card scrape with empty about must NOT overwrite full profile's about or downgrade completeness,
    # while still updating volatile/non-empty fields if needed, or updating when a newer field is provided
    shallow_payload = json.dumps([
        {
            'full_name': 'Jane Doe',
            'public_id': 'jane-doe',
            'headline': 'SVP Engineering at Synthetic Ventures',
            'about': '',
            'completeness': 'card',
            'follower_count': 4200,
        }
    ])
    up3 = json.loads(cli('upsert', 'profiles', shallow_payload, '--sync-run', sync_id))
    assert up3['created'] == 0 and up3['updated'] == 1
    jane_after = json.loads(cli('get', 'profiles', det_id_1))
    assert jane_after['completeness'] == 'full'
    assert jane_after['about'] == 'Detailed bio from full profile scrape.'
    assert jane_after['follower_count'] == 4200

    # Upsert posts with Snowflake URN timestamp extraction and --since cutoff filtering
    posts_payload = json.dumps([
        {
            'post_urn': 'urn:li:activity:7251234567890123456',
            'author_profile': det_id_1,
            'body': 'Recent post within cutoff',
            'published_at': '2026-10-16 12:00:00.000Z',
            'timestamp_precision': 'exact_urn',
        },
        {
            'post_urn': 'urn:li:activity:7000000000000000000',
            'author_profile': det_id_1,
            'body': 'Old post before cutoff',
            'published_at': '2023-01-01 00:00:00.000Z',
            'timestamp_precision': 'exact_urn',
        },
    ])
    up_posts = json.loads(cli('upsert', 'posts', posts_payload, '--sync-run', sync_id, '--since', '2026-10-01'))
    assert up_posts['created'] == 1 and up_posts['skipped_before_cutoff'] == 1

    finished = json.loads(cli('sync-finish', sync_id, '--status', 'completed', '--stats', '{"scanned":4,"created":3,"updated":1}'))
    assert finished['status'] == 'completed' and finished['completed_at']

    cli('logout')
print('Portable skill and schema checks passed.')
