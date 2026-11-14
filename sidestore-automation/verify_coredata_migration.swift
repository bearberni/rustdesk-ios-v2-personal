import Foundation
import CoreData
import ObjectiveC
import CryptoKit

// Synthetic data only. This tests compiled official models and inferred SQLite
// migration, not app startup, Keychain, pairing or the phone's real data.
enum GateError: Error { case failed(String) }

func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
    guard try condition() else { throw GateError.failed(message) }
}

func digest(_ url: URL) throws -> String {
    SHA256.hash(data: try Data(contentsOf: url)).map { String(format: "%02x", $0) }.joined()
}

func installSyntheticManagedClasses(_ model: NSManagedObjectModel) throws {
    // Preserve official model descriptions/hashes; provide empty app classes.
    for entity in model.entities {
        guard let name = entity.managedObjectClassName, NSClassFromString(name) == nil else { continue }
        guard let type = name.withCString({ objc_allocateClassPair(NSManagedObject.self, $0, 0) }) else {
            throw GateError.failed("Could not register synthetic model class")
        }
        objc_registerClassPair(type)
    }
}

func openStore(_ model: NSManagedObjectModel, at url: URL) throws -> (NSPersistentStoreCoordinator, NSManagedObjectContext) {
    let coordinator = NSPersistentStoreCoordinator(managedObjectModel: model)
    try coordinator.addPersistentStore(
        ofType: NSSQLiteStoreType, configurationName: nil, at: url,
        options: [NSSQLitePragmasOption: ["journal_mode": "DELETE"],
                  NSMigratePersistentStoresAutomaticallyOption: false,
                  NSInferMappingModelAutomaticallyOption: false]
    )
    let context = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    context.persistentStoreCoordinator = coordinator
    return (coordinator, context)
}

func closeStore(_ coordinator: NSPersistentStoreCoordinator, _ context: NSManagedObjectContext) throws {
    context.performAndWait { context.reset() }
    for store in coordinator.persistentStores { try coordinator.remove(store) }
}

func populateRequiredAttributes(_ object: NSManagedObject, label: String) throws {
    for (name, attribute) in object.entity.attributesByName where !attribute.isOptional && !attribute.isTransient {
        if let value = attribute.defaultValue { object.setValue(value, forKey: name); continue }
        switch attribute.attributeType {
        case .stringAttributeType:
            object.setValue("synthetic.\(label).\(name)", forKey: name)
        case .dateAttributeType:
            object.setValue(Date(timeIntervalSince1970: 1_800_000_000), forKey: name)
        case .booleanAttributeType, .integer16AttributeType, .integer32AttributeType, .integer64AttributeType:
            object.setValue(NSNumber(value: 1), forKey: name)
        case .floatAttributeType, .doubleAttributeType, .decimalAttributeType:
            object.setValue(NSNumber(value: 1), forKey: name)
        case .binaryDataAttributeType:
            object.setValue(Data("synthetic".utf8), forKey: name)
        case .URIAttributeType:
            object.setValue(URL(string: "https://synthetic.invalid/\(label)/\(name)")!, forKey: name)
        default:
            throw GateError.failed("Unsupported mandatory fixture attribute: \(object.entity.name ?? "?").\(name)")
        }
    }
}

