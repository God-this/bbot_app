import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/chat_models.dart';

/// 401 Unauthorized 응답 시 throw되는 예외
class AuthException implements Exception {
  const AuthException();
}

/// BeBot 백엔드 API 서비스
class BeBotApiService {
  final String baseUrl;
  String? _token;

  BeBotApiService({required this.baseUrl, String? token}) : _token = token;

  void setToken(String? token) => _token = token;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
      };

  /// 질문을 백엔드로 전송하고 답변 + 출처 + 세션 ID를 받아옴
  Future<({String answer, SourceInfo sources, int? sessionId})> sendQuestion(
      String question, {int? sessionId}) async {
    try {
      final body = <String, dynamic>{'question': question};
      if (sessionId != null) body['session_id'] = sessionId;

      final response = await http.post(
        Uri.parse('$baseUrl/api/chat'),
        headers: _headers,
        body: jsonEncode(body),
      );

      if (response.statusCode == 401) throw const AuthException();

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
          sessionId: data['session_id'] as int?,
        );
      } else {
        throw Exception('서버 오류: ${response.statusCode}');
      }
    } on AuthException {
      rethrow;
    } catch (e) {
      throw Exception('네트워크 오류: $e');
    }
  }

  /// 내 대화 세션 목록 조회
  Future<List<Map<String, dynamic>>> getSessions() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/api/chat/sessions'),
        headers: _headers,
      );
      if (response.statusCode == 401) throw const AuthException();
      if (response.statusCode == 200) {
        final list = jsonDecode(utf8.decode(response.bodyBytes)) as List<dynamic>;
        return list.cast<Map<String, dynamic>>();
      }
      throw Exception('서버 오류: ${response.statusCode}');
    } on AuthException {
      rethrow;
    } catch (e) {
      throw Exception('네트워크 오류: $e');
    }
  }

  /// 세션의 메시지 목록 조회
  Future<List<Map<String, dynamic>>> getSessionMessages(int sessionId) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/api/chat/sessions/$sessionId/messages'),
        headers: _headers,
      );
      if (response.statusCode == 401) throw const AuthException();
      if (response.statusCode == 200) {
        final list = jsonDecode(utf8.decode(response.bodyBytes)) as List<dynamic>;
        return list.cast<Map<String, dynamic>>();
      }
      throw Exception('서버 오류: ${response.statusCode}');
    } on AuthException {
      rethrow;
    } catch (e) {
      throw Exception('네트워크 오류: $e');
    }
  }

  /// 세션 삭제
  Future<void> deleteSession(int sessionId) async {
    try {
      final response = await http.delete(
        Uri.parse('$baseUrl/api/chat/sessions/$sessionId'),
        headers: _headers,
      );
      if (response.statusCode == 401) throw const AuthException();
      if (response.statusCode != 200) {
        throw Exception('서버 오류: ${response.statusCode}');
      }
    } on AuthException {
      rethrow;
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
