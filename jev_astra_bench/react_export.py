"""Export candidate source without temporary browser profiles or crash memory."""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path, PurePosixPath


def export_source_archive(source: Path, target: Path) -> dict:
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        roots, candidates, signatures = set(), set(), {}
        sentinels = {'Local State', 'Variations', 'VariationsSafeSeedV2', 'VariationsSeedV2',
                     'DevToolsActivePort', 'Last Version'}
        for member in members:
            parts = PurePosixPath(member.filename).parts
            for i, part in enumerate(parts[:-1]):
                if part.startswith('.') and any(term in part.lower() for term in ('profile', 'browser', 'chrome')):
                    candidates.add('/'.join(parts[:i + 1]) + '/')
                if part == 'Crashpad' and i and (parts[-1] in {'metadata', 'settings.dat'} or parts[-1].endswith('.dmp')):
                    signatures.setdefault('/'.join(parts[:i]) + '/', set()).add('Crashpad')
            if parts and parts[-1] in sentinels and len(parts) > 1:
                signatures.setdefault('/'.join(parts[:-1]) + '/', set()).add(parts[-1])
        for candidate in candidates:
            evidence = set().union(*(values for root, values in signatures.items() if root.startswith(candidate)))
            if len(evidence) >= 2:
                roots.add(candidate)
        for root, evidence in signatures.items():
            if len(evidence) >= 2 and not any(root.startswith(known) for known in roots):
                raise ValueError('Unclassified browser profile data; inspect before exporting this source archive')
        excluded = [m for m in members if any(m.filename.startswith(root) for root in roots)]
        if any(m.filename.endswith('.dmp') and m not in excluded for m in members):
            raise ValueError('Unclassified crash dump; inspect before exporting this source archive')
        if excluded:
            names = {m.filename for m in excluded}
            with zipfile.ZipFile(target, 'w') as exported:
                for member in members:
                    if member.filename not in names:
                        exported.writestr(member, archive.read(member))
        else:
            shutil.copy2(source, target)
    return {'excluded_members': len(excluded), 'excluded_browser_profile_roots': sorted(roots),
            'original_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'exported_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'policy': 'Only temporary browser profile directories are omitted. Code and assets retain their exact bytes; the raw archive remains in the original run.'}
