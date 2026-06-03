import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/admin_models.dart';

class AdminApiService {
  final String baseUrl;
  String? _token;

  AdminApiService({required this.baseUrl, String? token}) : _token = token;

  void setToken(String? token) => _token = token;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
      };

  Future<VideoStatusResponse> getVideoStatus() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/api/admin/video-status'), headers: _headers)
          .timeout(const Duration(seconds: 60));

      if (response.statusCode == 200) {
        final data =
            jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
        return VideoStatusResponse.fromMap(data);
      }
      throw Exception('서버 오류: ${response.statusCode}');
    } catch (e) {
      throw Exception('영상 상태 조회 실패: $e');
    }
  }

  Future<VideoStatusResponse> refreshVideoStatus() async {
    try {
      final response = await http
          .post(Uri.parse('$baseUrl/api/admin/video-status/refresh'),
              headers: _headers)
          .timeout(const Duration(seconds: 120));

      if (response.statusCode == 200) {
        final data =
            jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
        return VideoStatusResponse.fromMap(data);
      }
      throw Exception('서버 오류: ${response.statusCode}');
    } catch (e) {
      throw Exception('영상 상태 갱신 실패: $e');
    }
  }
}
