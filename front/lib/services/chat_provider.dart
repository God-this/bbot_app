import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';
import '../models/chat_models.dart';
import '../services/api_service.dart';
import '../services/auth_provider.dart';

class ChatProvider extends ChangeNotifier {
  final BeBotApiService _api;
  final AuthProvider    _auth;
  final _uuid = const Uuid();

  List<ChatMessage> _messages = [];
  bool _isTyping = false;
  String? _error;

  List<ChatSession> _sessions = [];
  bool _isLoadingSessions = false;
  bool _isLoadingSession  = false;
  int? _activeSessionId;

  ChatProvider({required BeBotApiService api, required AuthProvider auth})
      : _api  = api,
        _auth = auth;

  List<ChatMessage> get messages           => _messages;
  bool              get isTyping           => _isTyping;
  String?           get error              => _error;
  bool              get hasMessages        => _messages.isNotEmpty;
  List<ChatSession> get sessions           => _sessions;
  bool              get isLoadingSessions  => _isLoadingSessions;
  bool              get isLoadingSession   => _isLoadingSession;
  int?              get activeSessionId    => _activeSessionId;

  List<SuggestedQuestion> get suggestedQuestions => [
        SuggestedQuestion(text: '핀치새 부리는 분명히 변했는데,\n왜 진화의 증거가 아닐까?'),
        SuggestedQuestion(text: '창세기 때의 수명과 지금 수명이 다른 이유가 뭘까?'),
        SuggestedQuestion(text: '방주에서 살아남은 공룡,\n왜 결국 멸종되었을까?'),
      ];

  Future<void> sendMessage(String text) async {
    if (text.trim().isEmpty) return;

    _error = null;

    final userMsg = ChatMessage(
      id:        _uuid.v4(),
      content:   text.trim(),
      isUser:    true,
      timestamp: DateTime.now(),
    );
    _messages.add(userMsg);

    final botMsgId = _uuid.v4();
    _messages.add(ChatMessage(
      id:        botMsgId,
      content:   '',
      isUser:    false,
      timestamp: DateTime.now(),
      isLoading: true,
    ));
    _isTyping = true;
    notifyListeners();

    try {
      final result = await _api.sendQuestionStream(
        text.trim(),
        sessionId: _activeSessionId,
        onToken: (token) {
          final idx = _messages.indexWhere((m) => m.id == botMsgId);
          if (idx != -1) {
            _messages[idx] = _messages[idx].copyWith(
              content:   _messages[idx].content + token,
              isLoading: false,
            );
            notifyListeners();
          }
        },
      );

      if (result.sessionId != null) _activeSessionId = result.sessionId;

      final idx = _messages.indexWhere((m) => m.id == botMsgId);
      if (idx != -1) {
        _messages[idx] = _messages[idx].copyWith(
          sources:   result.sources,
          isLoading: false,
        );
      }
    } on AuthException {
      _messages.removeWhere((m) => m.id == botMsgId || m.id == userMsg.id);
      await _auth.onUnauthorized();
      return;
    } catch (e) {
      final idx = _messages.indexWhere((m) => m.id == botMsgId);
      if (idx != -1) {
        _messages[idx] = _messages[idx].copyWith(
          content:   '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.\n다시 시도해 주세요.',
          isLoading: false,
        );
      }
      _error = e.toString();
    } finally {
      _isTyping = false;
      notifyListeners();
    }
  }

  void clearChat() {
    _messages        = [];
    _error           = null;
    _isTyping        = false;
    _activeSessionId = null;
    notifyListeners();
  }

  // ─── 세션 목록 ───────────────────────────────────────────

  Future<void> fetchSessions() async {
    if (_isLoadingSessions) return;
    _isLoadingSessions = true;
    notifyListeners();

    try {
      final raw = await _api.getSessions();
      _sessions = raw.map(ChatSession.fromMap).toList();
    } on AuthException {
      await _auth.onUnauthorized();
      return;
    } catch (e) {
      debugPrint('세션 목록 로드 실패: $e');
    } finally {
      _isLoadingSessions = false;
      notifyListeners();
    }
  }

  // ─── 세션 메시지 불러오기 ────────────────────────────────

  Future<void> loadSession(int sessionId) async {
    _isLoadingSession = true;
    _error            = null;
    notifyListeners();

    try {
      final raw = await _api.getSessionMessages(sessionId);
      _messages = raw.map((m) {
        final role      = m['role'] as String? ?? 'user';
        final sourcesRaw = m['sources'] as Map<String, dynamic>?;
        return ChatMessage(
          id:        m['id'].toString(),
          content:   m['content'] as String? ?? '',
          isUser:    role == 'user',
          timestamp: DateTime.parse(m['created_at'] as String),
          sources:   role == 'assistant' ? _parseSourceInfo(sourcesRaw) : null,
        );
      }).toList();
      _activeSessionId = sessionId;
    } on AuthException {
      await _auth.onUnauthorized();
      return;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoadingSession = false;
      notifyListeners();
    }
  }

  // ─── 세션 삭제 ───────────────────────────────────────────

  Future<void> deleteSession(int sessionId) async {
    try {
      await _api.deleteSession(sessionId);
      _sessions.removeWhere((s) => s.id == sessionId);
      if (_activeSessionId == sessionId) {
        _messages        = [];
        _activeSessionId = null;
      }
      notifyListeners();
    } on AuthException {
      await _auth.onUnauthorized();
    } catch (e) {
      debugPrint('세션 삭제 실패: $e');
    }
  }

  // ─── 소스 파싱 헬퍼 ─────────────────────────────────────

  SourceInfo? _parseSourceInfo(Map<String, dynamic>? sources) {
    if (sources == null) return null;
    final web   = (sources['web_docs']   as List<dynamic>? ?? [])
        .map((d) => WebSource.fromMap(d as Map<String, dynamic>)).toList();
    final book  = (sources['book_docs']  as List<dynamic>? ?? [])
        .map((d) => BookSource.fromMap(d as Map<String, dynamic>)).toList();
    final video = (sources['video_docs'] as List<dynamic>? ?? [])
        .map((d) => VideoSource.fromMap(d as Map<String, dynamic>)).toList();
    final info  = SourceInfo(webSources: web, bookSources: book, videoSources: video);
    return info.isEmpty ? null : info;
  }
}
