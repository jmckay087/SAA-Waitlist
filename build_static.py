"""Build only public app assets for GitHub Pages; never copy local databases."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
MARKER = '.saa-static-build'


def build(output):
    output = Path(output).resolve()
    if output == ROOT or output.is_relative_to(ROOT / 'static') or output.is_relative_to(ROOT / 'instance'):
        raise ValueError('Choose a separate generated output directory.')
    if output.exists() and (not output.is_dir() or (any(output.iterdir()) and not (output / MARKER).is_file())):
        raise ValueError('The output directory contains unrelated files. Choose an empty directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape(['html']))
    html = environment.get_template('index.html').render(
        browser_local=True, csrf='browser-local', password_enabled=False,
        asset_base='./static/', home_href='./',
        default_schedule=json.loads((ROOT / 'default_schedule.json').read_text()),
    )
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / 'site'
        stage.mkdir()
        # Explicit allowlist: source, customer data, session keys and backups stay out.
        assets = stage / 'static'
        assets.mkdir()
        for filename in ['app.js', 'local-store.js', 'style.css']:
            shutil.copy2(ROOT / 'static' / filename, assets / filename)
        shutil.copytree(ROOT / 'static' / 'images', assets / 'images')
        (stage / 'index.html').write_text(html, encoding='utf-8')
        (stage / '.nojekyll').touch()
        (stage / MARKER).touch()
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(stage), str(output))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / '_site'))
    arguments = parser.parse_args()
    print(f'Static website built in {build(arguments.output)}')
