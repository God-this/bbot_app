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

  ChatProvider({required BeBotApiService api, required AuthProvider auth})
      : _api  = api,
        _auth = auth;

  List<ChatMessage> get messages    => _messages;
  bool              get isTyping    => _isTyping;
  String?           get error       => _error;
  bool              get hasMessages => _messages.isNotEmpty;

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

    final loadingMsg = ChatMessage(
      id:        _uuid.v4(),
      content:   '',
      isUser:    false,
      timestamp: DateTime.now(),
      isLoading: true,
    );
    _messages.add(loadingMsg);
    _isTyping = true;
    notifyListeners();

    try {
      final result = await _api.sendQuestion(text.trim());

      final index = _messages.indexWhere((m) => m.id == loadingMsg.id);
      if (index != -1) {
        _messages[index] = ChatMessage(
          id:        loadingMsg.id,
          content:   result.answer,
          isUser:    false,
          timestamp: DateTime.now(),
          sources:   result.sources,
        );
      }
    } on AuthException {
      // 토큰 만료: 로그아웃 처리
      _messages.removeWhere((m) => m.id == loadingMsg.id || m.id == userMsg.id);
      await _auth.onUnauthorized();
      return;
    } catch (e) {
      final index = _messages.indexWhere((m) => m.id == loadingMsg.id);
      if (index != -1) {
        _messages[index] = ChatMessage(
          id:        loadingMsg.id,
          content:   '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.\n다시 시도해 주세요.',
          isUser:    false,
          timestamp: DateTime.now(),
        );
      }
      _error = e.toString();
    } finally {
      _isTyping = false;
      notifyListeners();
    }
  }

  void clearChat() {
    _messages = [];
    _error    = null;
    _isTyping = false;
    notifyListeners();
  }
}
