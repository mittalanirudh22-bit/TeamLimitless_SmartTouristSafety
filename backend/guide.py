"""City guide content for the tourist website: places, food, stays and safety info per city.

Each city is a folder under locations/<slug>/ with config.yaml (risk engine), geofences.geojson (safety zones)
and guide.json (what tourists see). Adding a city means adding that folder -- no code changes.
"""
import json, re
from functools import lru_cache
from fastapi import APIRouter, HTTPException
from .database import ROOT

router = APIRouter()
LOCATIONS = ROOT / 'locations'
SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')


def valid_slug(slug: str) -> bool:
    return bool(slug and SLUG.match(slug)) and slug != 'template'


def location_slugs():
    """Every configured location (has a config.yaml), whether or not it has a tourist guide yet."""
    return sorted(p.parent.name for p in LOCATIONS.glob('*/config.yaml') if valid_slug(p.parent.name))


def guide_slugs():
    return sorted(p.parent.name for p in LOCATIONS.glob('*/guide.json') if valid_slug(p.parent.name))


@lru_cache(maxsize=64)
def _load(slug, _mtime):  # keyed on mtime, so an edited guide.json is picked up without a restart
    return json.loads((LOCATIONS / slug / 'guide.json').read_text(encoding='utf-8'))


def get_guide(slug: str):
    path = LOCATIONS / slug / 'guide.json'
    if not valid_slug(slug) or not path.exists():
        raise HTTPException(404, 'city guide not found')
    return _load(slug, path.stat().st_mtime_ns)


def summary(g):
    return dict(slug=g['slug'], name=g['name'], state=g['state'], tagline=g['tagline'], wiki=g.get('wiki'),
                center=g['center'], zoom=g.get('zoom', 12),
                counts=dict(places=len(g['places']), food=len(g['food']), stays=len(g['stays'])))


@router.get('')
def cities():
    return [summary(get_guide(s)) for s in guide_slugs()]


@router.get('/{slug}')
def city(slug: str):
    return get_guide(slug)
