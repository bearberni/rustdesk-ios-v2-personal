"""Validate a built SideStore IPA without assuming signature/runtime acceptance.

Uses the standard library; preserves all compiler-extracted AppIntents metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import struct
import zipfile
from pathlib import Path, PurePosixPath

ARM64 = 0x0100000C


def require(value, message):
    if not value:
        raise ValueError(message)


def macho_architectures(data: bytes) -> list[int]:
    require(len(data) >= 8, 'Truncated Mach-O')
    magic = data[:4]
    if magic in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
        return [struct.unpack_from('<I', data, 4)[0]]
    if magic in (b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce'):
        return [struct.unpack_from('>I', data, 4)[0]]
    fat = {
        b'\xca\xfe\xba\xbe': ('>', 20), b'\xbe\xba\xfe\xca': ('<', 20),
        b'\xca\xfe\xba\xbf': ('>', 32), b'\xbf\xba\xfe\xca': ('<', 32),
    }
    require(magic in fat, 'Executable is not Mach-O')
    endian, stride = fat[magic]
    count = struct.unpack_from(endian + 'I', data, 4)[0]
    require(1 <= count <= 32 and len(data) >= 8 + count * stride, 'Invalid FAT header')
    return [struct.unpack_from(endian + 'I', data, 8 + i * stride)[0] for i in range(count)]


def possible_identifiers(obj, prefix=''):
    results = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = prefix + '/' + str(key)
            if isinstance(value, str) and any(word in str(key).lower() for word in ('identifier', 'type', 'intent')):
                results.append({'path': path, 'value': value})
            results.extend(possible_identifiers(value, path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            results.extend(possible_identifiers(value, prefix + '/' + str(index)))
    return results


def inspect(ipa: Path, expected_intent: str | list[str], output: Path):
    expected_intents = [expected_intent] if isinstance(expected_intent, str) else expected_intent
    require(bool(expected_intents), 'No expected intents supplied')
    for identifier in expected_intents:
        require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', identifier), 'Invalid expected intent type')
    output.mkdir(parents=True, exist_ok=True)
    report = {
        'ipa_file': ipa.name, 'ipa_bytes': ipa.stat().st_size,
        'ipa_sha256': hashlib.sha256(ipa.read_bytes()).hexdigest(),
        'expected_intents': expected_intents,
        'valid_Apple_device_signature': False,
        'phone_installation_or_automation_verified': False,
    }
    with zipfile.ZipFile(ipa) as z:
        require(z.testzip() is None, 'ZIP CRC failure')
        names = z.namelist()
        require(len(names) == len(set(names)), 'Duplicate archive members')
        for name in names:
            p = PurePosixPath(name)
            require(not p.is_absolute() and '..' not in p.parts and '\\' not in name, 'Unsafe archive member')
        infos = [n for n in names if re.fullmatch(r'Payload/[^/]+\.app/Info\.plist', n)]
        require(infos == ['Payload/SideStore.app/Info.plist'], 'Expected exactly one top-level SideStore app')
        app_root = 'Payload/SideStore.app/'
        info_data = z.read(infos[0])
        info = plistlib.loads(info_data)
        (output / 'Info.plist').write_bytes(info_data)
        (output / 'Info.plist.json').write_text(json.dumps(info, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        require(info.get('CFBundleIdentifier') == 'com.SideStore.SideStore', 'Changed upstream bundle identifier; cannot assume in-place personal update')
        version = info.get('CFBundleShortVersionString', '')
        require(isinstance(version, str) and 'personalautomation' in version, 'Missing visible personalautomation version')
        require('iPhoneOS' in info.get('CFBundleSupportedPlatforms', []), 'Not an iPhoneOS device app')
        executable = info.get('CFBundleExecutable')
        require(isinstance(executable, str) and executable and '/' not in executable, 'Invalid executable name')
        architectures = macho_architectures(z.read(app_root + executable))
        require(ARM64 in architectures, 'Missing native arm64 executable')
        # No real personal provisioning profile belongs in a public unsigned build.
        profiles = [n for n in names if n.endswith('/embedded.mobileprovision')]
        require(not profiles, 'Unexpected embedded provisioning profile in unsigned artifact')

        metadata_names = [n for n in names if n.startswith(app_root + 'Metadata.appintents/') and not n.endswith('/')]
        require(metadata_names, 'Main-app AppIntents extracted metadata is missing')
        metadata_records, identifier_candidates, registered_actions = [], [], []
        for name in metadata_names:
            blob = z.read(name)
            relative = PurePosixPath(name[len(app_root):])
            target = output / 'AppIntentsMetadata' / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            record = {'path': name, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
            parsed = None
            try:
                parsed = json.loads(blob)
                record['format'] = 'JSON'
            except (ValueError, UnicodeDecodeError):
                try:
                    parsed = plistlib.loads(blob)
                    record['format'] = 'plist'
                except Exception:
                    record['format'] = 'opaque; raw file preserved'
            if parsed is not None:
                (target.with_name(target.name + '.json')).write_text(json.dumps(parsed, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
                candidates = possible_identifiers(parsed)
                identifier_candidates.extend({'metadata_file': name, **x} for x in candidates)
                # Verified against official 0.7.0-alpha compiler metadata: actions is a keyed map.
                action_map = parsed.get('actions') if isinstance(parsed, dict) else None
                if isinstance(action_map, dict):
                    for metadata_key, action in action_map.items():
                        if isinstance(action, dict) and isinstance(action.get('identifier'), str):
                            registered_actions.append({'metadata_file': name, 'metadata_key': metadata_key, **action})
            metadata_records.append(record)

        (output / 'AppIntents-identifier-candidates.json').write_text(json.dumps(identifier_candidates, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (output / 'AppIntents-registered-actions.json').write_text(json.dumps(registered_actions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        matches = {identifier: [x['metadata_file'] for x in registered_actions if x['identifier'] == identifier] for identifier in expected_intents}
        missing = [identifier for identifier, files in matches.items() if not files]
        report.update({
            'bundle_identifier': info['CFBundleIdentifier'], 'marketing_version': version,
            'executable': executable, 'architectures': architectures,
            'embedded_mobileprovision_files': profiles,
            'AppIntents_metadata': metadata_records,
            'expected_intent_metadata_matches': matches,
            'missing_registered_intents': missing,
            'status': 'passed' if not missing else 'failed_expected_intent_not_registered',
            'metadata_identifier_note': 'Strict main-app compiled actions map; compiler registration is not iPhone action discovery proof.',
        })
        (output / 'ipa-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        require(not missing, 'Expected intent identifier was not registered in compiler metadata: ' + ', '.join(missing))
    (output / 'SHA256SUMS.txt').write_text(report['ipa_sha256'] + '  ' + ipa.name + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ipa', type=Path)
    parser.add_argument('--expected-intent', required=True, action='append', help='Repeat or supply comma-separated registered action identifiers')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    expected = [identifier.strip() for value in args.expected_intent for identifier in value.split(',') if identifier.strip()]
    report = inspect(args.ipa, expected, args.output_dir)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
