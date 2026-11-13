/// Data models for the Personal AI Gateway Flutter client.
///
/// All models are parsed from the real gateway API. Nothing here invents
/// a model status, a version, a cost or a token count: values come from
/// the server, and missing values stay missing (null), never guessed.
library;

/// Error surfaced from the gateway. [code] is the gateway's real error
/// code (e.g. `invalid_client_key`, `model_not_verified`, `budget_exceeded`)
/// and [message] its real message.
class GatewayException implements Exception {
  GatewayException(this.message, {this.code, this.status});

  final String message;
  final String? code;
  final int? status;

  @override
  String toString() => 'GatewayException($status $code): $message';
}

/// A model returned by GET /v1/models. The gateway only returns
/// verified + enabled models, so every model in this list is "已验证可用".
/// Models not returned are never shown as verified.
class GatewayModel {
  GatewayModel({required this.id, this.created});

  factory GatewayModel.fromJson(Map<String, dynamic> json) {
    return GatewayModel(
      id: json['id'] as String? ?? '',
      created: json['created'] as int?,
    );
  }

  final String id;
  final int? created;

  /// Display-only pinned-version group, e.g. "gpt-5.4" for
  /// "gpt-5.4-2026-03-05". Never used to claim a different model exists.
  String get pinnedGroup {
    final parts = id.split('-');
    if (parts.length >= 3 &&
        parts.last.length == 8 &&
        int.tryParse(parts.last) != null) {
      return parts.sublist(0, parts.length - 1).join('-');
    }
    return id;
  }
}

/// One chat session from GET /api/v1/chats.
class ChatSession {
  ChatSession({
    required this.id,
    required this.title,
    this.model,
    this.createdAt,
    this.updatedAt,
  });

  factory ChatSession.fromJson(Map<String, dynamic> json) {
    return ChatSession(
      id: json['id'] as int,
      title: json['title'] as String? ?? '',
      model: json['model'] as String?,
      createdAt: json['created_at'] as String?,
      updatedAt: json['updated_at'] as String?,
    );
  }

  final int id;
  final String title;
  final String? model;
  final String? createdAt;
  final String? updatedAt;

  String get displayTitle => title.isEmpty ? '新对话' : title;
}

/// One message from GET /api/v1/chats/{id}/messages.
class ChatMessage {
  ChatMessage({
    this.id,
    required this.role,
    required this.content,
    this.model,
    this.tokensIn,
    this.tokensOut,
    this.createdAt,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    return ChatMessage(
      id: json['id'] as int?,
      role: json['role'] as String? ?? '',
      content: json['content'] as String? ?? '',
      model: json['model'] as String?,
      tokensIn: json['tokens_in'] as int?,
      tokensOut: json['tokens_out'] as int?,
      createdAt: json['created_at'] as String?,
    );
  }

  final int? id;
  final String role; // user | assistant | system
  final String content;
  final String? model;
  final int? tokensIn;
  final int? tokensOut;
  final String? createdAt;

  bool get isUser => role == 'user';
  bool get hasUsage => tokensIn != null || tokensOut != null;
}

/// One platform entry from GET /api/v1/app/version.
class PlatformRelease {
  PlatformRelease({
    required this.version,
    this.releaseDate,
    required this.downloadUrl,
    this.sha256,
    this.releaseNotes,
  });

  factory PlatformRelease.fromJson(Map<String, dynamic> json) {
    return PlatformRelease(
      version: json['version'] as String? ?? '',
      releaseDate: json['release_date'] as String?,
      downloadUrl: json['download_url'] as String? ?? '',
      sha256: json['sha256'] as String?,
      releaseNotes: json['release_notes'] as String?,
    );
  }

  final String version;
  final String? releaseDate;
  final String downloadUrl;
  final String? sha256;
  final String? releaseNotes;
}

/// Release info from GET /api/v1/app/version.
/// When [configured] is false the server has no release info and the UI
/// must say so — never fake a version.
class AppVersionInfo {
  AppVersionInfo({
    required this.configured,
    this.version,
    this.gatewayVersion,
    Map<String, PlatformRelease>? platforms,
  }) : platforms = platforms ?? {};

