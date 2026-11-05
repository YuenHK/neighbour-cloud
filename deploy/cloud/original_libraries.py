"""Count admitted original model libraries, independently of hosting domains.

This reads reviewed local manifests only. It never searches, downloads, grants
rights, publishes a model or treats a creator profile as an import adapter.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name('original_libraries.json')


def snapshot(*, document=None, static=None, runtime=None):
    document = document if document is not None else json.loads(MANIFEST.read_text(encoding='utf-8'))
    static = static if static is not None else json.loads((ROOT/'airi_overlay/cloud-model-gallery.json').read_text(encoding='utf-8'))['models']
    runtime = runtime if runtime is not None else json.loads((ROOT/'deploy/cloud/reviewed_model_imports.json').read_text(encoding='utf-8'))['models']
    if document.get('version') != 1 or document.get('counting_rule') != 'independent-original-libraries-v1':
        raise ValueError('original_library_manifest_invalid')
    known = {'static': {row['id']: row for row in static}, 'reviewed': {row['id']: row for row in runtime}}
    identities, maintainers, repositories, hashes, result = set(), set(), set(), set(), []
    for row in document['libraries']:
        identity, maintainer = row['id'], row['maintainer_id']
        if (not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', identity)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', maintainer)
                or identity in identities or maintainer in maintainers
                or row.get('verification') != 'licensed-native-import-verified'
                or row.get('original_material') is not True or not row['models']):
            raise ValueError('original_library_provenance_invalid')
        identities.add(identity)
        maintainers.add(maintainer)
        for link in [row['url'], *row['rights_urls']]:
            parsed = urlsplit(link)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
                raise ValueError('original_library_link_invalid')
        if not row['rights_urls']:
            raise ValueError('original_library_rights_missing')
        repository = row.get('repository')
        if repository:
            repo = urlsplit(repository)
            parts = repo.path.strip('/').split('/')
            key = '/'.join(parts).casefold()
            if (repo.scheme != 'https' or repo.hostname != 'github.com' or len(parts) != 2
                    or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) and part not in ('.', '..') for part in parts)
                    or repo.username or repo.password or repo.query or repo.fragment or repo.port
                    or key in repositories):
                raise ValueError('original_library_repository_invalid')
            repositories.add(key)
        models = []
        for ref in row['models']:
            item = known.get(ref['channel'], {}).get(ref['id'])
            if item is None or item['sha256'] != ref['sha256'] or ref['sha256'] in hashes:
                raise ValueError('original_library_model_not_admitted_or_recounted')
            hashes.add(ref['sha256'])
            models.append({'id': ref['id'], 'channel': ref['channel'], 'sha256': ref['sha256']})
        result.append({key: row[key] for key in ('id', 'name', 'maintainer_id', 'url', 'rights_urls')}
                      | {'repository': repository, 'one_click_verified': True,
                         'models': models, 'model_count': len(models), 'automatic_whole_repository_import': False})
    return {'counting_rule': document['counting_rule'], 'target_sources': 20,
            'verified_independent_sources': len(result), 'target_complete': len(result) >= 20,
            'verified_libraries': result, 'github_original_sources': len(repositories),
            'mirrors_profiles_or_repeated_maintainers_counted': False,
            'model_hashes_counted': len(hashes), 'network_requests': 0}
