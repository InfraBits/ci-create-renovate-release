'''Detect production vs development changes in composer.json & composer.lock.'''
import json

from common import compare_sections, describe_package, run, show


def load(ref, path):
    content = show(ref, path)
    return json.loads(content) if content else {}


def check(changes, latest_tag):
    compare_sections(changes, 'composer.json',
                     load(latest_tag, 'composer.json'), load('HEAD', 'composer.json'),
                     development_keys={'require-dev', 'autoload-dev'})

    old_lock, new_lock = load(latest_tag, 'composer.lock'), load('HEAD', 'composer.lock')

    # content-hash changes with any composer.json change, which is handled above
    compare_sections(changes, 'composer.lock', old_lock, new_lock,
                     development_keys={'platform-dev'},
                     ignored_keys={'_readme', 'content-hash', 'packages', 'packages-dev'})

    # A package moving between packages & packages-dev shows up as a change in both
    for key, report in (('packages', changes.production), ('packages-dev', changes.development)):
        old_packages = {p['name']: p for p in old_lock.get(key, [])}
        new_packages = {p['name']: p for p in new_lock.get(key, [])}
        for name in sorted(old_packages.keys() | new_packages.keys()):
            old, new = old_packages.get(name), new_packages.get(name)
            if old != new:
                report(f'composer.lock: {key}: {name}: {describe_package(old, new)}')


if __name__ == '__main__':
    run('composer', check)
