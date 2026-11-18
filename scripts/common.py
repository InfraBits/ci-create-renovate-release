'''Shared helpers for detecting production vs development dependency changes.'''
import json
import os
import re
import subprocess
import sys

# Semantic version levels a change can require
PATCH, MINOR = 'patch', 'minor'


class Changes:
    def __init__(self, name):
        self.name = name
        self.found = {'production': [], 'development': []}

    def production(self, change, level=PATCH):
        self.found['production'].append((change, level))

    def development(self, change, level=PATCH):
        self.found['development'].append((change, level))

    def report(self):
        if not any(self.found.values()):
            print(f'[{self.name}] No changes found')
        for kind, changes in self.found.items():
            if changes:
                print(f'[{self.name}] Found {len(changes)} {kind} change(s):')
                for change, level in changes:
                    print(f'  - [{level}] {change}')

    def write(self):
        if self.found['production']:
            set_output('have_changes', 'true')
        # Development dependencies are not shipped, so only production changes can require more than a patch
        if any(level == MINOR for _, level in self.found['production']):
            set_output('have_minor_changes', 'true')
        if self.found['development']:
            set_output('have_development_changes', 'true')


def set_output(name, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'{name}={value}\n')


def show(ref, path):
    '''Return the content of path at ref, or None if it does not exist.'''
    try:
        return subprocess.run(['git', 'show', f'{ref}:{path}'], check=True, capture_output=True).stdout.decode()
    except subprocess.CalledProcessError:
        return None


def format_value(value):
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def describe(old, new):
    '''Describe a value changing from old to new, where None means missing.'''
    if old is None:
        return f'added {format_value(new)}'
    if new is None:
        return f'removed {format_value(old)}'
    return f'{format_value(old)} -> {format_value(new)}'


def parse_version(value):
    '''Return the (major, minor) of a version or constraint like 1.2.3, v1.2 or ^1.2, or None if it is not one.'''
    match = isinstance(value, str) and re.match(r'[\s^~=<>!v]*(\d+)(?:\.(\d+))?', value)
    return (int(match[1]), int(match[2] or 0)) if match else None


def level(old, new):
    '''Return the level of a value changing from old to new, where None means missing.

    Adding or removing a value (i.e. a dependency) or changing the major/minor version is a minor change,
    anything else (patch versions, metadata or values we cannot parse) is a patch change.
    '''
    if old == new:
        return PATCH
    if old is None or new is None:
        return MINOR
    old_version, new_version = parse_version(old), parse_version(new)
    if old_version and new_version and old_version != new_version:
        return MINOR
    return PATCH


def diff(old, new, path=''):
    '''Yield (path, old, new) for each differing leaf between two nested mappings, where None means missing.'''
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            yield from diff(old.get(key), new.get(key), f'{path}.{key}' if path else key)
    elif isinstance(old, dict) and new is None:
        yield from diff(old, {}, path)
    elif old is None and isinstance(new, dict):
        yield from diff({}, new, path)
    elif old != new:
        yield path, old, new


def describe_package(old, new):
    '''Describe a lock file package entry changing, where None means missing.'''
    old_version = old.get('version') if old else None
    new_version = new.get('version') if new else None
    if old_version == new_version:
        return f'{old_version} (metadata changed)'
    return describe(old_version, new_version)


def package_level(old, new):
    '''Return the level of a lock file package entry changing, where None means missing.'''
    if old is None or new is None:
        return MINOR
    return level(old.get('version'), new.get('version'))


def compare_sections(changes, file, old, new, development_keys, ignored_keys=()):
    '''Compare two top level mappings, treating development_keys as development and the rest as production.'''
    for key in sorted((old.keys() | new.keys()) - set(ignored_keys)):
        report = changes.development if key in development_keys else changes.production
        for path, old_value, new_value in diff(old.get(key), new.get(key), key):
            report(f'{file}: {path}: {describe(old_value, new_value)}', level(old_value, new_value))


def run(name, check):
    '''Run check(changes, latest_tag), then report & write the outputs.'''
    changes = Changes(name)
    check(changes, sys.argv[1])
    changes.report()
    changes.write()
