import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';
import '../models/chat_models.dart';
import '../services/api_service.dart';

class ChatProvider extends ChangeNotifier {
  final BeBotApiService _api;
  final _uuid = const Uuid();

  List<ChatMessage> _messages = [];
  bool _isTyping = false;
  String? _error;

  ChatProvider({required BeBotApiService api}) : _api = api;

  List<ChatMessage> get messages => _messages;
  bool get isTyping => _isTyping;
  String? get error => _error;
  bool get hasMessages => _messages.isNotEmpty;

  /// 추천 질문 리스트
  List<SuggestedQuestion> get suggestedQuestions => [
        SuggestedQuestion(text: '성경은 어디에서 왔으며,\n정말 하나님의 말씀인가요?'),
        SuggestedQuestion(text: '공룡이 실제로 존재했나요?'),
        SuggestedQuestion(
            text: '성경 인물들의 나이와 족보를 통해\n지구의 나이를 계산하는 방법은 무엇인가요?'),
      ];

  /// 사용자 메시지 전송 및 AI 응답 처리
  Future<void> sendMessage(String text) async {
    if (text.trim().isEmpty) return;

    _error = null;

    // 사용자 메시지 추가
    final userMsg = ChatMessage(
      id: _uuid.v4(),
      content: text.trim(),
      isUser: true,
      timestamp: DateTime.now(),
    );
    _messages.add(userMsg);

    // 로딩 메시지 추가
    final loadingMsg = ChatMessage(
      id: _uuid.v4(),
      content: '',
      isUser: false,
      timestamp: DateTime.now(),
      isLoading: true,
    );
    _messages.add(loadingMsg);
    _isTyping = true;
    notifyListeners();

    try {
      final result = await _api.sendQuestion(text.trim());

      // 로딩 메시지를 실제 답변으로 교체
      final index = _messages.indexWhere((m) => m.id == loadingMsg.id);
      if (index != -1) {
        _messages[index] = ChatMessage(
          id: loadingMsg.id,
          content: result.answer,
          isUser: false,
          timestamp: DateTime.now(),
          sources: result.sources,
        );
      }
    } catch (e) {
      // 로딩 메시지를 에러 메시지로 교체
      final index = _messages.indexWhere((m) => m.id == loadingMsg.id);
      if (index != -1) {
        _messages[index] = ChatMessage(
          id: loadingMsg.id,
          content: '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.\n다시 시도해 주세요.',
          isUser: false,
          timestamp: DateTime.now(),
        );
      }
      _error = e.toString();
    } finally {
      _isTyping = false;
      notifyListeners();
    }
  }

  /// 대화 내역 초기화
  void clearChat() {
    _messages = [];
    _error = null;
    _isTyping = false;
    notifyListeners();
  }
}
