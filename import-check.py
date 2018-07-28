import json
import os
from typing import Dict, List, Set

import click
from distlib.database import DistributionPath


def get_modules(path: str) -> Dict[str, List[str]]:
    """
    Returns the actual file name that is imported for a module
    """
    modules: Dict[str, str] = {}
    dp = DistributionPath([path], include_egg=True)
    dists = dp.get_distributions()
    for dist in dists:
        for filename, _, _ in dist.list_installed_files():
            if filename.endswith(('.py')):
                parts = os.path.splitext(filename)[0].split(os.sep)
                if len(parts) == 1: # windows sep varies with distribution type
                    parts = os.path.splitext(filename)[0].split('/')
                if parts[-1].startswith('_') and not parts[-1].startswith('__'):
                    continue # ignore internals
                elif parts[-1] == '__init__' and parts[-2] != "tests":
                    module = parts[-2]
                    if not dist.key in modules:
                        modules[dist.key] = []
                    modules[dist.key].append(module)
    return modules


def check_line_import(line: str) -> bool:
    if line.startswith("import ") or line.startswith("from "):
        return True

    return False


def parse_imports(imports: List[str]) -> List[str]:
    """
    Parse the base import out of a specific import line
    e.g., django.db => django
    """
    filtered_imports: List[str] = []
    imports = [i for i in imports if not i.startswith(".")]  # filter relative imports that we don't care about
    imports = [i for i in imports if not i.startswith("_")]  # filter special imports that we don't care about
    for imp in imports:
        filtered_imports.append(imp.split(".")[0])

    return filtered_imports


def parse_import_line(line: str) -> List[str]:
    """
    Parse the base import out of an import line
    e.g., from django.db import Foo => django
    """
    if line.startswith("from"):
        return parse_imports([line.split(" ")[1]])  # from _import_ import doesnt, matter

    imports = line.split(" ")[1].split(",")  # import _import1, import2, import3_ as doesnt matter
    return parse_imports(imports)


def parse_file(file_path: str) -> List[str]:
    """
    Iterates through a given Python file looking for lines with `import`
    statements
    """
    imports: List[str] = []

    with open(file_path, 'r') as f:
        for line in f:
            stripped_line = line.strip()
            if check_line_import(stripped_line):
                imports += parse_import_line(stripped_line)

    return imports


def get_imports(path: str, excludes: List[str]) -> List[str]:
    """
    Iterates through a Python project directory and parses each `.py`
    file contained within (excluding those specified)
    """
    imports: List[str] = []

    for root, dirs, files in os.walk(path, topdown=True):
        dirs[:] = [d for d in dirs if d not in excludes]
        for file in files:
            if file.endswith(".py"):
                file_imports = parse_file(os.path.join(root, file))
                imports += file_imports

    return list(set(imports))


def traverse_used(dependencies: List[str], graph: List[dict]) -> List[str]:
    """
    Recursively iterates through dependencies and subdependencies to ensure the
    inclusion of all necessary packages
    """
    for package in graph:
        if package["package"]["key"] in dependencies:
            sub_dependencies = [pkg["key"] for pkg in package["dependencies"]]
            if len(sub_dependencies) == 0:
                return dependencies
            dependencies += traverse_used(sub_dependencies, graph)
            dependencies += sub_dependencies

    return dependencies


def determine_unused(modules: Dict[str, List[str]], imports: List[str], graph: List[dict]) -> List[str]:
    """
    Iterates through top-level requirements to determine which are never imported and returns that
    """
    unused: List[str] = []
    used: List[str] = imports

    for package in graph:
        key = package["package"]["key"]
        deps = package["dependencies"]

        try:
            module_names = modules[key]
        except KeyError:
            module_names = [key]

        for module_name in module_names:
            if not module_name in imports:
                unused.append(key)
            else:
                used.append(key)
                if len(deps) > 0:
                    dependencies = [pkg["key"] for pkg in deps]
                    used += traverse_used(dependencies, graph)
                    used += dependencies
                break

    unused = set([u for u in unused if u not in set(used)])
    return list(unused)


@click.command()
@click.option('--path', default='.', help='The directory containing Python files to check (recursive)')
@click.option('--graph', default='graph.json', help='The pipenv dependency graph')
@click.option('--package-path', default='[path]/venv/lib/python3.6/site-packages', help='The directory containing Python files to check (recursive)')
@click.option('--exclude', default='__pycache__,venv,static,node_modules', help='A comma separated list of directorys to exclude from checks')
@click.option('--uninstall/--no-uninstall', default=False, help='Output the pip command to uninstall unused requirements')
def main(path, graph, package_path, exclude, uninstall):
    package_path = package_path.replace("[path]", path)
    imports = get_imports(path, exclude.split(','))
    modules = get_modules(package_path)
    graph = json.loads(open(graph, 'r').read())
    unused_requirements = determine_unused(modules, imports, graph)
    if len(unused_requirements):
        print("Libraries to review: ")
        print("======================")
        print(unused_requirements)
        if uninstall:
            print(f"pip uninstall {' '.join(unused_requirements)}")
    else:
        print("Good job! No unused requirements")


if __name__ == "__main__":
    main()
