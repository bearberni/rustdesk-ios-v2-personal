"""Artifact-identity rejection tests; no device, credentials or real store writes."""
import copy
import json
import plistlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

import validate_sidestore_automation as validator

IDS = ['PrepareRenewalV2Intent', 'ExecuteRenewalV2Intent', 'FinalizeRenewalV2Intent']


def entitlements():
    return {
        'application-identifier': 'XYZ0123456.com.SideStore.SideStore',
        'com.apple.developer.team-identifier': 'XYZ0123456',
        'com.apple.security.application-groups': ['group.com.SideStore.SideStore'],
    }


def executable(values=None):
    xml = plistlib.dumps(entitlements() if values is None else values)
    blob = struct.pack('>II', 0xFADE7171, len(xml) + 8) + xml
    signature = struct.pack('>III', 0xFADE0CC0, 20 + len(blob), 1) + struct.pack('>II', 5, 20) + blob
    header = struct.pack('<IiiIIIII', 0xFEEDFACF, validator.ARM64, 0, 2, 1, 16, 0, 0)
    return header + struct.pack('<IIII', 0x1D, 16, 48, len(signature)) + signature


def info():
    return {
        'CFBundleIdentifier': 'com.SideStore.SideStore',
        'CFBundleShortVersionString': '0.7.0-personalautomation.5+151d3378',
        'CFBundleSupportedPlatforms': ['iPhoneOS'],
        'CFBundleExecutable': 'SideStore',
        'CFBundleURLTypes': [{'CFBundleURLSchemes': ['sidestore', 'sidestore-com.SideStore.SideStore']}],
        'UIFileSharingEnabled': True,
        'LSSupportsOpeningDocumentsInPlace': True,
        'NSBonjourServices': ['_remotepairing._tcp'],
        'NSLocalNetworkUsageDescription': 'Connect to this device.',
    }


def actions():
    result = []
    for identifier in IDS:
        result.append({
            'identifier': identifier,
            'allowedTargets': [{'type': 1}],
            'outputType': copy.deepcopy(validator.STRING_TYPE),
            'parameters': [] if identifier == IDS[0] else [{
                'name': 'runID', 'isOptional': False, 'valueType': copy.deepcopy(validator.STRING_TYPE),
            }],
            'systemProtocols': [] if identifier != IDS[1] else [
                'com.apple.link.systemProtocol.LongRunning',
                'com.apple.link.systemProtocol.ProgressReporting',
                'com.apple.link.systemProtocol.Cancellable',
            ],
        })
    return result


class IdentityValidationTests(unittest.TestCase):
    def test_thin_actual_signature_slot(self):
        self.assertEqual(validator.arm64_entitlements(executable()), entitlements())

    def test_fat_slice_signature_offsets(self):
        thin = executable()
        prefix = struct.pack('>II', 0xCAFEBABE, 1) + struct.pack('>IIIII', validator.ARM64, 0, 32, len(thin), 0)
        self.assertEqual(validator.arm64_entitlements(prefix + b'\0' * (32 - len(prefix)) + thin), entitlements())

    def test_current_info_without_legacy_ALTAppGroups(self):
        self.assertEqual(validator.identity_report(info(), executable())['status'], 'passed_unsigned_identity_only')

    def test_legacy_info_group_matches_signed_group(self):
        value = info(); value['ALTAppGroups'] = ['group.com.SideStore.SideStore']
        validator.identity_report(value, executable())

    def test_changed_bundle_rejected(self):
        value = info(); value['CFBundleIdentifier'] += '.Beta'
        with self.assertRaisesRegex(ValueError, 'bundle identity'):
            validator.identity_report(value, executable())

    def test_changed_signed_group_rejected(self):
        value = entitlements(); value['com.apple.security.application-groups'] = ['group.somewhere.else']
        with self.assertRaisesRegex(ValueError, 'App Group'):
            validator.identity_report(info(), executable(value))

    def test_personal_application_identifier_rejected(self):
        value = entitlements(); value['application-identifier'] = 'PERSONAL12.com.SideStore.SideStore'
        with self.assertRaisesRegex(ValueError, 'application identity'):
            validator.identity_report(info(), executable(value))

    def test_personal_team_rejected(self):
        value = entitlements(); value['com.apple.developer.team-identifier'] = 'PERSONAL12'
        with self.assertRaisesRegex(ValueError, 'team identity'):
            validator.identity_report(info(), executable(value))

    def test_wrong_keychain_group_rejected(self):
        value = entitlements(); value['keychain-access-groups'] = ['XYZ0123456.another.app']
        with self.assertRaisesRegex(ValueError, 'keychain'):
            validator.identity_report(info(), executable(value))

    def test_changed_URL_scheme_rejected(self):
        value = info(); value['CFBundleURLTypes'] = []
        with self.assertRaisesRegex(ValueError, 'URL identities'):
            validator.identity_report(value, executable())

    def test_missing_bonjour_rejected(self):
        value = info(); value['NSBonjourServices'] = []
        with self.assertRaisesRegex(ValueError, 'Bonjour'):
            validator.identity_report(value, executable())

    def test_missing_actual_signature_rejected(self):
        with self.assertRaises(ValueError):
            validator.arm64_entitlements(executable()[:48])

    def test_metadata_String_and_ticket_schema(self):
        self.assertEqual(set(validator.validate_wire_actions(actions(), IDS)), set(IDS))

    def test_metadata_wrong_output_type_rejected(self):
        value = actions(); value[1]['outputType'] = {'primitive': {'wrapper': {'typeIdentifier': 2}}}
        with self.assertRaisesRegex(ValueError, 'String metadata'):
            validator.validate_wire_actions(value, IDS)

    def test_metadata_missing_runID_rejected(self):
        value = actions(); value[1]['parameters'] = []
        with self.assertRaisesRegex(ValueError, 'parameter schema'):
            validator.validate_wire_actions(value, IDS)

    def test_metadata_duplicate_identifier_rejected(self):
        value = actions(); value.append(value[0])
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            validator.validate_wire_actions(value, IDS)

    def test_metadata_missing_cancel_protocol_rejected(self):
        value = actions(); value[1]['systemProtocols'] = []
        with self.assertRaisesRegex(ValueError, 'cancellation protocols'):
            validator.validate_wire_actions(value, IDS)

    def test_full_IPA_and_source_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); ipa = root / 'synthetic.ipa'
            with zipfile.ZipFile(ipa, 'w') as archive:
                archive.writestr('Payload/SideStore.app/Info.plist', plistlib.dumps(info()))
                archive.writestr('Payload/SideStore.app/SideStore', executable())
                archive.writestr('Payload/SideStore.app/Metadata.appintents/extract.actionsdata',
                                 json.dumps({'actions': {a['identifier']: a for a in actions()}}))
            report = validator.inspect(ipa, IDS, root / 'good', '151d3378')
            self.assertEqual(report['status'], 'passed')
            with self.assertRaisesRegex(ValueError, 'selected upstream'):
                validator.inspect(ipa, IDS, root / 'wrong_source', '6032424a')


if __name__ == '__main__':
    unittest.main(verbosity=2)
