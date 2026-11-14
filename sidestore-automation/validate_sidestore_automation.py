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
BASE_ID = 'com.SideStore.SideStore'
BASE_GROUP = 'group.' + BASE_ID
PLACEHOLDER_TEAM = 'XYZ0123456'
STRING_TYPE = {'primitive': {'wrapper': {'typeIdentifier': 0}}}


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


def arm64_entitlements(data: bytes) -> dict:
    """Read the actual main executable's ad-hoc XML entitlements, not a sidecar.

    This checks identity retained for personal re-signing. It does not verify an
    Apple device signature, authorize a team or prove iPhone acceptance.
    """
    require(ARM64 in macho_architectures(data), 'Missing arm64 signature target')
    magic = data[:4]
    if magic in (b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'):
        endian = '>' if magic in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf') else '<'
        wide = magic in (b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca')
        stride = 32 if wide else 20
        slices = []
        for i in range(struct.unpack_from(endian + 'I', data, 4)[0]):
            pos = 8 + i * stride
            if struct.unpack_from(endian + 'I', data, pos)[0] == ARM64:
                offset, size = struct.unpack_from(endian + ('QQ' if wide else 'II'), data, pos + 8)
                require(size >= 32 and offset + size <= len(data), 'Invalid arm64 FAT slice')
                slices.append(data[offset:offset + size])
        require(len(slices) == 1, 'Expected one arm64 slice for identity validation')
        data = slices[0]
        magic = data[:4]
    require(magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'), 'Expected native64 Mach-O')
    endian = '<' if magic == b'\xcf\xfa\xed\xfe' else '>'
    require(len(data) >= 32, 'Truncated64-bit Mach-O')
    ncmds, cmdbytes = struct.unpack_from(endian + 'II', data, 16)
    require(ncmds <= 4096 and 32 + cmdbytes <= len(data), 'Invalid Mach-O load commands')
    pos, signatures = 32, []
    for _ in range(ncmds):
        require(pos + 8 <= 32 + cmdbytes, 'Truncated load command')
        cmd, size = struct.unpack_from(endian + 'II', data, pos)
        require(size >= 8 and pos + size <= 32 + cmdbytes, 'Invalid load-command size')
        if cmd == 0x1D:  # LC_CODE_SIGNATURE
            require(size >= 16, 'Truncated code-signature command')
            offset, length = struct.unpack_from(endian + 'II', data, pos + 8)
            require(length >= 12 and offset + length <= len(data), 'Invalid signature range')
            signatures.append(data[offset:offset + length])
        pos += size
    require(len(signatures) == 1, 'Expected one embedded ad-hoc signature')
    sig = signatures[0]
    magic, length, count = struct.unpack_from('>III', sig)
    require(magic == 0xFADE0CC0 and 12 <= length <= len(sig), 'Invalid signature SuperBlob')
    require(count <= 128 and 12 + count * 8 <= length, 'Invalid signature index')
    values = []
    for i in range(count):
        slot, offset = struct.unpack_from('>II', sig, 12 + i * 8)
        require(offset + 8 <= length, 'Invalid signature blob offset')
        blobmagic, bloblen = struct.unpack_from('>II', sig, offset)
        require(bloblen >= 8 and offset + bloblen <= length, 'Invalid signature blob size')
        if slot == 5:  # CSSLOT_ENTITLEMENTS
            require(blobmagic == 0xFADE7171, 'Expected XML entitlement slot')
            value = plistlib.loads(sig[offset + 8:offset + bloblen])
            require(isinstance(value, dict), 'Entitlements must be a dictionary')
            values.append(value)
    require(len(values) == 1, 'Missing or duplicate XML main-app entitlements')
    return values[0]


def identity_report(info: dict, executable: bytes) -> dict:
    require(info.get('CFBundleIdentifier') == BASE_ID, 'Changed main base bundle identity')
    groups = info.get('ALTAppGroups')
    #151 no longer includes this legacy Info field. The signed entitlements below
    #are authoritative; if the field exists it must remain consistent.
    require(groups is None or groups == [BASE_GROUP], 'Unexpected legacy ALTAppGroups identity')
    schemes = {s for row in info.get('CFBundleURLTypes', []) for s in row.get('CFBundleURLSchemes', [])}
    require({'sidestore', 'sidestore-' + BASE_ID}.issubset(schemes), 'Changed SideStore URL identities')
    require(info.get('UIFileSharingEnabled') is True, 'File sharing must remain enabled for recovery logs')
    require(info.get('LSSupportsOpeningDocumentsInPlace') is True, 'Documents-in-place support must remain enabled')
    bonjour = {x.rstrip('.') for x in info.get('NSBonjourServices', [])}
    require('_remotepairing._tcp' in bonjour, 'RemotePairing Bonjour service declaration missing')
    require(bool(info.get('NSLocalNetworkUsageDescription')), 'Missing Local Network usage description')
    entitlements = arm64_entitlements(executable)
    require(entitlements.get('application-identifier') == PLACEHOLDER_TEAM + '.' + BASE_ID,
            'Unexpected fake-sign application identity or personal team')
    require(entitlements.get('com.apple.developer.team-identifier') == PLACEHOLDER_TEAM,
            'Unexpected fake-sign team identity')
    require(entitlements.get('com.apple.security.application-groups') == [BASE_GROUP],
            'Changed main-app signed App Group identity')
    keychain = entitlements.get('keychain-access-groups')
    require(keychain is None or keychain == [PLACEHOLDER_TEAM + '.' + BASE_ID],
            'Unexpected keychain-access identity')
    return {
        'status': 'passed_unsigned_identity_only',
        'base_bundle_identifier': BASE_ID,
        'legacy_ALTAppGroups': groups,
        'URL_schemes': sorted(schemes),
        'actual_main_executable_entitlements': entitlements,
        'same_account_personal_resigning_required': True,
        'phone_account_pairing_or_container_preservation_verified': False,
        'boundary': 'Stable unsigned identity permits an in-place signing attempt; it does not prove same-team phone signing, storage migration or device acceptance.',
    }


def validate_wire_actions(actions: list[dict], expected: list[str]) -> dict:
    checked = {}
    for identifier in expected:
        matches = [a for a in actions if a.get('identifier') == identifier]
        require(len(matches) == 1, 'Expected exactly one main-app registered action: ' + identifier)
        action = matches[0]
        require(action.get('outputType') == STRING_TYPE, 'V2 action must return compiled String metadata: ' + identifier)
        parameters = action.get('parameters', [])
        names = [] if identifier == 'PrepareRenewalV2Intent' else ['runID']
        require([p.get('name') for p in parameters] == names, 'Changed V2 parameter schema: ' + identifier)
        for p in parameters:
            require(p.get('valueType') == STRING_TYPE and p.get('isOptional') is False,
                    'V2 runID must be a required String: ' + identifier)
        require({'type': 1} in action.get('allowedTargets', []), 'V2 main-app execution target missing: ' + identifier)
        if identifier == 'ExecuteRenewalV2Intent':
            require({'com.apple.link.systemProtocol.LongRunning', 'com.apple.link.systemProtocol.Cancellable',
                     'com.apple.link.systemProtocol.ProgressReporting'}.issubset(set(action.get('systemProtocols', []))),
                    'Renewal action lost required long-running/cancellation protocols')
        checked[identifier] = {'output': 'String', 'parameters': names, 'main_app_target': True}
    return checked


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


def inspect(ipa: Path, expected_intent: str | list[str], output: Path, expected_source_suffix: str | None = None):
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
        if expected_source_suffix:
            require(version.endswith('+' + expected_source_suffix), 'Personal version does not identify selected upstream source')
        require('iPhoneOS' in info.get('CFBundleSupportedPlatforms', []), 'Not an iPhoneOS device app')
        executable = info.get('CFBundleExecutable')
        require(isinstance(executable, str) and executable and '/' not in executable, 'Invalid executable name')
        executable_data = z.read(app_root + executable)
        architectures = macho_architectures(executable_data)
        require(ARM64 in architectures, 'Missing native arm64 executable')
        identity = identity_report(info, executable_data)
        (output / 'unsigned-identity-validation.json').write_text(json.dumps(identity, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
        wire_schema = validate_wire_actions(registered_actions, expected_intents)
        report.update({
            'bundle_identifier': info['CFBundleIdentifier'], 'marketing_version': version,
            'executable': executable, 'architectures': architectures,
            'embedded_mobileprovision_files': profiles,
            'AppIntents_metadata': metadata_records,
            'expected_intent_metadata_matches': matches,
            'missing_registered_intents': missing,
            'unsigned_identity': identity,
            'V2_compiled_wire_schema': wire_schema,
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
    parser.add_argument('--expected-source-suffix', default='151d3378')
    args = parser.parse_args()
    expected = [identifier.strip() for value in args.expected_intent for identifier in value.split(',') if identifier.strip()]
    report = inspect(args.ipa, expected, args.output_dir, args.expected_source_suffix)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
