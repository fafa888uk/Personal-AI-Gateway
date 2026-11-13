/// SSE parsing for OpenAI-style chat completion streams, plus semver
/// comparison for the version check. Pure Dart, no Flutter dependency,
/// so it is unit-tested without widgets.
library;

import 'dart:convert';

import 'models.dart';

/// One parsed chunk of a chat-completion stream.
class ChatStreamEvent {
  ChatStreamEvent.delta(this.delta)
      : usage = null,
        isDone = false,
        error = null;

  ChatStreamEvent.usage({required int? tokensIn, required int? tokensOut})
      : delta = '',
        usage = ChatUsage(tokensIn, tokensOut),
        isDone = false,
        error = null;

  ChatStreamEvent.done()
      : delta = '',
        usage = null,
        isDone = true,
        error = null;

  ChatStreamEvent.error(this.error)
      : delta = '',
        usage = null,
        isDone = false;

  final String delta;
  final ChatUsage? usage;
  final bool isDone;
  final GatewayException? error;

  int? get tokensIn => usage?.tokensIn;
  int? get tokensOut => usage?.tokensOut;
}

/// Token usage reported by the server for one completed reply.
class ChatUsage {
  const ChatUsage(this.tokensIn, this.tokensOut);
  final int? tokensIn;
  final int? tokensOut;
}

/// Incremental SSE parser.
///
/// Feed raw text chunks as they arrive; [feed] returns the events that
/// became complete. Handles:
/// - `data: {...}` JSON lines (chat completion chunks),
/// - `data: [DONE]` end-of-stream marker,
/// - `data: {"error": ...}` error events (gateway error shape),
/// - partial lines split across chunk boundaries (buffered),
/// - comment lines (`: ...`) and `event:` lines (ignored).
class SseParser {
  String _buffer = '';

  /// Feed a raw text chunk; returns newly completed events.
  List<ChatStreamEvent> feed(String chunk) {
    _buffer += chunk;
    final events = <ChatStreamEvent>[];
    var newline = _buffer.indexOf('\n');
    while (newline >= 0) {
      var line = _buffer.substring(0, newline);
      _buffer = _buffer.substring(newline + 1);
      if (line.endsWith('\r')) {
        line = line.substring(0, line.length - 1);
      }
      events.addAll(_handleLine(line));
      newline = _buffer.indexOf('\n');
    }
    return events;
  }

  /// Flush any trailing partial line at stream end.
  List<ChatStreamEvent> finish() {
    if (_buffer.trim().isEmpty) {
      _buffer = '';
      return const [];
    }
    final line = _buffer;
    _buffer = '';
    return _handleLine(line);
  }

  List<ChatStreamEvent> _handleLine(String line) {
    if (line.isEmpty || line.startsWith(':') || line.startsWith('event:')) {
      return const [];
    }
    if (!line.startsWith('data:')) {
      return const [];
    }
    final data = line.substring('data:'.length).trim();
    if (data.isEmpty) {
      return const [];
    }
    if (data == '[DONE]') {
      return [ChatStreamEvent.done()];
    }
    Map<String, dynamic> json;
    try {
      final decoded = jsonDecode(data);
      if (decoded is! Map<String, dynamic>) {
        return const [];
      }
      json = decoded;
    } on FormatException {
      return const [];
    }
    if (json.containsKey('error')) {
      final err = json['error'];
      if (err is Map<String, dynamic>) {
        return [
          ChatStreamEvent.error(
            GatewayException(
              err['message'] as String? ?? '上游返回错误',
              code: err['code'] as String?,
            ),
          ),
        ];
      }
      return [
        ChatStreamEvent.error(GatewayException('上游返回错误')),
      ];
    }
    final events = <ChatStreamEvent>[];
    final choices = json['choices'];
    if (choices is List) {
      for (final choice in choices) {
        if (choice is Map<String, dynamic>) {
          final delta = choice['delta'];
          if (delta is Map<String, dynamic>) {
            final content = delta['content'];
            if (content is String && content.isNotEmpty) {
              events.add(ChatStreamEvent.delta(content));
            }
          }
        }
      }
    }
    final usage = json['usage'];
    if (usage is Map<String, dynamic>) {
      events.add(
        ChatStreamEvent.usage(
          tokensIn: usage['prompt_tokens'] as int?,
          tokensOut: usage['completion_tokens'] as int?,
        ),
      );
    }
    return events;
  }
}

/// Parse a whole SSE body at once (convenience for tests).
List<ChatStreamEvent> parseSseText(String text) {
  final parser = SseParser();
  final events = parser.feed(text);
  events.addAll(parser.finish());
  return events;
}

/// Compare two semver-ish version strings: -1 if [a] < [b], 0 if equal,
/// 1 if [a] > [b]. Numeric parts compare numerically; missing parts count
/// as 0; a pre-release suffix (after `-`) sorts below the same release.
int compareVersions(String a, String b) {
  String core(String v) => v.split('-').first;
  String pre(String v) {
    final idx = v.indexOf('-');
    return idx >= 0 ? v.substring(idx + 1) : '';
  }

  final aParts = core(a).split('.');
  final bParts = core(b).split('.');
  final len = aParts.length > bParts.length ? aParts.length : bParts.length;
  for (var i = 0; i < len; i++) {
    final av = i < aParts.length ? int.tryParse(aParts[i]) ?? 0 : 0;
    final bv = i < bParts.length ? int.tryParse(bParts[i]) ?? 0 : 0;
    if (av != bv) {
      return av < bv ? -1 : 1;
    }
  }
  final ap = pre(a);
  final bp = pre(b);
  if (ap == bp) {
    return 0;
  }
  if (ap.isEmpty) {
    return 1; // release > pre-release
  }
  if (bp.isEmpty) {
    return -1;
  }
  return ap.compareTo(bp) < 0 ? -1 : 1;
}
