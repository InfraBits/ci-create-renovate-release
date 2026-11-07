'''Detect production vs development changes in pyproject.toml & poetry.lock.'''
import copy
import re

from common import describe_package, diff, run, show

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

DEVELOPMENT_GROUPS = {'dev', 'test'}


def load(ref, path):
    content = show(ref, path)
    return tomllib.loads(content) if content else {}


def normalise(name):
    return re.sub(r'[-_.]+', '-', re.match(r'[A-Za-z0-9._-]+', name).group()).lower()


def split_pyproject(data):
    # Split pyproject into (production, development) sections
    production = copy.deepcopy(data)
    poetry = production.get('tool', {}).get('poetry', {})
    development = {'tool.poetry.dev-dependencies': poetry.pop('dev-dependencies', None)}
    for name in DEVELOPMENT_GROUPS:
        development[f'tool.poetry.group.{name}'] = poetry.get('group', {}).pop(name, None)
        development[f'dependency-groups.{name}'] = production.get('dependency-groups', {}).pop(name, None)
    return production, development


def production_packages(pyproject, packages):
    # Poetry >= 2.0 records the groups per package & Poetry < 1.5 records the category
    if all('groups' in p or 'category' in p for p in packages.values()):
        return {name for name, p in packages.items()
                if set(p.get('groups', [p.get('category')])) - DEVELOPMENT_GROUPS}

    # Otherwise walk the dependency tree from the non-development dependencies,
    # ignoring markers, so we over rather than under count production packages
    project = pyproject.get('project', {})
    poetry = pyproject.get('tool', {}).get('poetry', {})
    roots = [n for n in poetry.get('dependencies', {}) if n != 'python']
    roots += project.get('dependencies', [])
    for dependencies in project.get('optional-dependencies', {}).values():
        roots += dependencies
    for name, group in poetry.get('group', {}).items():
        if name not in DEVELOPMENT_GROUPS:
            roots += group.get('dependencies', {})
    for name, dependencies in pyproject.get('dependency-groups', {}).items():
        if name not in DEVELOPMENT_GROUPS:
            roots += [d for d in dependencies if isinstance(d, str)]

    seen = set()
    pending = [normalise(n) for n in roots]
    while pending:
        name = pending.pop()
        if name in seen or name not in packages:
            continue
        seen.add(name)
        pending += [normalise(d) for d in packages[name].get('dependencies', {})]
        for dependencies in packages[name].get('extras', {}).values():
            pending += [normalise(d) for d in dependencies]
    return seen


def check(changes, latest_tag):
    if tomllib is None:
        changes.production('tomllib is not available (requires python >= 3.11)')
        return

    old_pyproject, new_pyproject = load(latest_tag, 'pyproject.toml'), load('HEAD', 'pyproject.toml')
    old_production, old_development = split_pyproject(old_pyproject)
    new_production, new_development = split_pyproject(new_pyproject)
    for path, description in diff(old_production, new_production):
        changes.production(f'pyproject.toml: {path}: {description}')
    for path, description in diff(old_development, new_development):
        changes.development(f'pyproject.toml: {path}: {description}')

    old_lock, new_lock = load(latest_tag, 'poetry.lock'), load('HEAD', 'poetry.lock')

    # content-hash changes with any pyproject change, which is handled above
    old_metadata = {k: v for k, v in old_lock.get('metadata', {}).items() if k != 'content-hash'}
    new_metadata = {k: v for k, v in new_lock.get('metadata', {}).items() if k != 'content-hash'}
    for path, description in diff(old_metadata, new_metadata, 'metadata'):
        changes.production(f'poetry.lock: {path}: {description}')

    old_packages = {normalise(p['name']): p for p in old_lock.get('package', [])}
    new_packages = {normalise(p['name']): p for p in new_lock.get('package', [])}
    production = (production_packages(old_pyproject, old_packages) |
                  production_packages(new_pyproject, new_packages))
    for name in sorted(old_packages.keys() | new_packages.keys()):
        old, new = old_packages.get(name), new_packages.get(name)
        if old == new:
            continue
        report = changes.production if name in production else changes.development
        report(f'poetry.lock: {name}: {describe_package(old, new)}')


if __name__ == '__main__':
    run('poetry', check)
