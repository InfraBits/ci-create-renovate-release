'''Detect production vs development changes in package.json & package-lock.json.'''
import json

from common import compare_sections, describe_package, run, show


def load(ref, path):
    content = show(ref, path)
    return json.loads(content) if content else {}


def flatten_v1(dependencies, prefix=''):
    # lockfileVersion 1 nests dependencies, flatten them to node_modules paths like v2+
    packages = {}
    for name, package in dependencies.items():
        path = f'{prefix}node_modules/{name}'
        packages[path] = {k: v for k, v in package.items() if k != 'dependencies'}
        packages.update(flatten_v1(package.get('dependencies', {}), f'{path}/'))
    return packages


def lock_packages(lock):
    if 'packages' in lock:
        return lock['packages']
    return flatten_v1(lock.get('dependencies', {}))


def check(changes, latest_tag):
    compare_sections(changes, 'package.json',
                     load(latest_tag, 'package.json'), load('HEAD', 'package.json'),
                     development_keys={'devDependencies'})

    old_lock, new_lock = load(latest_tag, 'package-lock.json'), load('HEAD', 'package-lock.json')

    # packages (v2+) & dependencies (v1, also kept in v2 for compatibility) are handled below
    compare_sections(changes, 'package-lock.json', old_lock, new_lock,
                     development_keys=set(), ignored_keys={'packages', 'dependencies'})

    old_packages, new_packages = lock_packages(old_lock), lock_packages(new_lock)
    for path in sorted(old_packages.keys() | new_packages.keys()):
        old, new = old_packages.get(path), new_packages.get(path)
        if old == new:
            continue

        if path == '':
            # The root package mirrors package.json
            compare_sections(changes, 'package-lock.json: <root>', old or {}, new or {},
                             development_keys={'devDependencies'})
        elif all(p.get('dev') for p in (old, new) if p is not None):
            # devOptional packages are also optional production dependencies, so are not counted here
            changes.development(f'package-lock.json: {path}: {describe_package(old, new)}')
        else:
            changes.production(f'package-lock.json: {path}: {describe_package(old, new)}')


if __name__ == '__main__':
    run('npm', check)