func createFixture(_ context: NSManagedObjectContext) throws {
    try context.performAndWait {
        func insert(_ entity: String, _ label: String) throws -> NSManagedObject {
            let object = NSEntityDescription.insertNewObject(forEntityName: entity, into: context)
            try populateRequiredAttributes(object, label: label)
            return object
        }
        let account = try insert("Account", "account")
        account.setValue("synthetic-user@example.invalid", forKey: "appleID")
        account.setValue("synthetic-account", forKey: "identifier")
        let team = try insert("Team", "team")
        team.setValue("SYNTHETIC0", forKey: "identifier")
        team.setValue(account, forKey: "account")
        let sideStore = try insert("InstalledApp", "sidestore")
        sideStore.setValue("com.synthetic.SideStore", forKey: "bundleIdentifier")
        sideStore.setValue("com.synthetic.SideStore.SYNTHETIC0", forKey: "resignedBundleIdentifier")
        sideStore.setValue(team, forKey: "team")
        let rustDesk = try insert("InstalledApp", "rustdesk")
        rustDesk.setValue("com.synthetic.RustDeskV2", forKey: "bundleIdentifier")
        rustDesk.setValue("com.synthetic.RustDeskV2.SYNTHETIC0", forKey: "resignedBundleIdentifier")
        rustDesk.setValue(team, forKey: "team")
        let appExtension = try insert("InstalledExtension", "extension")
        appExtension.setValue("com.synthetic.SideStore.Widget", forKey: "bundleIdentifier")
        appExtension.setValue("com.synthetic.SideStore.Widget.SYNTHETIC0", forKey: "resignedBundleIdentifier")
        appExtension.setValue(sideStore, forKey: "parentApp")
        try context.save()
    }
}

func stableLabel(_ object: NSManagedObject) -> String {
    let entity = object.entity.name!
    let key = object.entity.attributesByName["identifier"] != nil ? "identifier" : "bundleIdentifier"
    return "\(entity):\(object.value(forKey: key) as! String)"
}

func valueString(_ value: Any?) -> String {
    switch value {
    case nil: return "<nil>"
    case let date as Date: return "date:\(date.timeIntervalSince1970)"
    case let data as Data: return "data:\(data.base64EncodedString())"
    case let url as URL: return "url:\(url.absoluteString)"
    case let number as NSNumber: return "number:\(number.stringValue)"
    case let text as String: return "text:\(text)"
    default: return "unsupported:\(String(describing: type(of: value!)))"
    }
}

func snapshot(_ context: NSManagedObjectContext, sourceModel: NSManagedObjectModel) throws -> Data {
    try context.performAndWait {
        var rows: [[String: Any]] = []
        for name in ["Account", "Team", "InstalledApp", "InstalledExtension"] {
            let request = NSFetchRequest<NSManagedObject>(entityName: name)
            for object in try context.fetch(request) {
                var attributes: [String: String] = [:]
                for (key, attribute) in sourceModel.entitiesByName[name]!.attributesByName where !attribute.isTransient {
                    attributes[key] = valueString(object.value(forKey: key))
                }
                var relationships: [String: [String]] = [:]
                for (key, relation) in sourceModel.entitiesByName[name]!.relationshipsByName {
                    let value = object.value(forKey: key)
                    if relation.isToMany {
                        let objects: [NSManagedObject]
                        if relation.isOrdered {
                            objects = (value as? NSOrderedSet)?.array as? [NSManagedObject] ?? []
                        } else {
                            objects = (value as? NSSet)?.allObjects as? [NSManagedObject] ?? []
                        }
                        let labels = objects.map(stableLabel)
                        relationships[key] = relation.isOrdered ? labels : labels.sorted()
                    } else {
                        relationships[key] = (value as? NSManagedObject).map { [stableLabel($0)] } ?? []
                    }
                }
                rows.append(["label": stableLabel(object), "attributes": attributes, "relationships": relationships])
            }
        }
        rows.sort { ($0["label"] as! String) < ($1["label"] as! String) }
        return try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys, .prettyPrinted])
    }
}

