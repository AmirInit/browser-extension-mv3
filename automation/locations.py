#!/usr/bin/env python3
"""Fetch only fresh, public Chrome warp metadata from Windscribe's CDNs."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

HOSTS = ('assets.windscribe.com', 'assets.totallyacdn.com')
MAX_AGE = 24 * 60 * 60


class LocationRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != 'https' or target.hostname not in HOSTS:
            raise ValueError('location source redirected to an untrusted host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(LocationRedirects())


def sanitize(obj):
    raw = obj.get('data') if isinstance(obj, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError('location list is empty or malformed')
    locations, seen_locations, seen_groups = [], set(), set()
    for loc in raw:
        if not isinstance(loc, dict):
            raise ValueError('invalid location')
        ident, country, tz = loc.get('id'), loc.get('country_code') or 'AUTO', loc.get('tz')
        if type(ident) is not int or ident <= 0 or ident in seen_locations:
            raise ValueError('invalid or duplicate location ID')
        if not isinstance(country, str) or not re.fullmatch(r'[A-Z]{2}|AUTO', country):
            raise ValueError('invalid country code')
        if tz is not None and (not isinstance(tz, str) or not re.fullmatch(r'[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+', tz)):
            raise ValueError('invalid timezone')
        seen_locations.add(ident)
        groups = loc.get('groups') or []
        if not isinstance(groups, list):
            raise ValueError('invalid datacenter list')
        cleaned = []
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError('invalid datacenter')
            gid, gps = group.get('id'), group.get('gps')
            if type(gid) is not int or gid <= 0 or gid in seen_groups:
                raise ValueError('invalid or duplicate datacenter ID')
            seen_groups.add(gid)
            result = {'id': gid}
            if gps is not None:
                if not isinstance(gps, str) or not re.fullmatch(r'\s*[+-]?\d+(?:\.\d+)?\s*,\s*[+-]?\d+(?:\.\d+)?\s*', gps):
                    raise ValueError('invalid datacenter coordinates')
                lat, lon = map(float, gps.split(','))
                if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
                    raise ValueError('datacenter coordinates out of range')
                result['gps'] = gps
            cleaned.append(result)
        entry = {'id': ident, 'country_code': country, 'groups': sorted(cleaned, key=lambda x: x['id'])}
        if tz is not None:
            entry['tz'] = tz
        locations.append(entry)
    if not seen_groups:
        raise ValueError('location list has no datacenters')
    return {'data': sorted(locations, key=lambda x: x['id'])}


def check_fresh(headers, now):
    try:
        date = parsedate_to_datetime(headers['Date']).timestamp()
        modified = parsedate_to_datetime(headers['Last-Modified']).timestamp()
        age = int(headers.get('Age', '0'))
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError('missing or invalid HTTP freshness metadata') from exc
    if abs(date - now) > 900 or age < 0 or age > MAX_AGE or date - modified > MAX_AGE or modified > date + 120:
        raise ValueError('location response is stale or has invalid timestamps')


def fetch(host, tier):
    url = f'https://{host}/serverlist/chrome/{tier}/x'
    req = urllib.request.Request(url, headers={'User-Agent': 'windscribe-community-build/1', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    with OPENER.open(req, timeout=25) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname not in HOSTS:
            raise ValueError('location source redirected to an untrusted host')
        check_fresh(response.headers, time.time())
        body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ValueError('location response too large')
        return sanitize(json.loads(body))


def main():
    target = Path(sys.argv[1])
    errors = []
    for host in HOSTS:
        try:
            free, pro = fetch(host, 0), fetch(host, 1)
            if free != pro:
                raise ValueError('public free and pro warp metadata differ; completeness requires review')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(free, separators=(',', ':')) + '\n', encoding='utf8')
            os.chmod(target, 0o600)
            print('Fresh public Chrome warp metadata:', len(free['data']), 'locations,',
                  sum(len(x['groups']) for x in free['data']), 'datacenters; source:', host)
            return
        except Exception as exc:
            errors.append(host + ': ' + str(exc)[:180])
    raise RuntimeError('No fresh, consistent public location feed: ' + '; '.join(errors))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Location retrieval failed safely:', str(exc), file=sys.stderr)
        sys.exit(1)
