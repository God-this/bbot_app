import 'dart:async';
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

  /// 스트리밍 질문 전송 — 토큰을 onToken 콜백으로 실시간 전달
  Future<({SourceInfo sources, int? sessionId})> sendQuestionStream(
    String question, {
    int? sessionId,
    required void Function(String token) onToken,
    void Function(SourceInfo sources)? onSources,
  }) async {
    final body = <String, dynamic>{'question': question};
    if (sessionId != null) body['session_id'] = sessionId;

    final request = http.Request('POST', Uri.parse('$baseUrl/api/chat/stream'))
      ..headers.addAll(_headers)
      ..body = jsonEncode(body);

    final streamedResponse = await request.send();

    if (streamedResponse.statusCode == 401) throw const AuthException();
    if (streamedResponse.statusCode != 200) {
      throw Exception('서버 오류: ${streamedResponse.statusCode}');
    }

    SourceInfo sources = SourceInfo();
    int? newSessionId;

    // 서버는 토큰 → [DONE] → [SOURCES] → [SESSION] 순으로 보내고,
    // 그 뒤 캐시 저장(임베딩 API 호출, 수 초)을 마친 다음에야 연결을 닫는다.
    // 연결 종료를 기다리면 답변이 끝난 뒤에도 입력창이 묶이므로,
    // 답변에 필요한 이벤트를 모두 받은 시점에 곧바로 완료 처리한다.
    final completer = Completer<void>();
    final buffer = StringBuffer();
    var streamDone = false;
    var sourcesReceived = false;

    void finishIfReady() {
      // [DONE] 이후 오는 [SOURCES]까지 받으면 더 기다릴 이유가 없다.
      // [SESSION]은 새 대화일 때만 오므로 완료 조건에 넣지 않는다.
      if (streamDone && sourcesReceived && !completer.isCompleted) {
        completer.complete();
      }
    }

    late final StreamSubscription<String> subscription;
    subscription = streamedResponse.stream.transform(utf8.decoder).listen(
      (chunk) {
        buffer.write(chunk);
        final raw = buffer.toString();
        final events = raw.split('\n\n');
        buffer.clear();
        if (!raw.endsWith('\n\n')) {
          buffer.write(events.removeLast());
        }

        for (final event in events) {
          if (event.isEmpty) continue;
          final data = event.replaceFirst('data: ', '');

          if (data == '[DONE]') {
            streamDone = true;
            finishIfReady();
          } else if (data.startsWith('[SOURCES]')) {
            final jsonStr = data.replaceFirst('[SOURCES]', '');
            try {
              final map = jsonDecode(jsonStr) as Map<String, dynamic>;
              sources = _parseSourceInfoFromMap(map);
              // 스트림 종료를 기다리지 않고 즉시 UI에 반영
              onSources?.call(sources);
            } catch (_) {}
            sourcesReceived = true;
            finishIfReady();
          } else if (data.startsWith('[SESSION]')) {
            newSessionId = int.tryParse(data.replaceFirst('[SESSION]', ''));
          } else {
            onToken(data.replaceAll('\\n', '\n'));
          }
        }
      },
      // 연결이 먼저 닫히는 경우(오류·조기 종료)에도 대기를 풀어준다.
      onDone: () {
        if (!completer.isCompleted) completer.complete();
      },
      onError: (e) {
        if (!completer.isCompleted) completer.completeError(e);
      },
      cancelOnError: true,
    );

    try {
      await completer.future;
    } finally {
      // 남은 캐시 저장 구간을 기다리지 않고 연결을 정리한다.
      unawaited(subscription.cancel());
    }
    return (sources: sources, sessionId: newSessionId);
  }

  SourceInfo _parseSourceInfoFromMap(Map<String, dynamic> map) {
    final web = (map['web_docs'] as List<dynamic>? ?? [])
        .map((d) => WebSource.fromMap(d as Map<String, dynamic>))
        .toList();
    final book = (map['book_docs'] as List<dynamic>? ?? [])
        .map((d) => BookSource.fromMap(d as Map<String, dynamic>))
        .toList();
    final video = (map['video_docs'] as List<dynamic>? ?? [])
        .map((d) => VideoSource.fromMap(d as Map<String, dynamic>))
        .toList();
    return SourceInfo(webSources: web, bookSources: book, videoSources: video);
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
