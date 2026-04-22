import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/chat_models.dart';

/// BeBot 백엔드 API 서비스
/// Python FastAPI/Flask 백엔드와 통신
class BeBotApiService {
  final String baseUrl;

  BeBotApiService({required this.baseUrl});

  /// 질문을 백엔드로 전송하고 답변 + 출처를 받아옴
  /// 
  /// 백엔드 엔드포인트: POST /api/chat
  /// Request body: { "question": "..." }
  /// Response: { "answer": "...", "sources": { "web_docs": [...], "book_docs": [...], "video_docs": [...] } }
  Future<({String answer, SourceInfo sources})> sendQuestion(
      String question) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/chat'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'question': question}),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(utf8.decode(response.bodyBytes));
        final answer = data['answer'] as String? ?? '';
        final sourcesData = data['sources'] as Map<String, dynamic>? ?? {};

        final webDocs = (sourcesData['web_docs'] as List<dynamic>? ?? [])
            .map((d) => WebSource.fromMap(d as Map<String, dynamic>))
            .toList();
        final bookDocs = (sourcesData['book_docs'] as List<dynamic>? ?? [])
            .map((d) => BookSource.fromMap(d as Map<String, dynamic>))
            .toList();
        final videoDocs = (sourcesData['video_docs'] as List<dynamic>? ?? [])
            .map((d) => VideoSource.fromMap(d as Map<String, dynamic>))
            .toList();

        return (
          answer: answer,
          sources: SourceInfo(
            webSources: webDocs,
            bookSources: bookDocs,
            videoSources: videoDocs,
          ),
        );
      } else {
        throw Exception('서버 오류: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('네트워크 오류: $e');
    }
  }

  /// 서버 상태 확인
  Future<bool> healthCheck() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/api/health'));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}