func main() throws {
    guard CommandLine.arguments.count == 4 else { throw GateError.failed("Expected old.mom new.mom output-directory") }
    let args = CommandLine.arguments
    guard let oldModel = NSManagedObjectModel(contentsOf: URL(fileURLWithPath: args[1])),
          let newModel = NSManagedObjectModel(contentsOf: URL(fileURLWithPath: args[2])) else {
        throw GateError.failed("Compiled model could not be loaded")
    }
    try installSyntheticManagedClasses(oldModel)
    try installSyntheticManagedClasses(newModel)
    try require(oldModel.entitiesByName["InstalledApp"]?.attributesByName["appBundleFingerprint"] == nil,
                "Expected17_6 without fingerprint")
    let added = newModel.entitiesByName["InstalledApp"]?.attributesByName["appBundleFingerprint"]
    try require(added?.isOptional == true && added?.attributeType == .stringAttributeType,
                "Expected17_7 optional String fingerprint")

    let output = URL(fileURLWithPath: args[3], isDirectory: true)
    try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
    let oldURL = output.appendingPathComponent("synthetic-17_6.sqlite")
    let migratedURL = output.appendingPathComponent("synthetic-17_7.sqlite")
    try require(!FileManager.default.fileExists(atPath: oldURL.path)
                && !FileManager.default.fileExists(atPath: migratedURL.path), "Use a fresh output directory")

    let (oldCoordinator, oldContext) = try openStore(oldModel, at: oldURL)
    try createFixture(oldContext)
    let before = try snapshot(oldContext, sourceModel: oldModel)
    try before.write(to: output.appendingPathComponent("before.json"))
    try closeStore(oldCoordinator, oldContext)
    let oldHash = try digest(oldURL)
    let mapping = try NSMappingModel.inferredMappingModel(forSourceModel: oldModel, destinationModel: newModel)
    let manager = NSMigrationManager(sourceModel: oldModel, destinationModel: newModel)
    try manager.migrateStore(from: oldURL, sourceType: NSSQLiteStoreType,
        options: [NSSQLitePragmasOption: ["journal_mode": "DELETE"]],
        with: mapping, toDestinationURL: migratedURL, destinationType: NSSQLiteStoreType,
        destinationOptions: [NSSQLitePragmasOption: ["journal_mode": "DELETE"]])
    try require(try digest(oldURL) == oldHash, "Migration changed the source store")
    let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
        ofType: NSSQLiteStoreType, at: migratedURL, options: nil)
    try require(newModel.isConfiguration(withName: nil, compatibleWithStoreMetadata: metadata),
                "Migrated metadata does not match17_7")
    try require(!oldModel.isConfiguration(withName: nil, compatibleWithStoreMetadata: metadata),
                "Old17_6 unexpectedly accepts new schema")

    let (newCoordinator, newContext) = try openStore(newModel, at: migratedURL)
    let after = try snapshot(newContext, sourceModel: oldModel)
    try after.write(to: output.appendingPathComponent("after.json"))
    try require(before == after, "Common attributes or relationships changed")
    try newContext.performAndWait {
        let apps = try newContext.fetch(NSFetchRequest<NSManagedObject>(entityName: "InstalledApp"))
        try require(apps.count == 2, "Expected both app records")
        try require(apps.allSatisfy { $0.value(forKey: "appBundleFingerprint") == nil }, "Added optional field is not nil")
    }
    try closeStore(newCoordinator, newContext)
    let (reopenedCoordinator, reopenedContext) = try openStore(newModel, at: migratedURL)
    try require(try snapshot(reopenedContext, sourceModel: oldModel) == before, "Reopened data changed")
    try closeStore(reopenedCoordinator, reopenedContext)
    let report: [String: Any] = [
        "passed": true, "syntheticOnly": true, "schema": "17_6 ->17_7",
        "mapping": "NSMappingModel.inferredMappingModel",
        "checks": ["source_unchanged", "destination_metadata", "old_schema_rejected",
                   "common_attributes_preserved", "relationships_preserved",
                   "both_apps_preserved", "new_optional_field_nil", "reopen_preserved"],
        "phoneRuntimeVerified": false, "maintenanceFileMigrationVerified": false,
        "accountKeychainPairingVerified": false
    ]
    try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted])
        .write(to: output.appendingPathComponent("migration-report.json"))
    print("PASS: synthetic CoreData17_6 ->17_7; eight checks; phone and maintenance acceptance remain separate")
}

do {
    try main()
} catch {
    fputs("FAIL: synthetic CoreData migration: \(error)\n", stderr)
    exit(1)
}
