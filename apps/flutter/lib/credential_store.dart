/// Credential storage for the Flutter client.
///
/// The client key is a bearer secret: it must never be logged, never be
/// put in a URL, and never be stored in plain shared preferences.
///
/// Storage by platform:
/// - iOS / macOS / Windows: `flutter_secure_storage` (Keychain /
///   Keychain-equivalent secure store).
/// - Linux (local dev only): secure storage needs libsecret and is often
///   unavailable, so the fallback is a JSON file at
///   `~/.config/personal_ai_gateway/credentials.json` created with mode
///   0600 (owner read/write only). Documented, Linux-only, never used on
///   the release targets.
/// - Tests: [MemoryCredentialStore] (in-memory only).
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract class CredentialStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
  Future<void> clearAll();
}

/// Keys used by the app. The client key is stored under 'client_key'.
class CredentialKeys {
  static const baseUrl = 'base_url';
  static const clientKey = 'client_key';
  static const selectedModel = 'selected_model';
  static const streamingEnabled = 'streaming_enabled';
}

/// Secure-store implementation (iOS / macOS / Windows).
class SecureCredentialStore implements CredentialStore {
  SecureCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);

  @override
  Future<void> clearAll() => _storage.deleteAll();
}

/// Linux-only fallback: a JSON file with mode 0600.
///
/// Only used on Linux (local development). The file lives outside the
/// app bundle at ~/.config/personal_ai_gateway/credentials.json and is
/// created with owner-only permissions. If the file exists with wider
/// permissions it is tightened on every write.
class FileCredentialStore implements CredentialStore {
  FileCredentialStore({String? filePath})
      : _filePath = filePath ??
            '${Platform.environment['HOME'] ?? ''}/.config/personal_ai_gateway/credentials.json';

  final String _filePath;

  File get _file => File(_filePath);

  Future<Map<String, String>> _load() async {
    try {
      if (!await _file.exists()) {
        return {};
      }
      final raw = await _file.readAsString();
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        return {};
      }
      return decoded.map((k, v) => MapEntry(k, v.toString()));
    } on Exception {
      return {};
    }
  }

  Future<void> _save(Map<String, String> data) async {
    await _file.parent.create(recursive: true);
    await _file.writeAsString(jsonEncode(data), flush: true);
    // Owner read/write only (0600). Best effort on platforms that
    // support POSIX permissions; Linux dev machines do.
    try {
      await Process.run('chmod', ['600', _filePath]);
    } on Exception {
      // Non-POSIX platform: the file is still outside the app bundle,
      // but permissions could not be tightened. Never used there.
    }
  }

  @override
  Future<String?> read(String key) async => (await _load())[key];

  @override
  Future<void> write(String key, String value) async {
    final data = await _load();
    data[key] = value;
    await _save(data);
  }

  @override
  Future<void> delete(String key) async {
    final data = await _load();
    data.remove(key);
    await _save(data);
  }

  @override
  Future<void> clearAll() async {
    if (await _file.exists()) {
      await _file.delete();
    }
  }
}

/// In-memory store for unit/widget tests. Nothing is persisted.
class MemoryCredentialStore implements CredentialStore {
  final Map<String, String> _data = {};

  @override
  Future<String?> read(String key) async => _data[key];

  @override
  Future<void> write(String key, String value) async {
    _data[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    _data.remove(key);
  }

  @override
  Future<void> clearAll() async {
    _data.clear();
  }
}

/// Picks the right store for the current platform:
/// Linux -> 0600-file fallback (dev only); everything else -> secure store.
CredentialStore defaultCredentialStore() {
  if (Platform.isLinux) {
    return FileCredentialStore();
  }
  return SecureCredentialStore();
}