  factory AppVersionInfo.fromJson(Map<String, dynamic> json) {
    final raw = json['platforms'];
    final platforms = <String, PlatformRelease>{};
    if (raw is Map<String, dynamic>) {
      for (final entry in raw.entries) {
        if (entry.value is Map<String, dynamic>) {
          platforms[entry.key] =
              PlatformRelease.fromJson(entry.value as Map<String, dynamic>);
        }
      }
    }
    return AppVersionInfo(
      configured: json['configured'] as bool? ?? false,
      version: json['version'] as String?,
      gatewayVersion: json['gateway_version'] as String?,
      platforms: platforms,
    );
  }

  factory AppVersionInfo.unconfigured() => AppVersionInfo(configured: false);

  final bool configured;
  final String? version;
  final String? gatewayVersion;
  final Map<String, PlatformRelease> platforms;
}

/// Per-model usage row from GET /api/v1/usage/summary.
class UsageByModel {
  UsageByModel({
    required this.model,
    required this.requests,
    required this.tokensIn,
    required this.tokensOut,
    required this.costUsd,
  });

  factory UsageByModel.fromJson(Map<String, dynamic> json) {
    return UsageByModel(
      model: json['model'] as String? ?? '',
      requests: json['requests'] as int? ?? 0,
      tokensIn: json['tokens_in'] as int? ?? 0,
      tokensOut: json['tokens_out'] as int? ?? 0,
      costUsd: (json['cost_usd'] as num?)?.toDouble() ?? 0.0,
    );
  }

  final String model;
  final int requests;
  final int tokensIn;
  final int tokensOut;
  final double costUsd;
}

/// Usage summary from GET /api/v1/usage/summary.
///
/// Server-side totals for the calling client key only.
/// [costStatus] is exactly what the gateway computes:
/// - "ok": every counted cost is exact.
/// - "price_not_configured": at least one record has no price — the cost
///   shown is a partial sum, never a complete total.
/// - "not_obtained": at least one record has no upstream usage — the cost
///   shown is a partial sum, never a complete total.
class UsageSummary {
  UsageSummary({
    required this.period,
    required this.requests,
    required this.tokensIn,
    required this.tokensOut,
    required this.costUsd,
    required this.costStatus,
    List<UsageByModel>? byModel,
  }) : byModel = byModel ?? [];

  factory UsageSummary.fromJson(Map<String, dynamic> json) {
    final raw = json['by_model'];
    final rows = <UsageByModel>[];
    if (raw is List) {
      for (final item in raw) {
        if (item is Map<String, dynamic>) {
          rows.add(UsageByModel.fromJson(item));
        }
      }
    }
    return UsageSummary(
      period: json['period'] as String? ?? '',
      requests: json['requests'] as int? ?? 0,
      tokensIn: json['tokens_in'] as int? ?? 0,
      tokensOut: json['tokens_out'] as int? ?? 0,
      costUsd: (json['cost_usd'] as num?)?.toDouble() ?? 0.0,
      costStatus: json['cost_status'] as String? ?? 'not_obtained',
      byModel: rows,
    );
  }

  final String period; // today | month
  final int requests;
  final int tokensIn;
  final int tokensOut;
  final double costUsd;
  final String costStatus;
  final List<UsageByModel> byModel;

  /// True only when the cost is a complete exact total.
  bool get costIsExact => costStatus == 'ok';

  String get costStatusLabel {
    switch (costStatus) {
      case 'ok':
        return '费用已按真实用量与定价计算';
      case 'price_not_configured':
        return '部分模型未配置价格，费用为不完整合计';
      case 'not_obtained':
        return '部分请求未返回用量，费用为不完整合计';
      default:
        return '费用状态未知：$costStatus';
    }
  }
}
