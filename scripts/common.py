'''Shared helpers for detecting production vs development dependency changes.'''
import json
import os
import subprocess
import sys


class Changes:
    def __init__(self, name):
        self.name = name
        self.found = {'production': [], 'development': []}

    def production(self, change):
        self.found['production'].append(change)

    def development(self, change):
        self.found['development'].append(change)

    def report(self):
        if not any(self.found.values()):
            print(f'[{self.name}] No changes found')
        for kind, changes in self.found.items():
            if changes:
                print(f'[{self.name}] Found {len(changes)} {kind} change(s):')
                for change in changes:
                    print(f'  - {change}')

    def write(self):
        if self.found['production']:
            set_output('have_changes', 'true')
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


def diff(old, new, path=''):
    '''Yield (path, description) for each differing leaf between two nested mappings.'''
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            yield from diff(old.get(key), new.get(key), f'{path}.{key}' if path else key)
    elif isinstance(old, dict) and new is None:
        yield from diff(old, {}, path)
    elif old is None and isinstance(new, dict):
        yield from diff({}, new, path)
    elif old != new:
        yield path, describe(old, new)


def describe_package(old, new):
    '''Describe a lock file package entry changing, where None means missing.'''
    old_version = old.get('version') if old else None
    new_version = new.get('version') if new else None
    if old_version == new_version:
        return f'{old_version} (metadata changed)'
    return describe(old_version, new_version)


def compare_sections(changes, file, old, new, development_keys, ignored_keys=()):
    '''Compare two top level mappings, treating development_keys as development and the rest as production.'''
    for key in sorted((old.keys() | new.keys()) - set(ignored_keys)):
        report = changes.development if key in development_keys else changes.production
        for path, description in diff(old.get(key), new.get(key), key):
            report(f'{file}: {path}: {description}')


def run(name, check):
    '''Run check(changes, latest_tag), then report & write the outputs.'''
    changes = Changes(name)
    check(changes, sys.argv[1])
    changes.report()
    changes.write()
